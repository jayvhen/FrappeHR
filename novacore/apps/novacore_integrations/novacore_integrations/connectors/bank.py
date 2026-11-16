"""Bank API Adapter (R4 - salaries sent via secured bank API on payday).

Runs after HR/Finance approval releases a payroll. With the bank API enabled, the
batch is sent over HTTPS with an OAuth2 client-credentials token. Otherwise (or if the
API fails) a disbursement CSV is attached to the Payroll Entry for manual upload, so a
payroll is never released without a disbursement artifact.
"""

import csv
import io

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime
from frappe.utils.file_manager import save_file

from novacore_integrations.connectors.http import get_settings, oauth2_client_credentials, request


def get_disbursement_lines(payroll_entry: str) -> list[dict]:
	slips = frappe.get_all(
		"Salary Slip",
		filters={"payroll_entry": payroll_entry, "docstatus": 1},
		fields=["name", "employee", "employee_name", "rounded_total", "net_pay", "bank_name", "bank_account_no"],
		order_by="employee_name",
	)
	lines = []
	for s in slips:
		amount = flt(s.rounded_total) or flt(s.net_pay)
		if amount <= 0:
			continue
		bank_name = s.bank_name or frappe.db.get_value("Employee", s.employee, "bank_name")
		account_no = s.bank_account_no or frappe.db.get_value("Employee", s.employee, "bank_ac_no")
		lines.append(
			{
				"reference": s.name,
				"employee": s.employee,
				"employee_name": s.employee_name,
				"bank_name": bank_name or "",
				"account_number": account_no or "",
				"amount": amount,
			}
		)
	return lines


def disburse_payroll(payroll_entry):
	lines = get_disbursement_lines(payroll_entry.name)
	if not lines:
		payroll_entry.db_set("disbursement_status", "Nothing to Disburse")
		return

	missing = [l["employee_name"] for l in lines if not l["account_number"]]
	settings = get_settings()

	if cint(settings.bank_enabled) and not missing:
		try:
			token = oauth2_client_credentials(
				"Bank Payroll API",
				settings.bank_token_url,
				settings.bank_client_id,
				settings.get_password("bank_client_secret"),
			)
			body = request(
				"Bank Payroll API",
				"POST",
				settings.bank_api_url,
				json_body={
					"batch_reference": payroll_entry.name,
					"source_account": settings.bank_source_account,
					"value_date": str(payroll_entry.posting_date),
					"currency": payroll_entry.currency,
					"total_amount": sum(l["amount"] for l in lines),
					"credits": lines,
				},
				headers={"Authorization": f"Bearer {token}"},
				reference=payroll_entry,
			)
			payroll_entry.db_set(
				{
					"disbursement_status": "Sent to Bank",
					"disbursement_reference": str(body.get("batch_id") or body.get("reference") or "")[:140],
					"disbursed_on": now_datetime(),
				}
			)
			payroll_entry.add_comment("Info", _("Disbursement batch sent to bank for {0} employees").format(len(lines)))
			return
		except Exception:
			frappe.log_error(title=f"Bank disbursement failed for {payroll_entry.name}")

	attach_disbursement_file(payroll_entry, lines)
	reason = (
		_("Missing bank account for: {0}").format(", ".join(missing))
		if missing
		else _("Bank API disabled or unavailable")
	)
	payroll_entry.db_set("disbursement_status", "File Ready")
	payroll_entry.add_comment("Info", _("Disbursement file attached for manual upload. {0}").format(reason))


def attach_disbursement_file(payroll_entry, lines):
	buffer = io.StringIO()
	writer = csv.DictWriter(
		buffer, fieldnames=["reference", "employee", "employee_name", "bank_name", "account_number", "amount"]
	)
	writer.writeheader()
	writer.writerows(lines)
	save_file(
		f"disbursement-{payroll_entry.name}.csv",
		buffer.getvalue().encode("utf-8"),
		payroll_entry.doctype,
		payroll_entry.name,
		is_private=1,
	)


@frappe.whitelist()
def retry_disbursement(payroll_entry: str):
	frappe.only_for(("HR Finance Manager", "System Manager"))
	doc = frappe.get_doc("Payroll Entry", payroll_entry)
	if not cint(doc.salary_slips_submitted):
		frappe.throw(_("Salary slips are not yet released"))
	if doc.disbursement_status == "Sent to Bank":
		frappe.throw(_("This payroll was already sent to the bank"))
	disburse_payroll(doc)
	return doc.reload().disbursement_status

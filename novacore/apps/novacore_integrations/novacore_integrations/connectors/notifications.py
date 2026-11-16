"""Notification Service: SMS notice when salary slips are released (Sequence Diagram 12, step 17).

E-mailing the slip itself is handled by Frappe HR ("Email Salary Slip to Employee" in
Payroll Settings). SMS uses Frappe's SMS Settings gateway.
"""

import frappe
from frappe import _
from frappe.utils import cint, fmt_money


def send_payslip_notices(payroll_entry):
	if not cint(frappe.db.get_single_value("NovaCore Integration Settings", "sms_payslip_notice")):
		return
	if not frappe.db.get_single_value("SMS Settings", "sms_gateway_url"):
		frappe.log_error(title="Payslip SMS skipped", message="SMS Settings has no gateway URL configured")
		return

	from frappe.core.doctype.sms_settings.sms_settings import send_sms

	slips = frappe.get_all(
		"Salary Slip",
		filters={"payroll_entry": payroll_entry.name, "docstatus": 1},
		fields=["employee", "employee_name", "rounded_total", "currency", "end_date"],
	)
	for slip in slips:
		number = frappe.db.get_value("Employee", slip.employee, "cell_number")
		if not number:
			continue
		message = _("Hi {0}, your salary for the period ending {1} ({2}) has been released. View your payslip in Frappe HR.").format(
			slip.employee_name.split(" ")[0],
			frappe.format(slip.end_date, "Date"),
			fmt_money(slip.rounded_total, currency=slip.currency),
		)
		try:
			send_sms([number], message, success_msg=False)
		except Exception:
			frappe.log_error(title=f"Payslip SMS failed for {slip.employee}")

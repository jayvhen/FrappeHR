"""R1 - All HR requests are approved in-system with 24h escalation.

Runs hourly. Any Leave Application / Overtime Request still Open after the configured
window is re-routed to the department manager (or next level up), shared with them,
assigned as a ToDo and flagged as escalated so it is escalated only once.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from novacore_ph.workflow.approvers import get_escalation_approver, share_with_approver

# doctype -> approver fieldname
ESCALATED_DOCTYPES = {
	"Leave Application": "leave_approver",
	"Overtime Request": "approver",
}


def escalate_pending_requests():
	settings = frappe.get_cached_doc("PH Statutory Settings")
	hours = cint(settings.escalate_after_hours) or 24
	cutoff = add_to_date(now_datetime(), hours=-hours)

	for doctype, approver_field in ESCALATED_DOCTYPES.items():
		pending = frappe.get_all(
			doctype,
			filters={
				"docstatus": 0,
				"status": "Open",
				"escalated": 0,
				"creation": ("<", cutoff),
			},
			fields=["name", "employee", "employee_name", approver_field],
			limit=500,
		)
		for row in pending:
			try:
				escalate(doctype, row, approver_field)
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title=f"Escalation failed for {doctype} {row.name}")


def escalate(doctype: str, row, approver_field: str):
	current = row.get(approver_field)
	new_approver = get_escalation_approver(row.employee, current)
	values = {"escalated": 1, "escalated_on": now_datetime()}
	if new_approver:
		values[approver_field] = new_approver
	frappe.db.set_value(doctype, row.name, values, update_modified=False)

	doc = frappe.get_doc(doctype, row.name)
	doc.add_comment(
		"Info",
		_("Escalated: not approved within the escalation window. Re-routed from {0} to {1}.").format(
			current or _("(none)"), new_approver or _("HR")
		),
	)

	recipients = [new_approver] if new_approver else get_hr_managers()
	for user in recipients:
		share_with_approver(doc, user)

	from novacore_ph.utils import assign_to

	assign_to(
		doctype,
		row.name,
		recipients,
		_("Escalated {0} for {1} awaiting approval").format(_(doctype), row.employee_name),
		priority="High",
	)


def get_hr_managers() -> list[str]:
	return [
		u.parent
		for u in frappe.get_all(
			"Has Role", filters={"role": "HR Manager", "parenttype": "User"}, fields=["parent"]
		)
		if u.parent not in ("Administrator", "Guest")
		and frappe.db.get_value("User", u.parent, "enabled")
	]

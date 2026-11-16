"""Approver resolution shared by leave/overtime requests and escalation."""

import frappe


def get_employee_user(employee: str | None) -> str | None:
	if not employee:
		return None
	return frappe.db.get_value("Employee", employee, "user_id")


def get_default_approver(employee: str) -> str | None:
	"""Team Leader first (reports_to), then the department manager."""
	reports_to = frappe.db.get_value("Employee", employee, "reports_to")
	user = get_employee_user(reports_to)
	return user or get_department_manager(employee)


def get_department_manager(employee: str) -> str | None:
	department = frappe.db.get_value("Employee", employee, "department")
	if not department:
		return None
	return frappe.db.get_value("Department", department, "department_manager")


def get_escalation_approver(employee: str, current_approver: str | None) -> str | None:
	"""Escalate to the department manager; if that is already the approver,
	go one level up the reporting line (the approver's own Team Leader)."""
	manager = get_department_manager(employee)
	if manager and manager != current_approver:
		return manager

	approver_employee = frappe.db.get_value("Employee", {"user_id": current_approver}, "name")
	if approver_employee:
		next_up = get_employee_user(frappe.db.get_value("Employee", approver_employee, "reports_to"))
		if next_up and next_up != current_approver:
			return next_up
	return None


def share_with_approver(doc, approver: str | None):
	"""Approvers are usually restricted by Employee user permissions, so share the
	request with them explicitly to allow review and submission."""
	if not approver or approver in ("Administrator", "Guest"):
		return
	if not frappe.db.exists("User", approver):
		return
	from frappe.share import add_docshare

	add_docshare(doc.doctype, doc.name, approver, read=1, write=1, submit=1, flags={"ignore_share_permission": True},
				 notify=0)

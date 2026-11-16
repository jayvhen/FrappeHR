"""Shared helpers."""

import frappe
from frappe.utils import nowdate


def send_email(**kwargs):
	"""frappe.sendmail that never breaks the business action that triggered it.

	Without an outgoing Email Account (normal on a fresh install) sendmail raises
	OutgoingEmailError, which would roll back e.g. a payroll rejection. Notifications
	are best-effort: failures are logged to Error Log instead.
	"""
	try:
		frappe.sendmail(**kwargs)
	except Exception:
		frappe.log_error(title=f"Notification email not sent: {kwargs.get('subject', '')}"[:140])


def assign_to(doctype: str, name: str, users: list[str], description: str, priority: str = "Medium"):
	"""Create a ToDo for each user and share the document with them.

	Used by system processes (escalation, lifecycle jobs, payroll approval, integrations)
	where the acting user is not necessarily allowed to read the document, so
	frappe.desk.form.assign_to.add() - which checks the caller's permission - does not fit.
	Skips users who already have an open ToDo for the document.
	"""
	from frappe.share import add_docshare

	for user in dict.fromkeys(u for u in users if u):
		if not frappe.db.get_value("User", user, "enabled"):
			continue
		if frappe.db.exists(
			"ToDo", {"reference_type": doctype, "reference_name": name, "allocated_to": user, "status": "Open"}
		):
			continue
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": user,
				"reference_type": doctype,
				"reference_name": name,
				"description": description,
				"priority": priority,
				"status": "Open",
				"date": nowdate(),
				"assigned_by": frappe.session.user,
			}
		).insert(ignore_permissions=True)
		if user != "Administrator" and not frappe.has_permission(doctype, "read", name, user=user):
			add_docshare(doctype, name, user, read=1, write=1, flags={"ignore_share_permission": True}, notify=0)

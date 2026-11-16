# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from novacore_ph.utils import send_email


class HRHelpdeskTicket(Document):
	def before_validate(self):
		if not self.employee and self.is_new():
			self.employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")

	def validate(self):
		if self.is_new() and not self.can_manage():
			# employees can only raise tickets; HR triages them
			self.status = "Open"
			self.assigned_to = None

		if self.status in ("Resolved", "Closed"):
			if not self.resolution:
				frappe.throw(_("Enter the resolution before marking the ticket {0}").format(self.status))
			if not self.resolved_on:
				self.resolved_on = now_datetime()
		else:
			self.resolved_on = None

		previous = self.get_doc_before_save()
		if previous and previous.status != self.status and not self.can_manage():
			frappe.throw(_("Only HR can change the ticket status"), frappe.PermissionError)

	def on_update(self):
		previous = self.get_doc_before_save()
		if self.assigned_to and (not previous or previous.assigned_to != self.assigned_to):
			from novacore_ph.utils import assign_to

			assign_to(self.doctype, self.name, [self.assigned_to], self.subject)

		if previous and previous.status != self.status and self.status in ("Resolved", "Closed"):
			owner_email = frappe.db.get_value("User", self.owner, "email")
			if owner_email:
				send_email(
					recipients=[owner_email],
					subject=_("HR Ticket {0} {1}").format(self.name, self.status),
					message=_("Your HR helpdesk ticket <b>{0}</b> was marked {1}.<br><br>{2}").format(
						frappe.utils.escape_html(self.subject), self.status, self.resolution or ""
					),
					reference_doctype=self.doctype,
					reference_name=self.name,
				)

	@staticmethod
	def can_manage():
		return bool({"HR Manager", "HR User", "System Manager"} & set(frappe.get_roles()))

# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from novacore_ph.workflow.approvers import get_default_approver, share_with_approver


class OvertimeRequest(Document):
	def validate(self):
		if flt(self.hours) <= 0 or flt(self.hours) > 16:
			frappe.throw(_("Overtime Hours must be greater than 0 and at most 16"))
		if getdate(self.date) > getdate(today()) and self.status == "Approved":
			frappe.throw(_("Overtime for a future date cannot be approved yet"))

		duplicate = frappe.db.exists(
			"Overtime Request",
			{
				"employee": self.employee,
				"date": self.date,
				"docstatus": ("<", 2),
				"status": ("!=", "Rejected"),
				"name": ("!=", self.name),
			},
		)
		if duplicate:
			frappe.throw(
				_("Overtime Request {0} already exists for this employee on {1}").format(
					frappe.bold(duplicate), frappe.format(self.date, "Date")
				),
				frappe.DuplicateEntryError,
			)

		if not self.approver:
			self.approver = get_default_approver(self.employee)

	def on_update(self):
		share_with_approver(self, self.approver)

	def before_submit(self):
		if self.status == "Open":
			frappe.throw(_("Set the status to Approved or Rejected before submitting"))
		self.validate_approver()

	def validate_approver(self):
		roles = frappe.get_roles()
		if frappe.session.user == self.approver or {"HR Manager", "HR User", "System Manager"} & set(roles):
			return
		frappe.throw(_("Only the approver ({0}) or HR can approve or reject this request").format(self.approver),
					 frappe.PermissionError)

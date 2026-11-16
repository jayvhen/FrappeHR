# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document

EVENT_FIELDS = {
	"employee.created": "on_employee_created",
	"employee.updated": "on_employee_updated",
	"employee.separated": "on_employee_separated",
	"payroll.released": "on_payroll_released",
}


class ERPEventSubscription(Document):
	def validate(self):
		self.endpoint_url = (self.endpoint_url or "").strip()
		url = self.endpoint_url.lower()
		if not url.startswith(("https://", "http://")):
			frappe.throw(_("Endpoint URL must start with https://"))
		if url.startswith("http://") and not frappe.conf.developer_mode:
			frappe.throw(_("Endpoint URL must use HTTPS outside developer mode"))
		if not any(self.get(f) for f in EVENT_FIELDS.values()):
			frappe.throw(_("Select at least one event"))

	@frappe.whitelist()
	def send_test_event(self):
		from novacore_integrations.erp.events import deliver

		deliver(self.name, "ping", {"message": "NovaCore HR webhook test"})
		return _("Test event sent - see Integration Request log for the result")

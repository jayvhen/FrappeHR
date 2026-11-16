# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

URL_FIELDS = ("bank_api_url", "bank_token_url", "kpi_api_url", "job_board_url", "esign_api_url")


class NovaCoreIntegrationSettings(Document):
	def validate(self):
		for field in URL_FIELDS:
			value = (self.get(field) or "").strip()
			self.set(field, value)
			if value and not value.lower().startswith("https://") and not frappe.conf.developer_mode:
				frappe.throw(_("{0} must use HTTPS").format(self.meta.get_label(field)))
		if not 1 <= cint(self.request_timeout) <= 300:
			frappe.throw(_("Request Timeout must be between 1 and 300 seconds"))
		if not 0 <= cint(self.max_retries) <= 5:
			frappe.throw(_("Retries must be between 0 and 5"))
		if cint(self.biometric_alert_minutes) < 1:
			frappe.throw(_("Device alert window must be at least 1 minute"))

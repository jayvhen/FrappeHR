# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

import re

import frappe
from frappe import _
from frappe.model.document import Document


class BiometricDevice(Document):
	def validate(self):
		self.device_id = (self.device_id or "").strip().upper()
		if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,39}", self.device_id):
			frappe.throw(_("Device ID may only contain letters, digits, '-' and '_' (2-40 characters)"))

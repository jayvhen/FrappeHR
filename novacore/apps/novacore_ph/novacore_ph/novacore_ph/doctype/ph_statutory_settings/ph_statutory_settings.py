# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class PHStatutorySettings(Document):
	def validate(self):
		if cint(self.annual_working_days) <= 0:
			frappe.throw(_("Annual Working Days must be greater than zero"))
		if flt(self.hours_per_day) <= 0 or flt(self.hours_per_day) > 24:
			frappe.throw(_("Hours per Day must be between 0 and 24"))
		if flt(self.night_diff_rate) < 0 or flt(self.overtime_rate) < 0:
			frappe.throw(_("Rates cannot be negative"))
		if cint(self.escalate_after_hours) < 1:
			frappe.throw(_("Escalation window must be at least 1 hour"))
		if cint(self.probation_months) < 1:
			frappe.throw(_("Probation period must be at least 1 month"))
		if cint(self.ot_rounding_minutes) < 0 or cint(self.ot_rounding_minutes) > 60:
			frappe.throw(_("Overtime rounding must be between 0 and 60 minutes"))

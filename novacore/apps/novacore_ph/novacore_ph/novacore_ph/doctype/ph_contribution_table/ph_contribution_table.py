# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class PHContributionTable(Document):
	def validate(self):
		if not self.brackets:
			frappe.throw(_("Add at least one bracket"))

		rows = sorted(self.brackets, key=lambda r: flt(r.from_amount))
		for i, row in enumerate(rows):
			if flt(row.from_amount) < 0 or flt(row.to_amount) < 0:
				frappe.throw(_("Row {0}: amounts cannot be negative").format(row.idx))
			if flt(row.to_amount) and flt(row.to_amount) < flt(row.from_amount):
				frappe.throw(_("Row {0}: To Amount must be greater than From Amount").format(row.idx))
			for field in ("employee_rate", "employer_rate"):
				if not 0 <= flt(row.get(field)) <= 100:
					frappe.throw(_("Row {0}: {1} must be between 0 and 100").format(row.idx, field))
			if flt(row.salary_cap) and flt(row.salary_cap) < flt(row.salary_floor):
				frappe.throw(_("Row {0}: Salary Cap must be greater than Salary Floor").format(row.idx))
			if i and flt(rows[i - 1].to_amount) and flt(row.from_amount) <= flt(rows[i - 1].to_amount):
				frappe.throw(
					_("Brackets overlap: row {0} starts before row {1} ends").format(row.idx, rows[i - 1].idx)
				)

		if self.enabled and frappe.db.exists(
			"PH Contribution Table",
			{
				"agency": self.agency,
				"effective_from": self.effective_from,
				"enabled": 1,
				"name": ("!=", self.name),
			},
		):
			frappe.throw(
				_("Another enabled {0} table is already effective from {1}").format(
					self.agency, frappe.format(self.effective_from, "Date")
				)
			)

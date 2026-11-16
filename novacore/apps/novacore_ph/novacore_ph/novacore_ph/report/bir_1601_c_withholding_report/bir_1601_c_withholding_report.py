# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

import frappe
from frappe import _
from frappe.utils import flt

from novacore_ph.statutory.reports import get_employee_values, parse_period


def execute(filters=None):
	"""Monthly remittance return of income taxes withheld on compensation (BIR Form 1601-C)."""
	month, year = parse_period(filters)
	rows = frappe.db.sql(
		"""
		select ss.employee, ss.employee_name,
			sum(ss.gross_pay) as gross_pay,
			sum(case when c.agency in ('SSS', 'PhilHealth', 'Pag-IBIG') then c.employee_share else 0 end)
				as mandatory_contributions,
			sum(case when c.agency = 'BIR' then c.employee_share else 0 end) as tax_withheld,
			sum(case when c.agency = 'BIR' then c.basis_amount else 0 end) as taxable_compensation
		from `tabSalary Slip` ss
		join `tabPH Statutory Contribution` c
			on c.parent = ss.name and c.parenttype = 'Salary Slip' and c.parentfield = 'ph_statutory_contributions'
		where ss.docstatus = 1 and ss.company = %(company)s
			and month(ss.end_date) = %(month)s and year(ss.end_date) = %(year)s
		group by ss.employee, ss.employee_name
		order by ss.employee_name
		""",
		{"company": filters.get("company"), "month": month, "year": year},
		as_dict=True,
	)
	tins = get_employee_values([r.employee for r in rows], "tin")
	mwe = get_employee_values([r.employee for r in rows], "is_minimum_wage_earner")
	for r in rows:
		r.tin = tins.get(r.employee) or ""
		r.minimum_wage_earner = mwe.get(r.employee) or 0
		r.non_taxable = max(flt(r.gross_pay) - flt(r.mandatory_contributions) - flt(r.taxable_compensation), 0)

	columns = [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 200},
		{"label": _("TIN"), "fieldname": "tin", "fieldtype": "Data", "width": 150},
		{"label": _("MWE"), "fieldname": "minimum_wage_earner", "fieldtype": "Check", "width": 60},
		{"label": _("Gross Compensation"), "fieldname": "gross_pay", "fieldtype": "Currency", "width": 150},
		{"label": _("SSS/PHIC/HDMF (EE)"), "fieldname": "mandatory_contributions", "fieldtype": "Currency",
		 "width": 150},
		{"label": _("Non-taxable Compensation"), "fieldname": "non_taxable", "fieldtype": "Currency", "width": 160},
		{"label": _("Taxable Compensation"), "fieldname": "taxable_compensation", "fieldtype": "Currency",
		 "width": 160},
		{"label": _("Tax Withheld"), "fieldname": "tax_withheld", "fieldtype": "Currency", "width": 130},
	]
	summary = [
		{"label": _("Employees"), "value": len(rows), "datatype": "Int"},
		{"label": _("Total Compensation"), "value": sum(flt(r.gross_pay) for r in rows), "datatype": "Currency"},
		{"label": _("Total Taxes Withheld"), "value": sum(flt(r.tax_withheld) for r in rows),
		 "datatype": "Currency", "indicator": "Blue"},
	]
	return columns, rows, None, None, summary

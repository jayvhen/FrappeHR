"""Shared queries for the government remittance reports (Package Diagram: Gov't Reports)."""

import frappe
from frappe import _
from frappe.utils import cint, flt

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
		  "October", "November", "December"]


def parse_period(filters) -> tuple[int, int]:
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Company is required"))
	if filters.month not in MONTHS:
		frappe.throw(_("Select a valid month"))
	year = cint(filters.year)
	if year < 2000 or year > 2100:
		frappe.throw(_("Select a valid year"))
	return MONTHS.index(filters.month) + 1, year


def contribution_rows(filters, agency: str):
	month, year = parse_period(filters)
	return frappe.db.sql(
		"""
		select ss.employee, ss.employee_name,
			avg(c.basis_amount) as basis_amount,
			sum(c.employee_share) as employee_share,
			sum(c.employer_share) as employer_share,
			sum(c.ec_share) as ec_share
		from `tabSalary Slip` ss
		join `tabPH Statutory Contribution` c
			on c.parent = ss.name and c.parenttype = 'Salary Slip' and c.parentfield = 'ph_statutory_contributions'
		where ss.docstatus = 1 and ss.company = %(company)s
			and month(ss.end_date) = %(month)s and year(ss.end_date) = %(year)s
			and c.agency = %(agency)s
		group by ss.employee, ss.employee_name
		order by ss.employee_name
		""",
		{"company": filters.get("company"), "month": month, "year": year, "agency": agency},
		as_dict=True,
	)


def contribution_report(filters, agency: str, id_field: str, id_label: str, include_ec=False):
	rows = contribution_rows(filters, agency)
	ids = get_employee_values([r.employee for r in rows], id_field)
	for r in rows:
		r.id_number = ids.get(r.employee) or ""
		r.total = flt(r.employee_share) + flt(r.employer_share) + (flt(r.ec_share) if include_ec else 0)
		r.missing_id = 0 if r.id_number else 1

	columns = [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 200},
		{"label": _(id_label), "fieldname": "id_number", "fieldtype": "Data", "width": 160},
		{"label": _("Monthly Basis"), "fieldname": "basis_amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Employee Share"), "fieldname": "employee_share", "fieldtype": "Currency", "width": 130},
		{"label": _("Employer Share"), "fieldname": "employer_share", "fieldtype": "Currency", "width": 130},
	]
	if include_ec:
		columns.append({"label": _("EC"), "fieldname": "ec_share", "fieldtype": "Currency", "width": 100})
	columns.append({"label": _("Total Remittance"), "fieldname": "total", "fieldtype": "Currency", "width": 140})

	missing = sum(r.missing_id for r in rows)
	message = (
		_("{0} employee(s) have no {1} on file. Update their Employee record before filing.").format(missing, id_label)
		if missing
		else None
	)
	summary = [
		{"label": _("Employees"), "value": len(rows), "datatype": "Int"},
		{"label": _("Employee Share"), "value": sum(flt(r.employee_share) for r in rows), "datatype": "Currency"},
		{"label": _("Employer Share"), "value": sum(flt(r.employer_share) for r in rows), "datatype": "Currency"},
		{"label": _("Total Remittance"), "value": sum(flt(r.total) for r in rows), "datatype": "Currency",
		 "indicator": "Blue"},
	]
	return columns, rows, message, None, summary


def get_employee_values(employees: list, fieldname: str) -> dict:
	if not employees:
		return {}
	return dict(
		frappe.get_all("Employee", filters={"name": ("in", employees)}, fields=["name", fieldname], as_list=True)
	)


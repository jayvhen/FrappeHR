# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT

import frappe
from frappe import _
from frappe.utils import flt

ID_FIELDS = {"sss_number": "SSS", "philhealth_number": "PhilHealth", "pagibig_number": "Pag-IBIG", "tin": "TIN"}
VARIANCE_THRESHOLD = 30  # % change in net pay vs the previous slip


def execute(filters=None):
	"""Exceptions the Payroll Officer reviews before requesting approval (Activity Diagram 11)."""
	filters = frappe._dict(filters or {})
	if not filters.payroll_entry and not (filters.company and filters.from_date and filters.to_date):
		frappe.throw(_("Select a Payroll Entry, or a Company with From and To dates"))

	conditions = {"docstatus": ("<", 2)}
	if filters.payroll_entry:
		conditions["payroll_entry"] = filters.payroll_entry
	else:
		conditions.update(
			{"company": filters.company, "start_date": (">=", filters.from_date), "end_date": ("<=", filters.to_date)}
		)

	slips = frappe.get_all(
		"Salary Slip",
		filters=conditions,
		fields=["name", "employee", "employee_name", "start_date", "end_date", "gross_pay", "net_pay",
				"payment_days", "total_working_days", "docstatus"],
		order_by="employee_name",
	)
	employees = {
		e.name: e
		for e in frappe.get_all(
			"Employee",
			filters={"name": ("in", [s.employee for s in slips] or [""])},
			fields=["name", "bank_ac_no", "salary_mode", *ID_FIELDS],
		)
	}

	rows = []
	for s in slips:
		emp = employees.get(s.employee) or frappe._dict()
		issues = []
		if flt(s.net_pay) <= 0:
			issues.append(("High", _("Net pay is zero or negative")))
		if flt(s.payment_days) == 0:
			issues.append(("High", _("No payment days in period")))
		elif flt(s.total_working_days) and flt(s.payment_days) < flt(s.total_working_days):
			issues.append(("Low", _("{0} of {1} days payable (LWOP/absences)").format(
				flt(s.payment_days), flt(s.total_working_days))))
		missing = [label for field, label in ID_FIELDS.items() if not emp.get(field)]
		if missing:
			issues.append(("Medium", _("Missing government IDs: {0}").format(", ".join(missing))))
		if emp.get("salary_mode") == "Bank" and not emp.get("bank_ac_no"):
			issues.append(("High", _("Salary mode is Bank but no bank account number")))
		if not frappe.db.exists("Attendance", {"employee": s.employee, "docstatus": 1,
											   "attendance_date": ("between", [s.start_date, s.end_date])}):
			issues.append(("Medium", _("No submitted attendance in period")))

		previous = frappe.db.get_value(
			"Salary Slip",
			{"employee": s.employee, "docstatus": 1, "end_date": ("<", s.start_date)},
			"net_pay",
			order_by="end_date desc",
		)
		if previous and flt(previous) > 0:
			change = (flt(s.net_pay) - flt(previous)) / flt(previous) * 100
			if abs(change) >= VARIANCE_THRESHOLD:
				issues.append(("Medium", _("Net pay changed {0:+.0f}% vs previous slip").format(change)))

		for severity, issue in issues:
			rows.append({
				"salary_slip": s.name, "employee": s.employee, "employee_name": s.employee_name,
				"severity": severity, "issue": issue, "net_pay": s.net_pay,
			})

	order = {"High": 0, "Medium": 1, "Low": 2}
	rows.sort(key=lambda r: (order[r["severity"]], r["employee_name"] or ""))
	columns = [
		{"label": _("Severity"), "fieldname": "severity", "fieldtype": "Data", "width": 90},
		{"label": _("Salary Slip"), "fieldname": "salary_slip", "fieldtype": "Link", "options": "Salary Slip",
		 "width": 190},
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Issue"), "fieldname": "issue", "fieldtype": "Data", "width": 340},
		{"label": _("Net Pay"), "fieldname": "net_pay", "fieldtype": "Currency", "width": 120},
	]
	high = sum(1 for r in rows if r["severity"] == "High")
	summary = [
		{"label": _("Salary Slips"), "value": len(slips), "datatype": "Int"},
		{"label": _("High Severity"), "value": high, "datatype": "Int", "indicator": "Red" if high else "Green"},
		{"label": _("Total Exceptions"), "value": len(rows), "datatype": "Int"},
	]
	return columns, rows, None, None, summary

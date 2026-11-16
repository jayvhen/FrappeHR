"""Salary Slip `validate` hook - PayrollProcessingService (Composite Structure Diagram).

collector  : AttendanceCollector   -> night-diff / overtime hours from submitted Attendance
earnings   : EarningsCalculator    -> ND premium and approved OT pay
statutory  : StatutoryDeductionEngine -> SSS, PhilHealth, Pag-IBIG, BIR
slipGen    : totals recomputed so gross / deductions / net pay stay consistent

Runs after HRMS has evaluated the salary structure, and is idempotent: every managed
row is removed and recomputed on each save.
"""

import calendar

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from novacore_ph.statutory.engine import MONTHLY_FRACTION, compute_period_contributions, compute_withholding_tax

COUNTRY = "Philippines"


def get_settings():
	return frappe.get_cached_doc("PH Statutory Settings")


def is_ph_company(company: str) -> bool:
	return frappe.get_cached_value("Company", company, "country") == COUNTRY


def apply_ph_payroll(doc, method=None):
	settings = get_settings()
	if not cint(settings.enabled) or not doc.company or not is_ph_company(doc.company):
		return
	if not doc.salary_structure:
		return

	components = get_managed_components(settings)
	remove_managed_rows(doc, components)

	monthly_base = get_monthly_base(doc)
	add_time_based_earnings(doc, settings, monthly_base)
	recompute_gross(doc)
	add_statutory_deductions(doc, settings, monthly_base)
	recompute_net(doc)

	if flt(doc.net_pay) < 0:
		frappe.throw(
			_("Net pay for {0} is negative after statutory deductions. Review the salary structure.").format(
				doc.employee_name
			),
			title=_("Negative Net Pay"),
		)


# --------------------------------------------------------------------- helpers
def get_managed_components(settings) -> dict:
	keys = (
		"sss_component",
		"philhealth_component",
		"pagibig_component",
		"withholding_tax_component",
		"night_diff_component",
		"overtime_component",
	)
	components = {k: settings.get(k) for k in keys}
	missing = [settings.meta.get_label(k) for k, v in components.items() if not v]
	if missing:
		frappe.throw(
			_("Set these components in PH Statutory Settings: {0}").format(", ".join(missing)),
			title=_("PH Payroll Not Configured"),
		)
	return components


def remove_managed_rows(doc, components: dict):
	managed = set(components.values())
	for table in ("earnings", "deductions"):
		rows = [r for r in doc.get(table) if r.salary_component not in managed]
		doc.set(table, rows)
		for i, row in enumerate(rows, start=1):
			row.idx = i
	doc.set("ph_statutory_contributions", [])


def get_monthly_base(doc) -> float:
	ssa = getattr(doc, "_salary_structure_assignment", None)
	base = flt(ssa.get("base")) if ssa else 0
	if not base:
		base = flt(
			frappe.db.get_value(
				"Salary Structure Assignment",
				{
					"employee": doc.employee,
					"salary_structure": doc.salary_structure,
					"docstatus": 1,
					"from_date": ("<=", doc.start_date),
				},
				"base",
				order_by="from_date desc",
			)
		)
	return base


def get_hourly_rate(settings, monthly_base: float) -> float:
	days = cint(settings.annual_working_days) or 261
	hours = flt(settings.hours_per_day) or 8
	return monthly_base * 12 / days / hours


def append_row(doc, table: str, component: str, amount: float):
	amount = flt(amount, doc.precision("gross_pay"))
	if amount <= 0:
		return
	comp = frappe.get_cached_value(
		"Salary Component",
		component,
		["salary_component_abbr", "is_tax_applicable", "depends_on_payment_days"],
		as_dict=True,
	)
	doc.append(
		table,
		{
			"salary_component": component,
			"abbr": comp.salary_component_abbr if comp else None,
			"amount": amount,
			"default_amount": amount,
			"depends_on_payment_days": 0,
			"is_tax_applicable": comp.is_tax_applicable if comp else 0,
		},
	)


# --------------------------------------------------------- AttendanceCollector
def get_attendance_hours(doc) -> list[dict]:
	return frappe.get_all(
		"Attendance",
		filters={
			"employee": doc.employee,
			"docstatus": 1,
			"attendance_date": ("between", [doc.start_date, doc.end_date]),
			"status": ("in", ["Present", "Half Day", "Work From Home"]),
		},
		fields=["attendance_date", "ph_night_diff_hours", "ph_overtime_hours"],
	)


def get_approved_ot(doc) -> dict:
	rows = frappe.get_all(
		"Overtime Request",
		filters={
			"employee": doc.employee,
			"docstatus": 1,
			"status": "Approved",
			"date": ("between", [doc.start_date, doc.end_date]),
		},
		fields=["date", "hours"],
	)
	approved = {}
	for r in rows:
		approved[getdate(r.date)] = approved.get(getdate(r.date), 0) + flt(r.hours)
	return approved


# --------------------------------------------------------- EarningsCalculator
def add_time_based_earnings(doc, settings, monthly_base: float):
	attendance = get_attendance_hours(doc)
	approved_ot = get_approved_ot(doc) if cint(settings.require_ot_approval) else None

	nd_hours = sum(flt(a.ph_night_diff_hours) for a in attendance)
	ot_hours = 0.0
	for a in attendance:
		logged = flt(a.ph_overtime_hours)
		if approved_ot is None:
			ot_hours += logged
		else:
			ot_hours += min(logged, approved_ot.get(getdate(a.attendance_date), 0))

	hourly = get_hourly_rate(settings, monthly_base)

	doc.ph_night_diff_hours = flt(nd_hours, 2)
	doc.ph_overtime_hours = flt(ot_hours, 2)
	append_row(doc, "earnings", settings.night_diff_component, nd_hours * hourly * flt(settings.night_diff_rate) / 100)
	append_row(doc, "earnings", settings.overtime_component, ot_hours * hourly * flt(settings.overtime_rate) / 100)

	# Minimum wage earners still receive ND / OT, but those premiums are tax-exempt (TRAIN law)
	if is_minimum_wage_earner(doc.employee):
		for row in doc.earnings:
			if row.salary_component in (settings.night_diff_component, settings.overtime_component):
				row.is_tax_applicable = 0


def is_minimum_wage_earner(employee: str) -> bool:
	return bool(frappe.db.get_value("Employee", employee, "is_minimum_wage_earner"))


# ---------------------------------------------------- StatutoryDeductionEngine
def is_second_cutoff(doc) -> bool:
	end = getdate(doc.end_date)
	return end.day == calendar.monthrange(end.year, end.month)[1] or getdate(doc.start_date).day > 15


def add_statutory_deductions(doc, settings, monthly_base: float):
	frequency = doc.payroll_frequency or "Monthly"
	if settings.contribution_basis == "Gross Pay" or not monthly_base:
		fraction = MONTHLY_FRACTION.get(frequency, 1.0)
		monthly_comp = flt(doc.gross_pay) / fraction if fraction else flt(doc.gross_pay)
	else:
		monthly_comp = monthly_base

	contributions = compute_period_contributions(
		monthly_comp, frequency, doc.end_date, is_second_cutoff(doc), settings.semi_monthly_deduction
	)

	component_for = {
		"SSS": settings.sss_component,
		"PhilHealth": settings.philhealth_component,
		"Pag-IBIG": settings.pagibig_component,
	}
	total_ee = 0.0
	for c in contributions:
		append_row(doc, "deductions", component_for[c.agency], c.employee_share)
		total_ee += c.employee_share
		doc.append(
			"ph_statutory_contributions",
			{
				"agency": c.agency,
				"basis_amount": c.basis_amount,
				"employee_share": c.employee_share,
				"employer_share": c.employer_share,
				"ec_share": c.ec_share,
				"table_version": c.table_version,
				"currency": doc.currency,
			},
		)

	# BIR withholding on taxable compensation net of mandatory contributions
	taxable = sum(
		flt(r.amount)
		for r in doc.earnings
		if cint(r.is_tax_applicable) and not cint(r.statistical_component) and not cint(r.do_not_include_in_total)
	)
	taxable_net = max(taxable - total_ee, 0)
	tax, version = 0.0, ""
	if not is_minimum_wage_earner(doc.employee):
		tax, version = compute_withholding_tax(taxable_net, frequency, doc.end_date)
	append_row(doc, "deductions", settings.withholding_tax_component, tax)
	doc.append(
		"ph_statutory_contributions",
		{
			"agency": "BIR",
			# taxable compensation net of mandatory contributions (excludes de minimis / exempt pay)
			"basis_amount": flt(taxable_net, 2),
			"employee_share": tax,
			"employer_share": 0,
			"ec_share": 0,
			"table_version": version,
			"currency": doc.currency,
		},
	)


# ------------------------------------------------------------------ totals
def recompute_gross(doc):
	if hasattr(doc, "get_component_totals"):
		doc.gross_pay = doc.get_component_totals("earnings", depends_on_payment_days=1)
	else:
		doc.gross_pay = sum(
			flt(r.amount) for r in doc.earnings if not cint(r.do_not_include_in_total) and not cint(r.statistical_component)
		)
	doc.base_gross_pay = flt(flt(doc.gross_pay) * flt(doc.exchange_rate or 1), doc.precision("base_gross_pay"))


def recompute_net(doc):
	if hasattr(doc, "set_precision_for_component_amounts"):
		doc.set_precision_for_component_amounts()
	if hasattr(doc, "set_net_pay"):
		doc.set_net_pay()
		return

	from frappe.utils import rounded

	doc.total_deduction = sum(
		flt(r.amount) for r in doc.deductions if not cint(r.do_not_include_in_total) and not cint(r.statistical_component)
	)
	doc.base_total_deduction = flt(doc.total_deduction) * flt(doc.exchange_rate or 1)
	doc.net_pay = flt(doc.gross_pay) - flt(doc.total_deduction) - flt(doc.get("total_loan_repayment"))
	doc.rounded_total = rounded(doc.net_pay)
	doc.base_net_pay = flt(doc.net_pay) * flt(doc.exchange_rate or 1)
	doc.base_rounded_total = rounded(doc.base_net_pay)
	if hasattr(doc, "set_net_total_in_words"):
		doc.set_net_total_in_words()

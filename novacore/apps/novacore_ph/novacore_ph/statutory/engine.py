"""PH Statutory Engine (R3 - SSS, PhilHealth, Pag-IBIG and BIR computed automatically).

All rates come from versioned `PH Contribution Table` records, so a new circular is
applied by adding a new table with a later effective date - no code change.

Computation rules per agency
  SSS        bracket matched on monthly compensation -> fixed EE / ER / EC amounts
  PhilHealth rate on compensation clamped to [floor, cap]  (EE share = 2.5%)
  Pag-IBIG   rate on compensation clamped to [floor, cap]  (bracketed: <=1,500 / above)
  BIR        semi-monthly withholding table: base_tax + rate * (taxable - from_amount)
"""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt, getdate

AGENCIES = ("SSS", "PhilHealth", "Pag-IBIG")

# How many semi-monthly periods a payroll period represents (BIR table is semi-monthly)
SEMI_MONTHLY_FACTOR = {
	"Monthly": 2.0,
	"Bimonthly": 1.0,  # Frappe HR "Bimonthly" == twice a month (semi-monthly)
	"Fortnightly": 24 / 26,
	"Weekly": 24 / 52,
	"Daily": 24 / 261,
}

# Fraction of the monthly contribution charged in one payroll period
MONTHLY_FRACTION = {
	"Monthly": 1.0,
	"Bimonthly": 0.5,
	"Fortnightly": 12 / 26,
	"Weekly": 12 / 52,
	"Daily": 12 / 261,
}


@dataclass
class Contribution:
	agency: str
	basis_amount: float
	employee_share: float
	employer_share: float
	ec_share: float
	table_version: str


def get_contribution_table(agency: str, on_date):
	name = frappe.db.get_value(
		"PH Contribution Table",
		{"agency": agency, "enabled": 1, "effective_from": ("<=", getdate(on_date))},
		"name",
		order_by="effective_from desc",
	)
	if not name:
		frappe.throw(
			_("No enabled {0} contribution table effective on {1}. Create one in PH Contribution Table.").format(
				agency, frappe.format(on_date, "Date")
			),
			title=_("Missing Statutory Table"),
		)
	return frappe.get_cached_doc("PH Contribution Table", name)


def find_bracket(table, amount: float):
	amount = flt(amount, 2)
	rows = sorted(table.brackets, key=lambda r: flt(r.from_amount))
	if amount < flt(rows[0].from_amount):
		return rows[0]
	match = rows[0]
	for row in rows:
		upper = flt(row.to_amount)
		if amount >= flt(row.from_amount):
			match = row
			if not upper or amount <= upper:
				return row
	# in a gap between brackets (e.g. 10,416.50) or above the last: use the last one started
	return match


def clamp(amount: float, floor: float, cap: float) -> float:
	amount = flt(amount)
	if flt(floor):
		amount = max(amount, flt(floor))
	if flt(cap):
		amount = min(amount, flt(cap))
	return amount


def compute_monthly_contribution(agency: str, monthly_compensation: float, on_date) -> Contribution:
	table = get_contribution_table(agency, on_date)
	row = find_bracket(table, monthly_compensation)

	if flt(row.employee_amount) or flt(row.employer_amount):
		# fixed-amount bracket (SSS)
		basis = monthly_compensation
		ee, er = flt(row.employee_amount), flt(row.employer_amount)
	else:
		basis = clamp(monthly_compensation, row.salary_floor, row.salary_cap)
		ee = basis * flt(row.employee_rate) / 100
		er = basis * flt(row.employer_rate) / 100

	return Contribution(
		agency=agency,
		basis_amount=flt(basis, 2),
		employee_share=flt(ee, 2),
		employer_share=flt(er, 2),
		ec_share=flt(row.ec_amount, 2),
		table_version=table.version,
	)


def period_share(monthly: Contribution, frequency: str, is_second_cutoff: bool, schedule: str) -> Contribution:
	"""Convert a monthly contribution into this payroll period's share."""
	if frequency == "Bimonthly" and schedule == "Second Cutoff Only":
		fraction = 1.0 if is_second_cutoff else 0.0
	else:
		fraction = MONTHLY_FRACTION.get(frequency, 1.0)

	return Contribution(
		agency=monthly.agency,
		basis_amount=monthly.basis_amount,
		employee_share=flt(monthly.employee_share * fraction, 2),
		employer_share=flt(monthly.employer_share * fraction, 2),
		ec_share=flt(monthly.ec_share * fraction, 2),
		table_version=monthly.table_version,
	)


def compute_withholding_tax(taxable_income: float, frequency: str, on_date) -> tuple[float, str]:
	"""BIR withholding on compensation using the semi-monthly table, scaled to the period."""
	if flt(taxable_income) <= 0:
		return 0.0, ""
	table = get_contribution_table("BIR", on_date)
	factor = SEMI_MONTHLY_FACTOR.get(frequency, 2.0)
	semi_monthly_taxable = flt(taxable_income) / factor
	row = find_bracket(table, semi_monthly_taxable)
	excess = max(semi_monthly_taxable - flt(row.from_amount), 0)
	tax = flt(row.base_tax) + excess * flt(row.employee_rate) / 100
	return flt(tax * factor, 2), table.version


def compute_period_contributions(
	monthly_compensation: float, frequency: str, on_date, is_second_cutoff: bool, schedule: str
) -> list[Contribution]:
	result = []
	for agency in AGENCIES:
		monthly = compute_monthly_contribution(agency, monthly_compensation, on_date)
		result.append(period_share(monthly, frequency, is_second_cutoff, schedule))
	return result

# Copyright (c) 2026, NovaCore Business Solutions Inc.
# License: MIT
"""Run with: bench --site <site> run-tests --app novacore_ph"""

import frappe
from frappe.tests.utils import FrappeTestCase

from novacore_ph.attendance.attendance import compute
from novacore_ph.lifecycle.employee import GOVERNMENT_IDS
from novacore_ph.statutory import engine

DATE = "2026-11-15"
NIGHT = frappe._dict(
	start_time="22:00:00",
	end_time="07:00:00",
	ph_night_diff_eligible=1,
	ph_break_start="02:00:00",
	ph_break_hours=1,
)


class TestNightDiffAndOvertime(FrappeTestCase):
	def test_object_diagram_night_shift(self):
		nd, ot = compute("2026-11-03 21:52:00", "2026-11-04 07:05:00", "2026-11-03", NIGHT, 15)
		self.assertEqual(nd, 7.0)  # 22:00-02:00 + 03:00-06:00 (break excluded)
		self.assertEqual(ot, 0.0)  # 5 minutes rounds down

	def test_overtime_after_shift_end(self):
		_nd, ot = compute("2026-11-05 21:52:00", "2026-11-06 09:00:00", "2026-11-05", NIGHT, 15)
		self.assertEqual(ot, 2.0)

	def test_day_shift_has_no_night_diff(self):
		day = frappe._dict(start_time="08:00:00", end_time="17:00:00", ph_night_diff_eligible=0)
		nd, _ot = compute("2026-11-03 07:55:00", "2026-11-03 17:05:00", "2026-11-03", day, 15)
		self.assertEqual(nd, 0.0)


class TestStatutoryEngine(FrappeTestCase):
	def test_sss(self):
		c = engine.compute_monthly_contribution("SSS", 23700, DATE)
		self.assertEqual((c.employee_share, c.employer_share, c.ec_share), (1175.0, 2350.0, 30.0))
		self.assertEqual(engine.compute_monthly_contribution("SSS", 90000, DATE).employee_share, 1750.0)

	def test_philhealth_floor_and_cap(self):
		self.assertEqual(engine.compute_monthly_contribution("PhilHealth", 8000, DATE).employee_share, 250.0)
		self.assertEqual(engine.compute_monthly_contribution("PhilHealth", 150000, DATE).employee_share, 2500.0)

	def test_pagibig_cap(self):
		self.assertEqual(engine.compute_monthly_contribution("Pag-IBIG", 23700, DATE).employee_share, 200.0)

	def test_semi_monthly_schedules(self):
		monthly = engine.compute_monthly_contribution("SSS", 23700, DATE)
		self.assertEqual(engine.period_share(monthly, "Bimonthly", False, "Split Equally").employee_share, 587.5)
		self.assertEqual(engine.period_share(monthly, "Bimonthly", False, "Second Cutoff Only").employee_share, 0)
		self.assertEqual(engine.period_share(monthly, "Bimonthly", True, "Second Cutoff Only").employee_share, 1175.0)

	def test_bir_withholding(self):
		self.assertEqual(engine.compute_withholding_tax(10000, "Bimonthly", DATE)[0], 0.0)
		self.assertEqual(engine.compute_withholding_tax(11850, "Bimonthly", DATE)[0], 214.95)
		self.assertEqual(engine.compute_withholding_tax(20000, "Bimonthly", DATE)[0], 1604.1)


class TestGovernmentIdFormat(FrappeTestCase):
	def test_formatters(self):
		self.assertEqual(GOVERNMENT_IDS["sss_number"][2]("3412345671"), "34-1234567-1")
		self.assertEqual(GOVERNMENT_IDS["tin"][2]("123456789000"), "123-456-789-000")

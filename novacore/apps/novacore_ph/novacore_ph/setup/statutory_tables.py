"""Reference statutory rate tables (created once; HR maintains new versions in the UI).

SSS        Circular 2024-006 (effective Jan 2025): 15% of MSC, EE 5% / ER 10%,
           MSC 5,000 - 35,000 in 500 steps, EC 10 (MSC < 15,000) or 30.
PhilHealth Circular 2020-0005 as applied 2024-2025: 5% premium, EE 2.5%,
           income floor 10,000 and ceiling 100,000.
Pag-IBIG   Circular 460 (Feb 2024): EE 1% (<= 1,500) / 2%, ER 2%, max fund salary 10,000.
BIR        RR 11-2018 TRAIN withholding table effective Jan 2023 (semi-monthly).
"""

import frappe

EFFECTIVE = "2025-01-01"


def sss_brackets():
	rows = []
	for msc in range(5000, 35001, 500):
		rows.append(
			{
				"from_amount": 0 if msc == 5000 else msc - 250,
				"to_amount": 0 if msc == 35000 else msc + 249.99,
				"employee_amount": msc * 0.05,
				"employer_amount": msc * 0.10,
				"ec_amount": 10 if msc < 15000 else 30,
			}
		)
	return rows


TABLES = [
	{
		"agency": "SSS",
		"version": "SSS-2025",
		"notes": "SSS Circular 2024-006. MSC 5,000-35,000; EE 5%, ER 10%, EC 10/30.",
		"brackets": sss_brackets(),
	},
	{
		"agency": "PhilHealth",
		"version": "PHIC-2025",
		"notes": "5% premium shared equally. Floor 10,000; ceiling 100,000.",
		"brackets": [
			{
				"from_amount": 0,
				"to_amount": 0,
				"employee_rate": 2.5,
				"employer_rate": 2.5,
				"salary_floor": 10000,
				"salary_cap": 100000,
			}
		],
	},
	{
		"agency": "Pag-IBIG",
		"version": "HDMF-2024",
		"notes": "HDMF Circular 460. Max monthly fund salary 10,000 (EE/ER max 200).",
		"brackets": [
			{"from_amount": 0, "to_amount": 1500, "employee_rate": 1, "employer_rate": 2, "salary_cap": 10000},
			{"from_amount": 1500.01, "to_amount": 0, "employee_rate": 2, "employer_rate": 2, "salary_cap": 10000},
		],
	},
	{
		"agency": "BIR",
		"version": "TRAIN-2023-SEMIMONTHLY",
		"notes": "Semi-monthly withholding tax table (RR 11-2018, 2023 onwards). "
		"Tax = base tax + rate x (taxable - From Amount).",
		"brackets": [
			{"from_amount": 0, "to_amount": 10416.99, "base_tax": 0, "employee_rate": 0},
			{"from_amount": 10417, "to_amount": 16666.99, "base_tax": 0, "employee_rate": 15},
			{"from_amount": 16667, "to_amount": 33332.99, "base_tax": 937.50, "employee_rate": 20},
			{"from_amount": 33333, "to_amount": 83332.99, "base_tax": 4270.70, "employee_rate": 25},
			{"from_amount": 83333, "to_amount": 333332.99, "base_tax": 16770.70, "employee_rate": 30},
			{"from_amount": 333333, "to_amount": 0, "base_tax": 91770.70, "employee_rate": 35},
		],
	},
]


def create_statutory_tables():
	for table in TABLES:
		if frappe.db.exists("PH Contribution Table", {"agency": table["agency"]}):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "PH Contribution Table",
				"agency": table["agency"],
				"version": table["version"],
				"effective_from": EFFECTIVE,
				"enabled": 1,
				"notes": table["notes"],
				"brackets": table["brackets"],
			}
		)
		doc.insert(ignore_permissions=True)

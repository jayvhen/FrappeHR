"""Seeder: setup wizard + NovaCore demo data (mirrors Object Diagram 05).

    bench --site <site> execute novacore_ph.setup.demo.run

Idempotent - records are looked up before being created, so it is safe to re-run.
Demo users all share DEMO_PASSWORD; change them before any real use.
"""

from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, getdate

COMPANY = "NovaCore Business Solutions Inc."
ABBR = "NBSI"
DEMO_PASSWORD = "NovaCore@2026"
YEAR = 2026


def run():
	frappe.flags.in_demo_seed = True
	frappe.set_user("Administrator")
	run_setup_wizard()
	company = frappe.db.get_value("Company", {"company_name": COMPANY}, "name") or COMPANY
	seed(company)
	frappe.db.commit()
	print("NovaCore demo data ready.")


# ------------------------------------------------------------- setup wizard
def run_setup_wizard():
	if frappe.db.exists("Company", COMPANY) or frappe.is_setup_complete():
		return
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	setup_complete(
		{
			"language": "English",
			"country": "Philippines",
			"timezone": "Asia/Manila",
			"currency": "PHP",
			"full_name": "NovaCore Administrator",
			"email": "admin@novacore.local",
			"password": DEMO_PASSWORD,
			"company_name": COMPANY,
			"company_abbr": ABBR,
			"chart_of_accounts": "Standard",
			"fy_start_date": f"{YEAR}-01-01",
			"fy_end_date": f"{YEAR}-12-31",
			"setup_demo": 0,
			"enable_telemetry": 0,
		}
	)
	frappe.db.commit()
	frappe.clear_cache()


# ------------------------------------------------------------------ helpers
def get_or_create(doctype, filters, values=None, submit=False):
	name = frappe.db.get_value(doctype, filters, "name")
	if name:
		return frappe.get_doc(doctype, name)
	doc = frappe.get_doc({"doctype": doctype, **filters, **(values or {})})
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def account(company, account_name):
	return frappe.db.get_value("Account", {"company": company, "account_name": account_name}, "name")


def ensure_account(company, account_name, parent_name, account_type=None):
	existing = account(company, account_name)
	if existing:
		return existing
	parent = account(company, parent_name)
	doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent,
			"company": company,
			"account_type": account_type or "",
			"is_group": 0,
		}
	).insert(ignore_permissions=True)
	return doc.name


# --------------------------------------------------------------------- seed
def seed(company):
	holiday_list = create_holiday_list(company)
	create_accounts_and_components(company)
	departments = create_departments(company)
	create_designations()
	shifts = create_shift_types(holiday_list)
	leave_types = create_leave_types()
	employees = create_people(company, departments, shifts, holiday_list)
	create_salary_structure(company, employees)
	create_integration_user()
	create_biometric_devices()
	allocate_leaves(employees, leave_types)
	# order matters: manual attendance and approved leave must exist before auto-attendance
	# runs, otherwise HRMS marks those days Absent
	create_manual_attendance(employees)
	create_requests(employees)
	create_checkins_and_attendance(employees, shifts)
	create_recruitment(company)
	create_appraisal(company, employees)
	run_payrolls(company)


def create_holiday_list(company):
	name = f"PH Holidays {YEAR}"
	if not frappe.db.exists("Holiday List", name):
		doc = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": name,
				"from_date": f"{YEAR}-01-01",
				"to_date": f"{YEAR}-12-31",
				"holidays": [
					{"holiday_date": d, "description": desc}
					for d, desc in [
						(f"{YEAR}-01-01", "New Year's Day"),
						(f"{YEAR}-04-02", "Maundy Thursday"),
						(f"{YEAR}-04-03", "Good Friday"),
						(f"{YEAR}-04-09", "Araw ng Kagitingan"),
						(f"{YEAR}-05-01", "Labor Day"),
						(f"{YEAR}-06-12", "Independence Day"),
						(f"{YEAR}-08-31", "National Heroes Day"),
						(f"{YEAR}-11-30", "Bonifacio Day"),
						(f"{YEAR}-12-25", "Christmas Day"),
						(f"{YEAR}-12-30", "Rizal Day"),
					]
				],
			}
		)
		doc.weekly_off = "Saturday"
		doc.get_weekly_off_dates()
		doc.weekly_off = "Sunday"
		doc.get_weekly_off_dates()
		doc.insert(ignore_permissions=True)
	frappe.db.set_value("Company", company, "default_holiday_list", name)
	return name


def create_accounts_and_components(company):
	payable = {
		"SSS Contribution": ensure_account(company, "SSS Contributions Payable", "Duties and Taxes", "Payable"),
		"PhilHealth Contribution": ensure_account(company, "PhilHealth Contributions Payable", "Duties and Taxes",
												  "Payable"),
		"Pag-IBIG Contribution": ensure_account(company, "Pag-IBIG Contributions Payable", "Duties and Taxes",
												"Payable"),
		"Withholding Tax": ensure_account(company, "Withholding Tax on Compensation Payable", "Duties and Taxes",
										  "Tax"),
	}
	salary_expense = account(company, "Salary")

	for name, abbr, ctype, taxable, payment_days in [
		("Basic Salary", "BS", "Earning", 1, 1),
		("De Minimis Allowance", "DMA", "Earning", 0, 1),
	]:
		if not frappe.db.exists("Salary Component", name):
			frappe.get_doc(
				{
					"doctype": "Salary Component",
					"salary_component": name,
					"salary_component_abbr": abbr,
					"type": ctype,
					"is_tax_applicable": taxable,
					"depends_on_payment_days": payment_days,
				}
			).insert(ignore_permissions=True)

	for component in (
		"Basic Salary",
		"De Minimis Allowance",
		"Night Differential",
		"Overtime Pay",
		"Sales Incentive",  # created by novacore_integrations (ERP API)
		*payable.keys(),
	):
		if not frappe.db.exists("Salary Component", component):
			continue
		doc = frappe.get_doc("Salary Component", component)
		target = payable.get(component, salary_expense)
		if not any(a.company == company for a in doc.accounts):
			doc.append("accounts", {"company": company, "account": target})
			doc.save(ignore_permissions=True)

	frappe.db.set_value(
		"Company",
		company,
		"default_payroll_payable_account",
		ensure_account(company, "Payroll Payable", "Current Liabilities", "Payable"),
	)


def create_departments(company):
	result = {}
	for dept, site, manager in [
		("Operations – Telco Campaign", "Calapan City", "hr.manager@novacore.local"),
		("Human Resources", "Calapan City", "hr.manager@novacore.local"),
		("Finance", "Calapan City", "finance@novacore.local"),
		("Information Technology", "Calapan City", "hr.manager@novacore.local"),
	]:
		name = frappe.db.get_value("Department", {"department_name": dept, "company": company}, "name")
		if not name:
			doc = frappe.get_doc(
				{
					"doctype": "Department",
					"department_name": dept,
					"company": company,
					"parent_department": "All Departments",
					"site": site,
				}
			).insert(ignore_permissions=True)
			name = doc.name
		result[dept] = (name, manager)
	return result


def create_designations():
	for d in ("Customer Service Agent", "Team Leader", "HR Manager", "Payroll Officer", "Finance Manager",
			  "Customer Service Representative"):
		get_or_create("Designation", {"designation_name": d})


def create_shift_types(holiday_list):
	shifts = {}
	for name, start, end, nd, brk in [
		("Day Shift", "08:00:00", "17:00:00", 0, "12:00:00"),
		("Night Shift", "22:00:00", "07:00:00", 1, "02:00:00"),
	]:
		doc = get_or_create(
			"Shift Type",
			{"name": name},
			{
				"start_time": start,
				"end_time": end,
				"holiday_list": holiday_list,
				"enable_auto_attendance": 1,
				"process_attendance_after": f"{YEAR}-10-16",
				"determine_check_in_and_check_out": "Alternating entries as IN and OUT during the same shift",
				"working_hours_calculation_based_on": "First Check-in and Last Check-out",
				"begin_check_in_before_shift_start_time": 60,
				"allow_check_out_after_shift_end_time": 240,
				"late_entry_grace_period": 10,
				"enable_late_entry_marking": 1,
				"ph_night_diff_eligible": nd,
				"ph_break_start": brk,
				"ph_break_hours": 1,
			},
		)
		shifts[name] = doc.name
	return shifts


# annual days granted in the demo (HRMS may pre-create some types with a 0 limit)
LEAVE_DAYS = {"Vacation Leave": 15, "Sick Leave": 15, "Service Incentive Leave": 5}


def create_leave_types():
	for name, days in LEAVE_DAYS.items():
		doc = get_or_create("Leave Type", {"leave_type_name": name}, {"max_leaves_allowed": days})
		if (doc.max_leaves_allowed or 0) < days:
			frappe.db.set_value("Leave Type", doc.name, "max_leaves_allowed", days)
	return list(LEAVE_DAYS)


PEOPLE = [
	# key, first, last, gender, dob, email, roles, dept, designation, shift, base, device id, ids, mwe
	("hr", "Maria", "Santos", "Female", "1985-04-12", "hr.manager@novacore.local",
	 ["HR Manager", "HR User", "Employee"], "Human Resources", "HR Manager", "Day Shift", 45000, "1001",
	 ("34-1234567-1", "12-345678901-1", "1234-5678-9001", "123-456-789-000"), 0),
	("payroll", "Paolo", "Cruz", "Male", "1990-08-03", "payroll@novacore.local",
	 ["Payroll Officer", "Employee"], "Finance", "Payroll Officer", "Day Shift", 30000, "1002",
	 ("34-1234567-2", "12-345678902-2", "1234-5678-9002", "123-456-789-001"), 0),
	("finance", "Liza", "Mendoza", "Female", "1983-01-22", "finance@novacore.local",
	 ["HR Finance Manager", "Accounts User", "Employee"], "Finance", "Finance Manager", "Day Shift", 50000, "1003",
	 ("34-1234567-3", "12-345678903-3", "1234-5678-9003", "123-456-789-002"), 0),
	("tl", "Carlo", "Bautista", "Male", "1992-11-30", "teamlead@novacore.local",
	 ["Team Leader", "Employee"], "Operations – Telco Campaign", "Team Leader", "Night Shift", 35000, "1004",
	 ("34-1234567-4", "12-345678904-4", "1234-5678-9004", "123-456-789-003"), 0),
	("juan", "Juan", "Reyes", "Male", "1998-06-15", "juan.reyes@novacore.local",
	 ["Employee"], "Operations – Telco Campaign", "Customer Service Agent", "Night Shift", 23700, "1025",
	 ("34-1234567-5", "12-345678905-5", "1234-5678-9005", "123-456-789-004"), 0),
	("ana", "Ana", "Villanueva", "Female", "1999-02-09", "ana.villanueva@novacore.local",
	 ["Employee"], "Operations – Telco Campaign", "Customer Service Agent", "Day Shift", 20000, "1026",
	 ("34-1234567-6", "12-345678906-6", "1234-5678-9006", "123-456-789-005"), 0),
	("rico", "Rico", "Garcia", "Male", "2000-09-19", "rico.garcia@novacore.local",
	 ["Employee"], "Operations – Telco Campaign", "Customer Service Agent", "Day Shift", 10500, "1027",
	 ("34-1234567-7", "12-345678907-7", "", ""), 1),
]


def create_people(company, departments, shifts, holiday_list):
	employees = {}
	for (key, first, last, gender, dob, email, roles, dept, designation, shift, base, device, ids, mwe) in PEOPLE:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": first,
					"last_name": last,
					"send_welcome_email": 0,
					"new_password": DEMO_PASSWORD,
					"user_type": "System User",
					"roles": [{"role": r} for r in roles],
				}
			).insert(ignore_permissions=True)
		employees[key] = {"email": email, "base": base, "shift": shifts[shift], "name": None}

	# departments managers are users, set once those exist
	for dept, (dept_name, manager) in departments.items():
		frappe.db.set_value("Department", dept_name, "department_manager", manager)

	for (key, first, last, gender, dob, email, roles, dept, designation, shift, base, device, ids, mwe) in PEOPLE:
		name = frappe.db.get_value("Employee", {"user_id": email}, "name")
		if not name:
			doj = "2026-03-02" if key in ("juan", "rico") else "2024-01-08"
			doc = frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": first,
					"last_name": last,
					"gender": gender,
					"date_of_birth": dob,
					"date_of_joining": doj,
					"company": company,
					"status": "Active",
					"user_id": email,
					"department": departments[dept][0],
					"designation": designation,
					"default_shift": shifts[shift],
					"holiday_list": holiday_list,
					"attendance_device_id": device,
					"salary_mode": "Bank",
					"bank_name": "Land Bank of the Philippines",
					"bank_ac_no": f"0012-3456-{device}",
					"cell_number": f"+63917555{device}",
					"sss_number": ids[0],
					"philhealth_number": ids[1],
					"pagibig_number": ids[2],
					"tin": ids[3],
					"is_minimum_wage_earner": mwe,
					"employment_stage": "Probationary" if key in ("juan", "rico") else "Regular",
				}
			)
			doc.insert(ignore_permissions=True)
			name = doc.name
		employees[key]["name"] = name

	tl = employees["tl"]
	for key in ("juan", "ana", "rico"):
		frappe.db.set_value(
			"Employee",
			employees[key]["name"],
			{"reports_to": tl["name"], "leave_approver": tl["email"]},
		)
	for key in ("hr", "payroll", "finance", "tl"):
		frappe.db.set_value("Employee", employees[key]["name"], "leave_approver", "hr.manager@novacore.local")

	ops = departments["Operations – Telco Campaign"][0]
	dept = frappe.get_doc("Department", ops)
	if not any(a.approver == tl["email"] for a in dept.get("leave_approvers", [])):
		dept.append("leave_approvers", {"approver": tl["email"]})
		dept.save(ignore_permissions=True)
	return employees


def create_salary_structure(company, employees):
	name = "NovaCore Semi-monthly"
	if not frappe.db.exists("Salary Structure", name):
		doc = frappe.get_doc(
			{
				"doctype": "Salary Structure",
				"name": name,
				"company": company,
				"currency": "PHP",
				"payroll_frequency": "Bimonthly",
				"is_active": "Yes",
				"earnings": [
					{
						"salary_component": "Basic Salary",
						"abbr": "BS",
						"amount_based_on_formula": 1,
						"formula": "base / 2",
						"depends_on_payment_days": 1,
					},
					{
						"salary_component": "De Minimis Allowance",
						"abbr": "DMA",
						"amount_based_on_formula": 1,
						"condition": "base > 15000",
						"formula": "1000",
						"depends_on_payment_days": 1,
					},
				],
			}
		)
		doc.insert(ignore_permissions=True)
		doc.submit()

	for emp in employees.values():
		if frappe.db.exists("Salary Structure Assignment", {"employee": emp["name"], "docstatus": 1}):
			continue
		doj = frappe.db.get_value("Employee", emp["name"], "date_of_joining")
		frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": emp["name"],
				"salary_structure": name,
				"company": company,
				"currency": "PHP",
				"from_date": max(getdate(doj), getdate(f"{YEAR}-01-01")),
				"base": emp["base"],
				"payroll_payable_account": account(company, "Payroll Payable"),
			}
		).insert(ignore_permissions=True).submit()


def create_integration_user():
	"""API-only user for the other ERP modules. Generate its API key/secret in
	User > Settings > API Access and hand those to the integrating team."""
	email = "erp.integration@novacore.local"
	if frappe.db.exists("User", email) or not frappe.db.exists("Role", "ERP Integration"):
		return
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "ERP Integration",
			"send_welcome_email": 0,
			"user_type": "System User",
			"roles": [{"role": "ERP Integration"}, {"role": "ERP Finance Integration"}],
		}
	).insert(ignore_permissions=True)


def create_biometric_devices():
	if not frappe.db.exists("DocType", "Biometric Device"):
		return
	for device_id, location in [("BIO-CAL-01", "Calapan HQ - Lobby"), ("BIO-CAL-02", "Calapan HQ - 2F"),
								("BIO-CAL-03", "Calapan HQ - Operations Floor")]:
		get_or_create("Biometric Device", {"device_id": device_id}, {"location": location, "enabled": 1})


def allocate_leaves(employees, leave_types):
	for emp in employees.values():
		for leave_type in leave_types:
			if frappe.db.exists(
				"Leave Allocation", {"employee": emp["name"], "leave_type": leave_type, "docstatus": 1}
			):
				continue
			doj = frappe.db.get_value("Employee", emp["name"], "date_of_joining")
			frappe.get_doc(
				{
					"doctype": "Leave Allocation",
					"employee": emp["name"],
					"leave_type": leave_type,
					"from_date": max(getdate(doj), getdate(f"{YEAR}-01-01")),
					"to_date": f"{YEAR}-12-31",
					"new_leaves_allocated": LEAVE_DAYS[leave_type],
				}
			).insert(ignore_permissions=True).submit()


def working_days(start, end, skip=()):
	day = getdate(start)
	while day <= getdate(end):
		if day.weekday() < 5 and str(day) not in skip:
			yield day
		day = add_days(day, 1)


def add_checkin(employee, time, log_type, device):
	if frappe.db.exists("Employee Checkin", {"employee": employee, "time": time}):
		return
	frappe.get_doc(
		{"doctype": "Employee Checkin", "employee": employee, "time": time, "log_type": log_type,
		 "device_id": device}
	).insert(ignore_permissions=True)


def create_checkins_and_attendance(employees, shifts):
	"""Biometric logs Oct 16 - Nov 13 processed by HRMS auto-attendance (Timing Diagram 16)."""
	start, end = f"{YEAR}-10-16", f"{YEAR}-11-13"
	juan, ana = employees["juan"]["name"], employees["ana"]["name"]
	for day in working_days(start, end, skip={f"{YEAR}-11-10"}):
		# Juan, night shift: object diagram values on Nov 3; 2h overtime on Nov 5
		in_t = datetime.combine(day, datetime.strptime("21:52", "%H:%M").time())
		out_t = in_t + timedelta(hours=9, minutes=13)
		if str(day) == f"{YEAR}-11-05":
			out_t = datetime.combine(add_days(day, 1), datetime.strptime("09:00", "%H:%M").time())
		add_checkin(juan, in_t, "IN", "BIO-CAL-03")
		add_checkin(juan, out_t, "OUT", "BIO-CAL-03")

		ana_in = datetime.combine(day, datetime.strptime("07:55", "%H:%M").time())
		add_checkin(ana, ana_in, "IN", "BIO-CAL-01")
		add_checkin(ana, ana_in + timedelta(hours=9, minutes=10), "OUT", "BIO-CAL-01")

	for shift in shifts.values():
		doc = frappe.get_doc("Shift Type", shift)
		doc.last_sync_of_checkin = f"{YEAR}-11-15 12:00:00"
		doc.save(ignore_permissions=True)
		doc.process_auto_attendance()


def create_manual_attendance(employees):
	"""Employees without biometric logs in the demo are marked present for the payroll periods."""
	for key in ("hr", "payroll", "finance", "tl", "rico"):
		emp = employees[key]["name"]
		for day in working_days(f"{YEAR}-10-16", f"{YEAR}-11-13"):
			if not frappe.db.exists("Attendance", {"employee": emp, "attendance_date": day, "docstatus": ("<", 2)}):
				frappe.get_doc(
					{"doctype": "Attendance", "employee": emp, "attendance_date": day, "status": "Present",
					 "shift": employees[key]["shift"]}
				).insert(ignore_permissions=True).submit()


def create_requests(employees):
	juan = employees["juan"]
	tl_email = employees["tl"]["email"]

	if not frappe.db.exists("Leave Application", {"employee": juan["name"], "from_date": f"{YEAR}-11-10"}):
		leave = frappe.get_doc(
			{
				"doctype": "Leave Application",
				"employee": juan["name"],
				"leave_type": "Vacation Leave",
				"from_date": f"{YEAR}-11-10",
				"to_date": f"{YEAR}-11-10",
				"description": "Family event",
				"leave_approver": tl_email,
				"status": "Approved",
				"posting_date": f"{YEAR}-11-03",
			}
		)
		leave.insert(ignore_permissions=True)
		leave.submit()

	if not frappe.db.exists("Overtime Request", {"employee": juan["name"], "date": f"{YEAR}-11-05"}):
		ot = frappe.get_doc(
			{
				"doctype": "Overtime Request",
				"employee": juan["name"],
				"date": f"{YEAR}-11-05",
				"hours": 2,
				"reason": "Campaign volume spike - stayed for queue backlog",
				"approver": tl_email,
				"status": "Approved",
			}
		)
		ot.insert(ignore_permissions=True)
		ot.submit()

	# a pending request that the hourly escalation job will pick up
	if not frappe.db.exists("Overtime Request", {"employee": employees["ana"]["name"], "date": f"{YEAR}-11-13"}):
		frappe.get_doc(
			{
				"doctype": "Overtime Request",
				"employee": employees["ana"]["name"],
				"date": f"{YEAR}-11-13",
				"hours": 1.5,
				"reason": "System outage recovery",
				"approver": tl_email,
			}
		).insert(ignore_permissions=True)

	get_or_create(
		"HR Helpdesk Ticket",
		{"subject": "Request for Certificate of Employment", "employee": juan["name"]},
		{
			"category": "Documents & Certificates",
			"priority": "Medium",
			"description": "Requesting a COE for a bank loan application.",
		},
	)


def create_recruitment(company):
	opening = frappe.db.get_value("Job Opening", {"job_title": "Customer Service Representative"}, "name")
	if not opening:
		opening = (
			frappe.get_doc(
				{
					"doctype": "Job Opening",
					"job_title": "Customer Service Representative",
					"designation": "Customer Service Representative",
					"company": company,
					"status": "Open",
					"planned_vacancies": 10,
					"description": "Telco campaign voice support, night shift, Calapan City.",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	get_or_create(
		"Job Applicant",
		{"email_id": "bea.castillo@example.com"},
		{
			"applicant_name": "Bea Castillo",
			"job_title": opening,
			"status": "Open",
			"assessment_score": 85,
			"assessment_status": "Passed",
		},
	)


def create_appraisal(company, employees):
	"""Q4 2026 appraisal cycle (draft) - optional; skipped with a log entry if HRMS rejects the setup."""
	try:
		kra = get_or_create("KRA", {"title": "Call Quality & Productivity"})
		criteria = get_or_create("Employee Feedback Criteria", {"criteria": "Customer Focus"})
		template = get_or_create(
			"Appraisal Template",
			{"template_title": "Customer Service Agent"},
			{
				"goals": [{"key_result_area": kra.name, "per_weightage": 100}],
				"rating_criteria": [{"criteria": criteria.name, "per_weightage": 100}],
			},
		)
		cycle = get_or_create(
			"Appraisal Cycle",
			{"cycle_name": f"Q4 {YEAR}"},
			{
				"company": company,
				"start_date": f"{YEAR}-10-01",
				"end_date": f"{YEAR}-12-31",
				"kra_evaluation_method": "Manual Rating",
			},
		)
		juan = employees["juan"]["name"]
		if not frappe.db.exists("Appraisal", {"employee": juan, "appraisal_cycle": cycle.name}):
			appraisal = frappe.get_doc(
				{
					"doctype": "Appraisal",
					"employee": juan,
					"appraisal_cycle": cycle.name,
					"appraisal_template": template.name,
				}
			)
			appraisal.insert(ignore_permissions=True)
			frappe.db.set_value("Appraisal", appraisal.name, "kpi_score", 92.4)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="NovaCore demo: appraisal seed skipped")
		print("Appraisal demo data skipped (see Error Log).")


def make_payroll_entry(company, start, end):
	existing = frappe.db.get_value(
		"Payroll Entry", {"company": company, "start_date": start, "end_date": end, "docstatus": 1}, "name"
	)
	if existing:
		return frappe.get_doc("Payroll Entry", existing)
	entry = frappe.get_doc(
		{
			"doctype": "Payroll Entry",
			"company": company,
			"posting_date": end,
			"payroll_frequency": "Bimonthly",
			"start_date": start,
			"end_date": end,
			"currency": "PHP",
			"exchange_rate": 1,
			"payroll_payable_account": account(company, "Payroll Payable"),
			"cost_center": frappe.db.get_value("Company", company, "cost_center"),
			"payment_account": account(company, "Cash"),
		}
	)
	entry.insert(ignore_permissions=True)
	entry.fill_employee_details()
	entry.save(ignore_permissions=True)
	entry.submit()  # creates draft salary slips
	return entry


def run_payrolls(company):
	"""Oct 16-31: full approval cycle (released). Nov 1-15: draft slips awaiting the Payroll Officer."""
	from novacore_ph.payroll.payroll_entry import release_payroll

	october = make_payroll_entry(company, f"{YEAR}-10-16", f"{YEAR}-10-31")
	if not october.salary_slips_submitted:
		october.db_set(
			{
				"approval_status": "Approved",
				"approval_requested_by": "payroll@novacore.local",
				"approved_by": "finance@novacore.local",
				"approved_on": f"{YEAR}-11-03 10:00:00",
			}
		)
		release_payroll(october.name)
		frappe.set_user("Administrator")

	make_payroll_entry(company, f"{YEAR}-11-01", f"{YEAR}-11-15")

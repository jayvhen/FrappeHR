"""Employee lifecycle (State Machine Diagram 13) and government ID validation.

Applicant -> Offered -> Onboarding are tracked on Job Applicant / Job Offer /
Employee Onboarding (HRMS). Once an Employee exists, `employment_stage` follows:

  Probationary --appraisal passed [score >= min]--> Regular
  Regular <--> On Leave            (approved leave covering today)
  Regular <--> Suspended           (disciplinary action / suspension served)
  Probationary | Regular --resignation filed / not regularized--> Notice Period
  Notice Period --clearance complete (relieving date passed)--> Separated (status Left)
"""

import re

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, getdate, today

ALLOWED_TRANSITIONS = {
	"Probationary": {"Regular", "On Leave", "Suspended", "Notice Period", "Separated"},
	"Regular": {"On Leave", "Suspended", "Notice Period", "Separated"},
	"On Leave": {"Probationary", "Regular", "Notice Period", "Separated"},
	"Suspended": {"Probationary", "Regular", "Notice Period", "Separated"},
	"Notice Period": {"Probationary", "Regular", "Separated"},
	"Separated": {"Probationary"},  # rehire
}

# fieldname: (label, allowed digit counts, formatter)
GOVERNMENT_IDS = {
	"sss_number": ("SSS Number", (10,), lambda d: f"{d[:2]}-{d[2:9]}-{d[9:]}"),
	"philhealth_number": ("PhilHealth Number", (12,), lambda d: f"{d[:2]}-{d[2:11]}-{d[11:]}"),
	"pagibig_number": ("Pag-IBIG MID Number", (12,), lambda d: f"{d[:4]}-{d[4:8]}-{d[8:]}"),
	"tin": (
		"TIN",
		(9, 12, 13, 14),
		lambda d: "-".join([d[:3], d[3:6], d[6:9]] + ([d[9:]] if len(d) > 9 else [])),
	),
}


def get_settings():
	return frappe.get_cached_doc("PH Statutory Settings")


# ------------------------------------------------- staff record visibility
# ERPNext restricts every employee-linked user to their own Employee record (a User
# Permission). HR and payroll staff must see everyone (a Payroll Entry lists all
# employees), so they are exempt. Regular employees and Team Leaders stay restricted.
STAFF_ROLES = {"HR Manager", "HR User", "Payroll Officer", "HR Finance Manager"}


def is_staff_user(user: str | None) -> bool:
	return bool(user) and bool(STAFF_ROLES & set(frappe.get_roles(user)))


def remove_self_restriction(user: str):
	if frappe.db.exists("User Permission", {"user": user, "allow": "Employee"}):
		frappe.db.delete("User Permission", {"user": user, "allow": "Employee"})
		frappe.clear_cache(user=user)


def exempt_staff_on_employee_update(doc, method=None):
	if is_staff_user(doc.user_id):
		remove_self_restriction(doc.user_id)


def exempt_staff_on_user_update(doc, method=None):
	if is_staff_user(doc.name):
		remove_self_restriction(doc.name)


def exempt_all_staff_from_self_restriction():
	users = frappe.get_all(
		"Has Role", filters={"role": ("in", list(STAFF_ROLES)), "parenttype": "User"}, pluck="parent", distinct=True
	)
	for user in users:
		remove_self_restriction(user)


# ---------------------------------------------------------------- validation
def validate_employee(doc, method=None):
	validate_government_ids(doc)
	set_lifecycle_defaults(doc)
	validate_stage_transition(doc)
	if is_staff_user(doc.user_id):
		doc.create_user_permission = 0


def validate_government_ids(doc):
	for fieldname, (label, lengths, fmt) in GOVERNMENT_IDS.items():
		raw = (doc.get(fieldname) or "").strip()
		if not raw:
			continue
		digits = re.sub(r"[\s-]", "", raw)
		if not digits.isdigit() or len(digits) not in lengths:
			frappe.throw(
				_("{0} must contain {1} digits").format(label, _(" or ").join(str(n) for n in lengths)),
				title=_("Invalid Government ID"),
			)
		formatted = fmt(digits)
		doc.set(fieldname, formatted)
		duplicate = frappe.db.get_value(
			"Employee", {fieldname: formatted, "name": ("!=", doc.name or "")}, "employee_name"
		)
		if duplicate:
			frappe.throw(_("{0} {1} is already used by {2}").format(label, formatted, duplicate))


def set_lifecycle_defaults(doc):
	if not doc.employment_stage:
		doc.employment_stage = "Probationary"
	if doc.date_of_joining and not doc.probation_end_date:
		months = cint(get_settings().probation_months) or 6
		doc.probation_end_date = add_months(getdate(doc.date_of_joining), months)
	if doc.status == "Left":
		doc.employment_stage = "Separated"
	if doc.employment_stage == "Regular" and not doc.regularization_date:
		doc.regularization_date = getdate(today())


def validate_stage_transition(doc):
	if doc.is_new() or frappe.flags.ph_lifecycle_system:
		return
	previous = doc.get_doc_before_save()
	if not previous or previous.employment_stage == doc.employment_stage or not previous.employment_stage:
		return
	allowed = ALLOWED_TRANSITIONS.get(previous.employment_stage, set())
	if doc.employment_stage not in allowed:
		frappe.throw(
			_("Employment stage cannot change from {0} to {1}").format(
				frappe.bold(previous.employment_stage), frappe.bold(doc.employment_stage)
			),
			title=_("Invalid Lifecycle Transition"),
		)
	if doc.employment_stage == "Separated" and doc.status != "Left":
		frappe.throw(_("Set the employee status to Left (with a relieving date) to separate the employee"))


# ------------------------------------------------------------ transitions
def set_stage(employee: str, stage: str, reason: str):
	current = frappe.db.get_value("Employee", employee, "employment_stage")
	if current == stage:
		return
	values = {"employment_stage": stage}
	if stage == "On Leave":
		values["stage_before_leave"] = current
	if stage == "Regular" and not frappe.db.get_value("Employee", employee, "regularization_date"):
		values["regularization_date"] = getdate(today())
	frappe.db.set_value("Employee", employee, values)
	frappe.get_doc("Employee", employee).add_comment(
		"Info", _("Employment stage changed from {0} to {1}: {2}").format(current, stage, reason)
	)


def regularize_on_appraisal(doc, method=None):
	"""Probationary --appraisal passed [rating >= min]--> Regular"""
	stage = frappe.db.get_value("Employee", doc.employee, "employment_stage")
	if stage != "Probationary":
		return
	minimum = flt(get_settings().regularization_min_rating) or 3
	if flt(doc.final_score) >= minimum:
		set_stage(doc.employee, "Regular", _("Appraisal {0} passed with score {1}").format(doc.name, doc.final_score))


def sync_leave_stage(doc, method=None):
	if getdate(doc.from_date) <= getdate(today()) <= getdate(doc.to_date):
		sync_employee_leave_stage(doc.employee)


def sync_employee_leave_stage(employee: str):
	stage, before = frappe.db.get_value("Employee", employee, ["employment_stage", "stage_before_leave"])
	on_leave_today = frappe.db.exists(
		"Leave Application",
		{
			"employee": employee,
			"docstatus": 1,
			"status": "Approved",
			"from_date": ("<=", today()),
			"to_date": (">=", today()),
		},
	)
	if on_leave_today and stage in ("Probationary", "Regular"):
		set_stage(employee, "On Leave", _("Approved leave {0}").format(on_leave_today))
	elif not on_leave_today and stage == "On Leave":
		set_stage(employee, before or "Regular", _("Leave ended"))


def start_notice_period(doc, method=None):
	"""Employee Separation created (resignation filed) -> Notice Period."""
	if doc.employee:
		set_stage(doc.employee, "Notice Period", _("Separation {0} started").format(doc.name))


def daily_lifecycle_sync():
	frappe.db.commit()  # isolate from any earlier work in this job
	for employee in frappe.get_all(
		"Employee", filters={"status": "Active", "employment_stage": ("in", ["Probationary", "Regular", "On Leave"])},
		pluck="name",
	):
		sync_employee_leave_stage(employee)
	frappe.db.commit()

	separate_relieved_employees()
	flag_unregularized_probationers()
	frappe.db.commit()


def separate_relieved_employees():
	"""Notice Period --clearance complete--> Separated. Saved through the ORM so
	integrations (e.g. AD account disabling) run on status change."""
	for name in frappe.get_all(
		"Employee",
		# "is set" is required: Frappe treats NULL dates as 0001-01-01 in "<" filters
		filters=[["status", "=", "Active"], ["relieving_date", "is", "set"], ["relieving_date", "<", today()]],
		pluck="name",
	):
		try:
			doc = frappe.get_doc("Employee", name)
			doc.status = "Left"
			doc.flags.ignore_permissions = True
			frappe.flags.ph_lifecycle_system = True
			doc.save()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Could not separate employee {name}")
		finally:
			frappe.flags.ph_lifecycle_system = False


def flag_unregularized_probationers():
	"""Probation ended without a passing appraisal -> HR decides (ToDo), never automatic."""
	from novacore_ph.utils import assign_to
	from novacore_ph.workflow.escalation import get_hr_managers

	overdue = frappe.get_all(
		"Employee",
		filters=[
			["status", "=", "Active"],
			["employment_stage", "=", "Probationary"],
			["probation_end_date", "is", "set"],
			["probation_end_date", "<", today()],
		],
		fields=["name", "employee_name", "probation_end_date"],
	)
	hr = get_hr_managers()
	for emp in overdue:
		if not hr or frappe.db.exists(
			"ToDo", {"reference_type": "Employee", "reference_name": emp.name, "status": "Open"}
		):
			continue
		assign_to(
			"Employee",
			emp.name,
			hr,
			_(
				"Probation of {0} ended on {1} without a passing appraisal. Regularize or start the notice period."
			).format(emp.employee_name, frappe.format(emp.probation_end_date, "Date")),
			priority="High",
		)

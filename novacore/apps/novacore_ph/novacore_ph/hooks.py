app_name = "novacore_ph"
app_title = "NovaCore PH"
app_publisher = "NovaCore Business Solutions Inc."
app_description = "Philippine payroll, statutory compliance and HR workflows for Frappe HR"
app_email = "hr@novacore.local"
app_license = "MIT"
required_apps = ["erpnext", "hrms"]

# Install / migrate: custom fields, roles, salary components and statutory tables
# are (re)applied idempotently on every migrate.
before_install = "novacore_ph.setup.install.before_install"
after_install = "novacore_ph.setup.install.after_install"
after_migrate = "novacore_ph.setup.install.after_migrate"

override_doctype_class = {
	"Payroll Entry": "novacore_ph.payroll.payroll_entry.NovaCorePayrollEntry",
}

doctype_js = {
	"Payroll Entry": "public/js/payroll_entry.js",
	"Employee": "public/js/employee.js",
}

doc_events = {
	"Salary Slip": {
		"validate": "novacore_ph.payroll.salary_slip.apply_ph_payroll",
	},
	"Attendance": {
		"validate": "novacore_ph.attendance.attendance.compute_night_diff_and_overtime",
	},
	"Employee": {
		"validate": "novacore_ph.lifecycle.employee.validate_employee",
		"on_update": "novacore_ph.lifecycle.employee.exempt_staff_on_employee_update",
	},
	"User": {
		"on_update": "novacore_ph.lifecycle.employee.exempt_staff_on_user_update",
	},
	"Appraisal": {
		"on_submit": "novacore_ph.lifecycle.employee.regularize_on_appraisal",
	},
	"Leave Application": {
		"on_submit": "novacore_ph.lifecycle.employee.sync_leave_stage",
		"on_cancel": "novacore_ph.lifecycle.employee.sync_leave_stage",
	},
	"Employee Separation": {
		"after_insert": "novacore_ph.lifecycle.employee.start_notice_period",
	},
}

scheduler_events = {
	"hourly": [
		"novacore_ph.workflow.escalation.escalate_pending_requests",
	],
	"daily": [
		"novacore_ph.lifecycle.employee.daily_lifecycle_sync",
	],
}

# Fired by novacore_ph after HR/Finance approves a payroll run and slips are submitted.
# Other apps (novacore_integrations) register handlers: fn(payroll_entry: Document)
novacore_payroll_approved = []

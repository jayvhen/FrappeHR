app_name = "novacore_integrations"
app_title = "NovaCore Integrations"
app_publisher = "NovaCore Business Solutions Inc."
app_description = "Connectors for biometric devices, bank, KPI system, Active Directory, job boards and e-signature"
app_email = "it@novacore.local"
app_license = "MIT"
required_apps = ["hrms", "novacore_ph"]

before_install = "novacore_integrations.setup.install.before_install"
after_install = "novacore_integrations.setup.install.after_migrate"
after_migrate = "novacore_integrations.setup.install.after_migrate"

doctype_js = {
	"Job Offer": "public/js/job_offer.js",
	"Appraisal Cycle": "public/js/appraisal_cycle.js",
	"Payroll Entry": "public/js/payroll_entry.js",
}

doc_events = {
	"Employee": {
		"on_update": [
			"novacore_integrations.connectors.provisioning.on_employee_update",
			"novacore_integrations.erp.events.on_employee_update",
		],
	},
	"Employee Onboarding": {
		"on_update": "novacore_integrations.connectors.provisioning.on_onboarding_update",
	},
	"Job Opening": {
		"on_update": "novacore_integrations.connectors.job_boards.on_job_opening_update",
	},
}

scheduler_events = {
	"cron": {
		"*/5 * * * *": ["novacore_integrations.connectors.biometric.check_device_health"],
	},
}

# Registered with novacore_ph's payroll release (see novacore_ph.payroll.payroll_entry.release_payroll)
novacore_payroll_approved = [
	"novacore_integrations.connectors.bank.disburse_payroll",
	"novacore_integrations.connectors.notifications.send_payslip_notices",
	"novacore_integrations.erp.events.on_payroll_released",
]

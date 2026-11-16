"""Install / migrate routines for novacore_ph. Everything here is idempotent and runs
on every `bench migrate`, so it doubles as the app's schema + reference-data migration."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.permissions import add_permission, update_permission_property

from novacore_ph.setup.custom_fields import get_custom_fields

ROLES = {
	"Team Leader": 1,
	"Payroll Officer": 1,
	"HR Finance Manager": 1,
}

# doctype -> {role: [ptypes]} (permlevel 0 unless key is (role, permlevel))
ROLE_PERMISSIONS = {
	"Payroll Entry": {
		"Payroll Officer": ["read", "write", "create", "submit", "cancel", "report", "print"],
		"HR Finance Manager": ["read", "report", "print"],
	},
	"Salary Slip": {
		"Payroll Officer": ["read", "write", "create", "delete", "report", "print", "email"],
		"HR Finance Manager": ["read", "report", "print"],
	},
	"Salary Structure": {"Payroll Officer": ["read", "report"]},
	"Salary Structure Assignment": {
		"Payroll Officer": ["read", "write", "create", "submit", "report"],
	},
	"Additional Salary": {"Payroll Officer": ["read", "write", "create", "submit", "report"]},
	"Salary Component": {"Payroll Officer": ["read"], "HR Finance Manager": ["read"]},
	"Payroll Period": {"Payroll Officer": ["read"]},
	"Payroll Settings": {"Payroll Officer": ["read"]},
	"Employee": {
		"Payroll Officer": ["read", "report"],
		"HR Finance Manager": ["read", "report"],
		"Team Leader": ["read"],
		("Payroll Officer", 1): ["read"],
		("HR Finance Manager", 1): ["read"],
		("HR Manager", 1): ["read", "write"],
		("HR User", 1): ["read", "write"],
		# NOTE: no ("Employee", 1) grant. Field levels are per role, not per record, so it would
		# expose every readable colleague's government IDs (e.g. to Team Leaders) - RA 10173.
	},
	"Attendance": {"Payroll Officer": ["read", "report"], "Team Leader": ["read", "report"]},
	"Employee Checkin": {"Team Leader": ["read", "report"]},
	"Leave Application": {"Team Leader": ["read", "write", "submit", "report"]},
	"Appraisal": {"Team Leader": ["read", "write", "report"]},
	"PH Contribution Table": {},
}

SALARY_COMPONENTS = [
	# name, abbr, type, taxable
	("Night Differential", "ND", "Earning", 1),
	("Overtime Pay", "OTP", "Earning", 1),
	("SSS Contribution", "SSS", "Deduction", 0),
	("PhilHealth Contribution", "PHIC", "Deduction", 0),
	("Pag-IBIG Contribution", "HDMF", "Deduction", 0),
	("Withholding Tax", "WTAX", "Deduction", 0),
]

SETTINGS_COMPONENTS = {
	"night_diff_component": "Night Differential",
	"overtime_component": "Overtime Pay",
	"sss_component": "SSS Contribution",
	"philhealth_component": "PhilHealth Contribution",
	"pagibig_component": "Pag-IBIG Contribution",
	"withholding_tax_component": "Withholding Tax",
}


def before_install():
	create_roles()


def after_install():
	after_migrate()


def after_migrate():
	create_roles()
	create_custom_fields(get_custom_fields(), ignore_validate=True)
	setup_permissions()
	revoke_permissions()
	from novacore_ph.lifecycle.employee import exempt_all_staff_from_self_restriction

	exempt_all_staff_from_self_restriction()
	create_salary_components()
	configure_settings()
	from novacore_ph.setup.statutory_tables import create_statutory_tables

	create_statutory_tables()
	frappe.db.commit()


def create_roles():
	for role, desk_access in ROLES.items():
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": desk_access}).insert(
				ignore_permissions=True
			)


# (doctype, role, permlevel) grants removed in later versions - deleted on migrate
REVOKED_PERMISSIONS = [("Employee", "Employee", 1)]


def revoke_permissions():
	for doctype, role, permlevel in REVOKED_PERMISSIONS:
		frappe.db.delete("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": permlevel})
	frappe.clear_cache()


def setup_permissions():
	for doctype, grants in ROLE_PERMISSIONS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for key, ptypes in grants.items():
			role, permlevel = key if isinstance(key, tuple) else (key, 0)
			if not frappe.db.exists("Role", role):
				continue
			if not frappe.db.exists(
				"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": permlevel, "if_owner": 0}
			):
				add_permission(doctype, role, permlevel)
			for ptype in ptypes:
				update_permission_property(doctype, role, permlevel, ptype, 1, validate=False)


def create_salary_components():
	for name, abbr, component_type, taxable in SALARY_COMPONENTS:
		if frappe.db.exists("Salary Component", name):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": name,
				"salary_component_abbr": abbr,
				"type": component_type,
				"depends_on_payment_days": 0,
				"is_tax_applicable": taxable if component_type == "Earning" else 0,
				"description": "Managed by NovaCore PH Statutory Engine",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)


def configure_settings():
	settings = frappe.get_single("PH Statutory Settings")
	changed = False
	for field, component in SETTINGS_COMPONENTS.items():
		if not settings.get(field) and frappe.db.exists("Salary Component", component):
			settings.set(field, component)
			changed = True
	if settings.is_new() or changed or not settings.annual_working_days:
		for field in settings.meta.fields:
			if field.default and settings.get(field.fieldname) in (None, "", 0):
				settings.set(field.fieldname, field.default)
		settings.flags.ignore_permissions = True
		settings.save()

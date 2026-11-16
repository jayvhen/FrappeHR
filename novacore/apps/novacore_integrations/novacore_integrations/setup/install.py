"""Install / migrate routines for novacore_integrations (idempotent)."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def ro(**kw):
	return {"read_only": 1, "no_copy": 1, **kw}


CUSTOM_FIELDS = {
	"Employee": [
		{
			"fieldname": "ad_account",
			"label": "AD / M365 Account",
			"fieldtype": "Data",
			"insert_after": "user_id",
			**ro(),
		},
		{
			"fieldname": "ad_provisioning_status",
			"label": "Account Provisioning",
			"fieldtype": "Select",
			"options": "\nActive\nManual - Pending IT\nDisabled",
			"insert_after": "ad_account",
			**ro(),
		},
	],
	"Payroll Entry": [
		{
			"fieldname": "disbursement_status",
			"label": "Disbursement Status",
			"fieldtype": "Select",
			"options": "\nSent to Bank\nFile Ready\nNothing to Disburse",
			"insert_after": "rejection_reason",
			"allow_on_submit": 1,
			"in_list_view": 1,
			**ro(),
		},
		{
			"fieldname": "disbursement_reference",
			"label": "Bank Batch Reference",
			"fieldtype": "Data",
			"insert_after": "disbursement_status",
			"allow_on_submit": 1,
			**ro(),
		},
		{
			"fieldname": "disbursed_on",
			"label": "Disbursed On",
			"fieldtype": "Datetime",
			"insert_after": "disbursement_reference",
			"allow_on_submit": 1,
			**ro(),
		},
	],
	"Job Opening": [
		{
			"fieldname": "publish_to_job_boards",
			"label": "Publish to Job Boards",
			"fieldtype": "Check",
			"insert_after": "status",
		},
		{
			"fieldname": "job_board_status",
			"label": "Job Board Status",
			"fieldtype": "Data",
			"insert_after": "publish_to_job_boards",
			"depends_on": "publish_to_job_boards",
			**ro(),
		},
		{
			"fieldname": "job_board_reference",
			"label": "Job Board Reference",
			"fieldtype": "Data",
			"insert_after": "job_board_status",
			"hidden": 1,
			**ro(),
		},
	],
	"Job Offer": [
		{
			"fieldname": "e_signature_status",
			"label": "E-Signature Status",
			"fieldtype": "Select",
			"options": "Not Sent\nSent\nSigned\nDeclined",
			"default": "Not Sent",
			"insert_after": "status",
			"allow_on_submit": 1,
			**ro(),
		},
		{
			"fieldname": "e_signature_id",
			"label": "E-Signature Envelope ID",
			"fieldtype": "Data",
			"insert_after": "e_signature_status",
			"allow_on_submit": 1,
			"search_index": 1,
			**ro(),
		},
	],
}


CUSTOM_FIELDS["Additional Salary"] = [
	{
		"fieldname": "external_system",
		"label": "Source System",
		"fieldtype": "Data",
		"insert_after": "salary_component",
		"description": "ERP module that posted this entry through the API",
		**ro(),
	},
	{
		"fieldname": "external_reference",
		"label": "External Reference",
		"fieldtype": "Data",
		"insert_after": "external_system",
		"search_index": 1,
		**ro(),
	},
]

# API-only roles (no desk access): one Frappe user per external ERP module
INTEGRATION_ROLES = ("Biometric Device", "ERP Integration", "ERP Finance Integration")


def before_install():
	for role in INTEGRATION_ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 0}).insert(ignore_permissions=True)


def create_incentive_component():
	if not frappe.db.exists("Salary Component", "Sales Incentive"):
		doc = frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": "Sales Incentive",
				"salary_component_abbr": "SINC",
				"type": "Earning",
				"is_tax_applicable": 1,
				"depends_on_payment_days": 0,
				"description": "Commissions / incentives posted by the e-commerce modules via API",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)


def after_migrate():
	before_install()
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	create_incentive_component()
	settings = frappe.get_single("NovaCore Integration Settings")
	if not settings.request_timeout:
		for field in settings.meta.fields:
			if field.default and settings.get(field.fieldname) in (None, "", 0):
				settings.set(field.fieldname, field.default)
		settings.flags.ignore_permissions = True
		settings.save()
	frappe.db.commit()

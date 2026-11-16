"""AD Provisioning Connector (R5 - accounts created on hire, disabled on relieving date).

Uses Microsoft Graph (Entra ID / M365) with client-credentials. If provisioning is
disabled, IT receives a ToDo instead, so the step is tracked either way.
Communication Diagram 14: startOnboarding -> provisionAccount -> credentials ->
notify IT and Team Leader -> welcome email.
"""

import re
import secrets

import frappe
from frappe import _
from frappe.utils import cint

from novacore_ph.utils import send_email
from novacore_integrations.connectors.http import create_manual_task, get_settings, oauth2_client_credentials, request

GRAPH = "https://graph.microsoft.com/v1.0"


def _graph_token(settings) -> str:
	return oauth2_client_credentials(
		"Microsoft Graph",
		f"https://login.microsoftonline.com/{settings.ad_tenant_id}/oauth2/v2.0/token",
		settings.ad_client_id,
		settings.get_password("ad_client_secret"),
		scope="https://graph.microsoft.com/.default",
	)


def build_upn(employee, domain: str) -> str:
	first = re.sub(r"[^a-z]", "", (employee.first_name or "").lower())
	last = re.sub(r"[^a-z]", "", (employee.last_name or "").lower())
	base = ".".join(p for p in (first, last) if p) or employee.name.lower()
	return f"{base}@{domain}"


def provision_account(employee_name: str):
	employee = frappe.get_doc("Employee", employee_name)
	if employee.ad_account and employee.ad_provisioning_status == "Active":
		return
	settings = get_settings()

	if not cint(settings.ad_enabled):
		employee.db_set("ad_provisioning_status", "Manual - Pending IT")
		create_manual_task(employee, _("Create AD / Microsoft 365 account for new hire {0}").format(employee.employee_name))
		return

	upn = build_upn(employee, settings.ad_domain)
	token = _graph_token(settings)
	request(
		"Microsoft Graph",
		"POST",
		f"{GRAPH}/users",
		json_body={
			"accountEnabled": True,
			"displayName": employee.employee_name,
			"givenName": employee.first_name,
			"surname": employee.last_name or "",
			"mailNickname": upn.split("@")[0],
			"userPrincipalName": upn,
			"employeeId": employee.name,
			"department": employee.department or "",
			"jobTitle": employee.designation or "",
			"passwordProfile": {"forceChangePasswordNextSignIn": True, "password": secrets.token_urlsafe(12) + "aA1!"},
		},
		headers={"Authorization": f"Bearer {token}"},
		reference=employee,
	)
	employee.db_set({"ad_account": upn, "ad_provisioning_status": "Active"})
	employee.add_comment("Info", _("AD / M365 account {0} provisioned").format(upn))


def disable_account(employee_name: str):
	employee = frappe.get_doc("Employee", employee_name)
	if employee.ad_provisioning_status == "Disabled":
		return
	settings = get_settings()
	if not cint(settings.ad_enabled) or not employee.ad_account:
		employee.db_set("ad_provisioning_status", "Manual - Pending IT")
		create_manual_task(
			employee, _("Disable AD / Microsoft 365 account of separated employee {0}").format(employee.employee_name)
		)
		return
	token = _graph_token(settings)
	request(
		"Microsoft Graph",
		"PATCH",
		f"{GRAPH}/users/{employee.ad_account}",
		json_body={"accountEnabled": False},
		headers={"Authorization": f"Bearer {token}"},
		reference=employee,
	)
	employee.db_set("ad_provisioning_status", "Disabled")
	employee.add_comment("Info", _("AD / M365 account {0} disabled").format(employee.ad_account))


def _enqueue(fn, employee: str):
	frappe.enqueue(fn, employee_name=employee, queue="short", enqueue_after_commit=True)


def on_employee_update(doc, method=None):
	previous = doc.get_doc_before_save()
	if doc.status == "Left" and (not previous or previous.status != "Left"):
		_enqueue(disable_account, doc.name)


def on_onboarding_update(doc, method=None):
	"""Provision once the onboarding is linked to an employee record."""
	if not doc.employee or frappe.flags.in_demo_seed:
		return
	status = frappe.db.get_value("Employee", doc.employee, "ad_provisioning_status")
	if status in ("Active", "Manual - Pending IT", "Disabled"):
		return
	_enqueue(provision_account, doc.employee)
	notify_onboarding(doc)


def notify_onboarding(doc):
	"""3.5 notifyITandTL() and 4 sendWelcomeEmail()."""
	employee = frappe.get_doc("Employee", doc.employee)
	team_leader_user = (
		frappe.db.get_value("Employee", employee.reports_to, "user_id") if employee.reports_to else None
	)
	if team_leader_user:
		send_email(
			recipients=[team_leader_user],
			subject=_("New team member: {0}").format(employee.employee_name),
			message=_("{0} joins your team on {1}. Accounts and devices are being prepared.").format(
				employee.employee_name, frappe.format(employee.date_of_joining, "Date")
			),
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)
	welcome_to = employee.personal_email or employee.prefered_email or employee.user_id
	if welcome_to:
		send_email(
			recipients=[welcome_to],
			subject=_("Welcome to NovaCore Business Solutions"),
			message=_("Hi {0}, welcome aboard! Your start date is {1}. Your onboarding checklist is in Frappe HR.").format(
				employee.first_name, frappe.format(employee.date_of_joining, "Date")
			),
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)

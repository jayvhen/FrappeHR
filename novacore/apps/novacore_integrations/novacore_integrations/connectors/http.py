"""Shared outbound HTTP client: timeouts, retries and an Integration Request log per call."""

import json
import time

import frappe
import requests
from frappe import _
from frappe.utils import cint

SECRET_KEYS = {"authorization", "client_secret", "password", "api_key", "x-api-key", "access_token"}


def get_settings():
	return frappe.get_cached_doc("NovaCore Integration Settings")


def redact(data):
	if isinstance(data, dict):
		return {k: ("***" if k.lower() in SECRET_KEYS else redact(v)) for k, v in data.items()}
	if isinstance(data, list):
		return [redact(v) for v in data]
	return data


def log_request(service: str, url: str, payload, reference=None):
	doc = frappe.get_doc(
		{
			"doctype": "Integration Request",
			"integration_request_service": service,
			"request_description": url[:140],
			"is_remote_request": 0,
			"status": "Queued",
			"data": json.dumps(redact(payload), default=str)[:65000],
			"reference_doctype": reference.doctype if reference else None,
			"reference_docname": reference.name if reference else None,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def request(
	service: str,
	method: str,
	url: str,
	*,
	json_body=None,
	data=None,
	headers=None,
	params=None,
	reference=None,
	auth=None,
):
	"""Perform an HTTP call with retries; raises frappe.ValidationError on final failure."""
	settings = get_settings()
	timeout = cint(settings.request_timeout) or 30
	retries = cint(settings.max_retries)
	log = log_request(service, url, json_body if json_body is not None else data, reference)

	last_error = None
	for attempt in range(retries + 1):
		try:
			response = requests.request(
				method, url, json=json_body, data=data, headers=headers, params=params, timeout=timeout, auth=auth
			)
			if response.status_code >= 500 and attempt < retries:
				last_error = f"HTTP {response.status_code}"
				time.sleep(2**attempt)
				continue
			response.raise_for_status()
			body = response.json() if response.content and "json" in response.headers.get("Content-Type", "") else {}
			log.db_set({"status": "Completed", "output": json.dumps(redact(body), default=str)[:65000]})
			return body
		except requests.RequestException as e:
			last_error = str(e)
			if attempt < retries:
				time.sleep(2**attempt)

	log.db_set({"status": "Failed", "error": (last_error or "")[:65000]})
	frappe.throw(_("{0} request failed: {1}").format(service, last_error), title=_("Integration Error"))


def oauth2_client_credentials(service: str, token_url: str, client_id: str, client_secret: str, scope=None) -> str:
	payload = {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}
	if scope:
		payload["scope"] = scope
	body = request(service, "POST", token_url, data=payload)
	token = body.get("access_token")
	if not token:
		frappe.throw(_("{0}: token endpoint returned no access_token").format(service))
	return token


def create_manual_task(reference, description: str, role: str = "System Manager"):
	"""Fallback when a connector is disabled: a ToDo so a human completes the step."""
	users = [
		r.parent
		for r in frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, fields=["parent"])
		if r.parent not in ("Administrator", "Guest") and frappe.db.get_value("User", r.parent, "enabled")
	] or ["Administrator"]
	from novacore_ph.utils import assign_to

	assign_to(reference.doctype, reference.name, users, description)

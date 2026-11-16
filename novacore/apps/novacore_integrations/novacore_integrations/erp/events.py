"""Outbound HR events for the other ERP modules (signed webhooks).

Delivery contract (POST to the subscriber's endpoint_url):
  Headers  Content-Type: application/json
           X-NovaCore-Event: <event>
           X-NovaCore-Delivery: <uuid>            (idempotency key for the receiver)
           X-NovaCore-Signature: <hex HMAC-SHA256(secret, raw body)>
  Body     {"id": <uuid>, "event": <event>, "occurred_at": <ISO-8601>, "data": {...}}

Deliveries are queued after the HR transaction commits, retried by the shared HTTP
client, and logged in Integration Request.
"""

import hashlib
import hmac
import json
import uuid

import frappe
from frappe.utils import cint, now_datetime

from novacore_integrations.api.v1 import serialize_employee, payroll_summary_for_entry
from novacore_integrations.connectors.http import request
from novacore_integrations.novacore_integrations.doctype.erp_event_subscription.erp_event_subscription import (
	EVENT_FIELDS,
)


def publish(event: str, data: dict):
	field = EVENT_FIELDS[event]
	subscribers = frappe.get_all("ERP Event Subscription", filters={"enabled": 1, field: 1}, pluck="name")
	for name in subscribers:
		frappe.enqueue(
			deliver,
			queue="short",
			enqueue_after_commit=True,
			subscription=name,
			event=event,
			data=data,
		)


def deliver(subscription: str, event: str, data: dict):
	sub = frappe.get_doc("ERP Event Subscription", subscription)
	delivery_id = str(uuid.uuid4())
	body = json.dumps(
		{"id": delivery_id, "event": event, "occurred_at": now_datetime().isoformat(), "data": data},
		default=str,
		separators=(",", ":"),
	)
	signature = hmac.new(sub.get_password("secret").encode(), body.encode(), hashlib.sha256).hexdigest()
	request(
		f"ERP Webhook: {sub.system_name}",
		"POST",
		sub.endpoint_url,
		data=body,
		headers={
			"Content-Type": "application/json",
			"X-NovaCore-Event": event,
			"X-NovaCore-Delivery": delivery_id,
			"X-NovaCore-Signature": signature,
		},
		reference=sub,
	)


# ------------------------------------------------------------------ hooks
def on_employee_update(doc, method=None):
	if frappe.flags.in_install or frappe.flags.in_migrate:
		return
	payload = serialize_employee(doc)
	previous = doc.get_doc_before_save()
	if doc.flags.in_insert or not previous:
		publish("employee.created", payload)
		return
	if doc.status == "Left" and previous.status != "Left":
		publish("employee.separated", payload)
	elif any(previous.get(f) != doc.get(f) for f in payload_fields()):
		publish("employee.updated", payload)


def payload_fields():
	return (
		"first_name",
		"last_name",
		"status",
		"employment_stage",
		"department",
		"designation",
		"branch",
		"reports_to",
		"company_email",
		"user_id",
		"relieving_date",
	)


def on_payroll_released(payroll_entry):
	"""Registered in hooks under novacore_payroll_approved."""
	if not cint(payroll_entry.salary_slips_submitted):
		return
	publish("payroll.released", payroll_summary_for_entry(payroll_entry.name))

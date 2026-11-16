"""Biometric Connector (R2 - logs sync within 5 minutes, with failure alerts).

Terminals (or their push-sync agent) authenticate with an API key/secret of a user
holding the "Biometric Device" role and POST:

  POST /api/method/novacore_integrations.connectors.biometric.push_checkins
  Authorization: token <api_key>:<api_secret>
  {"device_id": "BIO-CAL-03",
   "logs": [{"device_user_id": "1025", "timestamp": "2026-11-03 21:52:00", "log_type": "IN"}]}

`device_user_id` matches Employee.attendance_device_id. Idempotent: a log already stored
for the same employee + timestamp is skipped, so devices can safely resend.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from novacore_ph.utils import send_email

DEVICE_ROLES = ("Biometric Device", "System Manager", "HR Manager")
MAX_LOGS_PER_REQUEST = 1000


def _get_device(device_id: str):
	device_id = (device_id or "").strip().upper()
	if not device_id or not frappe.db.exists("Biometric Device", device_id):
		frappe.throw(_("Unknown biometric device {0}").format(device_id), frappe.DoesNotExistError)
	device = frappe.get_doc("Biometric Device", device_id)
	if not device.enabled:
		frappe.throw(_("Biometric device {0} is disabled").format(device_id), frappe.PermissionError)
	return device


def _check_enabled():
	frappe.only_for(DEVICE_ROLES)
	if not cint(frappe.db.get_single_value("NovaCore Integration Settings", "biometric_enabled")):
		frappe.throw(_("Biometric push API is disabled"), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def push_checkins(device_id: str, logs):
	_check_enabled()
	device = _get_device(device_id)
	if isinstance(logs, str):
		logs = json.loads(logs)
	if not isinstance(logs, list):
		frappe.throw(_("logs must be a list"))
	if len(logs) > MAX_LOGS_PER_REQUEST:
		frappe.throw(_("At most {0} logs per request").format(MAX_LOGS_PER_REQUEST))

	inserted, skipped, errors = 0, 0, []
	employee_cache = {}
	for i, log in enumerate(logs):
		try:
			user_id = str(log.get("device_user_id") or "").strip()
			log_type = (log.get("log_type") or "").upper() or None
			if log_type not in (None, "IN", "OUT"):
				raise frappe.ValidationError(_("log_type must be IN or OUT"))
			timestamp = get_datetime(log.get("timestamp"))
			if not user_id or not timestamp:
				raise frappe.ValidationError(_("device_user_id and timestamp are required"))
			if timestamp > add_to_date(now_datetime(), minutes=10):
				raise frappe.ValidationError(_("timestamp is in the future"))

			if user_id not in employee_cache:
				employee_cache[user_id] = frappe.db.get_value(
					"Employee", {"attendance_device_id": user_id, "status": "Active"}, "name"
				)
			employee = employee_cache[user_id]
			if not employee:
				raise frappe.ValidationError(_("No active employee with device user id {0}").format(user_id))

			if frappe.db.exists("Employee Checkin", {"employee": employee, "time": timestamp}):
				skipped += 1
				continue

			frappe.get_doc(
				{
					"doctype": "Employee Checkin",
					"employee": employee,
					"time": timestamp,
					"log_type": log_type,
					"device_id": device.name,
				}
			).insert(ignore_permissions=True)
			inserted += 1
		except Exception as e:
			errors.append({"index": i, "error": str(e)})

	device.db_set(
		{
			"last_sync": now_datetime(),
			"status": "Online",
			"last_error": json.dumps(errors[:20]) if errors else None,
		}
	)
	return {"inserted": inserted, "skipped": skipped, "errors": errors}


@frappe.whitelist(methods=["POST"])
def heartbeat(device_id: str):
	"""Lets idle terminals report they are alive between check-ins."""
	_check_enabled()
	device = _get_device(device_id)
	device.db_set({"last_sync": now_datetime(), "status": "Online"})
	return {"status": "ok"}


def check_device_health():
	"""Every 5 minutes: devices silent longer than the alert window go Offline and alert HR/IT."""
	settings = frappe.get_cached_doc("NovaCore Integration Settings")
	if not cint(settings.biometric_enabled):
		return
	window = cint(settings.biometric_alert_minutes) or 5
	cutoff = add_to_date(now_datetime(), minutes=-window)
	stale = frappe.get_all(
		"Biometric Device",
		filters=[
			["enabled", "=", 1],
			["status", "=", "Online"],
			["last_sync", "is", "set"],
			["last_sync", "<", cutoff],
		],
		fields=["name", "location", "last_sync"],
	)
	for device in stale:
		frappe.db.set_value("Biometric Device", device.name, "status", "Offline")
		recipients = [settings.biometric_alert_email] if settings.biometric_alert_email else []
		if recipients:
			send_email(
				recipients=recipients,
				subject=_("Biometric device {0} offline").format(device.name),
				message=_("Device {0} ({1}) has not synced since {2}. Check-ins may be missing.").format(
					device.name, device.location or "", device.last_sync
				),
			)
		frappe.publish_realtime(
			"msgprint",
			{"message": _("Biometric device {0} is offline").format(device.name), "indicator": "red"},
			doctype="Biometric Device",
		)
	if stale:
		frappe.db.commit()

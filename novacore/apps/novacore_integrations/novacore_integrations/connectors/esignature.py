"""E-Signature Service for job offers (Communication Diagram 14: 1.1 requestSignature / 1.2 signed).

send_for_signature(job_offer)  -> creates an envelope at the provider
esignature_webhook             <- provider callback, authenticated by HMAC-SHA256 signature
On "signed" the offer is Accepted and HR gets a ToDo to create the Employee (2: createEmployee()).
"""

import hashlib
import hmac
import json

import frappe
from frappe import _
from frappe.utils import cint, get_url

from novacore_integrations.connectors.http import create_manual_task, get_settings, request


@frappe.whitelist()
def send_for_signature(job_offer: str):
	frappe.only_for(("HR Manager", "HR User", "System Manager"))
	doc = frappe.get_doc("Job Offer", job_offer)
	doc.check_permission("write")
	if doc.e_signature_status in ("Sent", "Signed"):
		frappe.throw(_("This offer is already {0}").format(doc.e_signature_status))
	settings = get_settings()
	if not cint(settings.esign_enabled):
		frappe.throw(_("Enable the E-Signature connector in NovaCore Integration Settings first"))

	email = frappe.db.get_value("Job Applicant", doc.job_applicant, "email_id")
	if not email:
		frappe.throw(_("The job applicant has no email address"))

	headers = {"Authorization": f"Bearer {settings.get_password('esign_api_key')}"} if settings.esign_api_key else {}
	body = request(
		"E-Signature",
		"POST",
		settings.esign_api_url,
		json_body={
			"reference": doc.name,
			"signer": {"name": doc.applicant_name, "email": email},
			"document_url": get_url(f"/printview?doctype=Job%20Offer&name={doc.name}"),
			"callback_url": get_url("/api/method/novacore_integrations.connectors.esignature.esignature_webhook"),
		},
		headers=headers,
		reference=doc,
	)
	envelope = str(body.get("envelope_id") or body.get("id") or "")
	if not envelope:
		frappe.throw(_("E-signature provider returned no envelope id"))
	doc.db_set({"e_signature_id": envelope[:140], "e_signature_status": "Sent"})
	return envelope


@frappe.whitelist(allow_guest=True, methods=["POST"])
def esignature_webhook():
	secret = get_settings().get_password("esign_webhook_secret", raise_exception=False)
	raw = frappe.request.get_data() or b""
	received = frappe.get_request_header("X-Signature") or ""
	expected = hmac.new((secret or "").encode(), raw, hashlib.sha256).hexdigest()
	if not secret or not hmac.compare_digest(expected, received):
		frappe.throw(_("Invalid signature"), frappe.AuthenticationError)

	payload = json.loads(raw or b"{}")
	envelope, event = str(payload.get("envelope_id") or ""), payload.get("event")
	name = frappe.db.get_value("Job Offer", {"e_signature_id": envelope}, "name")
	if not name:
		frappe.throw(_("Unknown envelope"), frappe.DoesNotExistError)

	frappe.set_user("Administrator")
	doc = frappe.get_doc("Job Offer", name)
	if event == "signed":
		doc.db_set({"e_signature_status": "Signed", "status": "Accepted"})
		doc.add_comment("Info", _("Offer signed electronically (envelope {0})").format(envelope))
		create_manual_task(doc, _("Offer signed by {0}: create the Employee record and start onboarding").format(
			doc.applicant_name), role="HR Manager")
	elif event == "declined":
		doc.db_set({"e_signature_status": "Declined", "status": "Rejected"})
		doc.add_comment("Info", _("Offer declined electronically"))
	else:
		frappe.throw(_("Unsupported event {0}").format(event))
	frappe.db.commit()
	return {"status": "ok"}

"""Job Board Publisher (Class Diagram: JobOpening.publishToJobBoards())."""

import frappe
from frappe import _
from frappe.utils import cint, get_url

from novacore_integrations.connectors.http import get_settings, request


def on_job_opening_update(doc, method=None):
	if not cint(doc.get("publish_to_job_boards")) or doc.status != "Open":
		return
	previous = doc.get_doc_before_save()
	if doc.job_board_status == "Published" and previous and previous.status == doc.status:
		return
	frappe.enqueue(publish_job_opening, job_opening=doc.name, queue="short", enqueue_after_commit=True)


def publish_job_opening(job_opening: str):
	doc = frappe.get_doc("Job Opening", job_opening)
	settings = get_settings()
	if not cint(settings.job_board_enabled):
		doc.db_set("job_board_status", "Careers Page Only")
		return
	headers = {"X-API-Key": settings.get_password("job_board_api_key")} if settings.job_board_api_key else {}
	body = request(
		"Job Boards",
		"POST",
		settings.job_board_url,
		json_body={
			"reference": doc.name,
			"title": doc.job_title,
			"designation": doc.designation,
			"company": doc.company,
			"location": doc.get("location") or "Calapan City",
			"vacancies": doc.get("planned_vacancies"),
			"description": doc.description,
			"apply_url": get_url(f"/jobs/{doc.route}") if doc.get("route") else get_url("/jobs"),
		},
		headers=headers,
		reference=doc,
	)
	doc.db_set({"job_board_status": "Published", "job_board_reference": str(body.get("id") or "")[:140]})
	doc.add_comment("Info", _("Published to job boards"))

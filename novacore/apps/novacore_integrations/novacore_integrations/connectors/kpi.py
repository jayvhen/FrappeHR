"""KPI Import Connector (R6 - appraisals import KPIs from QA systems).

Two directions:
  pull  import_kpis(appraisal_cycle)      HR clicks "Import KPIs" on the Appraisal Cycle
  push  push_kpis(appraisal_cycle, scores) QA system posts [{employee, kpi_score}]
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from novacore_integrations.connectors.http import get_settings, request


def apply_scores(appraisal_cycle: str, scores: list) -> dict:
	if not frappe.db.exists("Appraisal Cycle", appraisal_cycle):
		frappe.throw(_("Appraisal Cycle {0} not found").format(appraisal_cycle))
	updated, not_found, invalid = 0, [], []
	for row in scores:
		employee = (row.get("employee") or "").strip()
		score = row.get("kpi_score")
		if score is None or not 0 <= flt(score) <= 100:
			invalid.append(employee or str(row))
			continue
		appraisal = frappe.db.get_value(
			"Appraisal", {"employee": employee, "appraisal_cycle": appraisal_cycle, "docstatus": 0}, "name"
		)
		if not appraisal:
			not_found.append(employee)
			continue
		frappe.db.set_value("Appraisal", appraisal, "kpi_score", flt(score, 2))
		updated += 1
	return {"updated": updated, "not_found": not_found, "invalid": invalid}


@frappe.whitelist()
def import_kpis(appraisal_cycle: str):
	frappe.only_for(("HR Manager", "HR User", "System Manager"))
	settings = get_settings()
	if not cint(settings.kpi_enabled):
		frappe.throw(_("Enable the KPI connector in NovaCore Integration Settings first"))
	headers = {"X-API-Key": settings.get_password("kpi_api_key")} if settings.kpi_api_key else {}
	body = request(
		"KPI System",
		"GET",
		settings.kpi_api_url,
		params={"cycle": appraisal_cycle},
		headers=headers,
		reference=frappe.get_doc("Appraisal Cycle", appraisal_cycle),
	)
	scores = body if isinstance(body, list) else body.get("data", [])
	return apply_scores(appraisal_cycle, scores)


@frappe.whitelist(methods=["POST"])
def push_kpis(appraisal_cycle: str, scores):
	frappe.only_for(("HR Manager", "System Manager"))
	if isinstance(scores, str):
		scores = json.loads(scores)
	if not isinstance(scores, list):
		frappe.throw(_("scores must be a list of {employee, kpi_score}"))
	return apply_scores(appraisal_cycle, scores)

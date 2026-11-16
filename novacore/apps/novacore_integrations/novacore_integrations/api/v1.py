"""NovaCore HR - REST API v1 for the other ERP modules (see novacore/API.md).

Auth: each external system gets its own Frappe user with the "ERP Integration" role and
an API key/secret:  Authorization: token <api_key>:<api_secret>

Base path: /api/method/novacore_integrations.api.v1.<function>

Privacy (RA 10173): directory endpoints never return government IDs, salary, bank or
personal contact data. Payroll data is aggregated (per component / department), never
per-employee pay.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate

INTEGRATION_ROLES = ("ERP Integration", "System Manager")
FINANCE_ROLES = ("ERP Finance Integration", "System Manager")
MAX_PAGE = 500

EMPLOYEE_FIELDS = [
	"name",
	"employee_name",
	"first_name",
	"last_name",
	"status",
	"employment_stage",
	"company",
	"department",
	"designation",
	"branch",
	"reports_to",
	"company_email",
	"user_id",
	"date_of_joining",
	"relieving_date",
	"default_shift",
	"modified",
]


def _auth(roles=INTEGRATION_ROLES):
	frappe.only_for(roles)


def serialize_employee(row) -> dict:
	get = row.get
	return {
		"employee_id": get("name"),
		"full_name": get("employee_name"),
		"first_name": get("first_name"),
		"last_name": get("last_name"),
		"status": get("status"),
		"employment_stage": get("employment_stage"),
		"company": get("company"),
		"department": get("department"),
		"designation": get("designation"),
		"branch": get("branch"),
		"reports_to": get("reports_to"),
		"work_email": get("company_email") or get("user_id"),
		"user_id": get("user_id"),
		"date_of_joining": str(get("date_of_joining") or "") or None,
		"relieving_date": str(get("relieving_date") or "") or None,
		"shift": get("default_shift"),
		"modified": str(get("modified") or "") or None,
	}


# ------------------------------------------------------------- directory
@frappe.whitelist(methods=["GET"])
def get_employees(
	status: str | None = None,
	department: str | None = None,
	designation: str | None = None,
	modified_since: str | None = None,
	limit: int = 100,
	offset: int = 0,
):
	"""Employee directory. Use modified_since for incremental sync."""
	_auth()
	limit = min(max(cint(limit) or 100, 1), MAX_PAGE)
	filters = {}
	if status:
		if status not in ("Active", "Inactive", "Suspended", "Left"):
			frappe.throw(_("Invalid status"))
		filters["status"] = status
	if department:
		filters["department"] = department
	if designation:
		filters["designation"] = designation
	if modified_since:
		filters["modified"] = (">", get_datetime(modified_since))

	rows = frappe.get_all(
		"Employee",
		filters=filters,
		fields=EMPLOYEE_FIELDS,
		order_by="modified asc, name asc",
		limit_start=max(cint(offset), 0),
		limit_page_length=limit,
	)
	return {
		"data": [serialize_employee(r) for r in rows],
		"count": len(rows),
		"next_offset": cint(offset) + len(rows) if len(rows) == limit else None,
	}


@frappe.whitelist(methods=["GET"])
def get_employee(employee_id: str):
	_auth()
	row = frappe.db.get_value("Employee", employee_id, EMPLOYEE_FIELDS, as_dict=True)
	if not row:
		frappe.throw(_("Employee {0} not found").format(employee_id), frappe.DoesNotExistError)
	return serialize_employee(row)


@frappe.whitelist(methods=["GET"])
def get_departments(company: str | None = None):
	_auth()
	filters = {"is_group": 0}
	if company:
		filters["company"] = company
	departments = frappe.get_all(
		"Department",
		filters=filters,
		fields=["name", "department_name", "company", "parent_department", "site"],
		order_by="name",
	)
	headcount = dict(
		frappe.get_all(
			"Employee",
			filters={"status": "Active"},
			fields=["department", "count(name) as n"],
			group_by="department",
			as_list=True,
		)
	)
	for d in departments:
		d["active_headcount"] = headcount.get(d["name"], 0)
	return {"data": departments}


@frappe.whitelist(methods=["GET"])
def is_active_employee(user_or_employee: str):
	"""Fast access check for other modules (e.g. before assigning an order or a ticket)."""
	_auth()
	row = frappe.db.get_value(
		"Employee",
		{"name": user_or_employee} if frappe.db.exists("Employee", user_or_employee) else {"user_id": user_or_employee},
		["name", "status", "employment_stage"],
		as_dict=True,
	)
	if not row:
		return {"active": False, "employee_id": None}
	active = row.status == "Active" and row.employment_stage not in ("Suspended", "Separated")
	return {"active": active, "employee_id": row.name, "status": row.status, "employment_stage": row.employment_stage}


# ------------------------------------------------------- commissions (in)
@frappe.whitelist(methods=["POST"])
def post_incentives(source_system: str, payroll_date: str, entries):
	"""Sales / fulfillment incentives from the e-commerce modules -> payroll.

	entries: [{"employee_id", "amount", "reference", "component"?, "description"?}]
	Each becomes a submitted Additional Salary picked up by the next payroll run.
	Idempotent per (source_system, reference): re-posting the same reference is skipped.
	"""
	_auth()
	source_system = (source_system or "").strip()
	if not source_system:
		frappe.throw(_("source_system is required"))
	payroll_date = getdate(payroll_date)
	if isinstance(entries, str):
		entries = json.loads(entries)
	if not isinstance(entries, list) or not entries or len(entries) > MAX_PAGE:
		frappe.throw(_("entries must be a list of 1 to {0} items").format(MAX_PAGE))

	default_component = "Sales Incentive"
	created, skipped, errors = [], [], []
	for i, e in enumerate(entries):
		reference = str(e.get("reference") or "").strip()
		frappe.db.savepoint("incentive")
		try:
			if not reference:
				raise frappe.ValidationError(_("reference is required"))
			amount = flt(e.get("amount"), 2)
			if amount <= 0:
				raise frappe.ValidationError(_("amount must be greater than 0"))
			employee = e.get("employee_id")
			emp = frappe.db.get_value("Employee", employee, ["status", "company"], as_dict=True)
			if not emp or emp.status != "Active":
				raise frappe.ValidationError(_("employee {0} is not active").format(employee))
			component = e.get("component") or default_component
			if frappe.db.get_value("Salary Component", component, "type") != "Earning":
				raise frappe.ValidationError(_("{0} is not an earning component").format(component))

			existing = frappe.db.get_value(
				"Additional Salary",
				{"external_system": source_system, "external_reference": reference, "docstatus": ("<", 2)},
				"name",
			)
			if existing:
				skipped.append({"reference": reference, "additional_salary": existing})
				continue

			doc = frappe.get_doc(
				{
					"doctype": "Additional Salary",
					"employee": employee,
					"company": emp.company,
					"currency": frappe.get_cached_value("Company", emp.company, "default_currency"),
					"salary_component": component,
					"amount": amount,
					"payroll_date": payroll_date,
					"overwrite_salary_structure_amount": 0,
					"external_system": source_system,
					"external_reference": reference,
				}
			)
			doc.insert(ignore_permissions=True)
			doc.submit()
			created.append({"reference": reference, "additional_salary": doc.name})
		except Exception as ex:
			frappe.db.rollback(save_point="incentive")
			errors.append({"index": i, "reference": reference, "error": str(ex)})
	return {"created": created, "skipped": skipped, "errors": errors}


# ------------------------------------------------------- payroll (finance)
def payroll_summary_for_entry(payroll_entry: str) -> dict:
	entry = frappe.db.get_value(
		"Payroll Entry",
		payroll_entry,
		["name", "company", "start_date", "end_date", "posting_date", "currency", "salary_slips_submitted",
		 "approval_status"],
		as_dict=True,
	)
	if not entry:
		frappe.throw(_("Payroll Entry {0} not found").format(payroll_entry), frappe.DoesNotExistError)

	slip_filter = {"payroll_entry": payroll_entry, "docstatus": 1}
	totals = frappe.get_all(
		"Salary Slip",
		filters=slip_filter,
		fields=["count(name) as employees", "sum(gross_pay) as gross_pay", "sum(total_deduction) as total_deduction",
				"sum(net_pay) as net_pay"],
	)[0]
	by_department = frappe.get_all(
		"Salary Slip",
		filters=slip_filter,
		fields=["department", "count(name) as employees", "sum(gross_pay) as gross_pay", "sum(net_pay) as net_pay"],
		group_by="department",
	)
	components = frappe.db.sql(
		"""
		select sd.parentfield as type, sd.salary_component as component, sum(sd.amount) as amount
		from `tabSalary Detail` sd join `tabSalary Slip` ss on ss.name = sd.parent
		where ss.payroll_entry = %s and ss.docstatus = 1 and sd.parenttype = 'Salary Slip'
		group by sd.parentfield, sd.salary_component
		order by sd.parentfield, sd.salary_component
		""",
		payroll_entry,
		as_dict=True,
	)
	employer = frappe.db.sql(
		"""
		select c.agency, sum(c.employee_share) as employee_share, sum(c.employer_share) as employer_share,
			sum(c.ec_share) as ec_share
		from `tabPH Statutory Contribution` c join `tabSalary Slip` ss on ss.name = c.parent
		where ss.payroll_entry = %s and ss.docstatus = 1 and c.parenttype = 'Salary Slip'
		group by c.agency
		""",
		payroll_entry,
		as_dict=True,
	)
	return {
		"payroll_entry": entry.name,
		"company": entry.company,
		"period": {"start": str(entry.start_date), "end": str(entry.end_date)},
		"posting_date": str(entry.posting_date),
		"currency": entry.currency,
		"released": bool(cint(entry.salary_slips_submitted)),
		"approval_status": entry.approval_status,
		"totals": {k: flt(v) for k, v in totals.items()},
		"by_department": by_department,
		"components": [
			{"type": "earning" if c.type == "earnings" else "deduction", "component": c.component, "amount": flt(c.amount)}
			for c in components
		],
		"statutory": employer,
	}


@frappe.whitelist(methods=["GET"])
def get_payroll_summary(payroll_entry: str):
	"""Aggregated payroll for the Finance module's journal posting (no per-employee pay)."""
	_auth(FINANCE_ROLES)
	return payroll_summary_for_entry(payroll_entry)


@frappe.whitelist(methods=["GET"])
def list_payroll_runs(company: str | None = None, released_only: int = 1, limit: int = 50):
	_auth(FINANCE_ROLES)
	filters = {"docstatus": 1}
	if company:
		filters["company"] = company
	if cint(released_only):
		filters["salary_slips_submitted"] = 1
	return {
		"data": frappe.get_all(
			"Payroll Entry",
			filters=filters,
			fields=["name", "company", "start_date", "end_date", "posting_date", "approval_status",
					"salary_slips_submitted as released"],
			order_by="end_date desc",
			limit_page_length=min(cint(limit) or 50, MAX_PAGE),
		)
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def health():
	return {"status": "ok", "service": "novacore-hr", "api_version": "v1"}

"""Payroll approval workflow (Activity Diagram 11 / Sequence Diagram 12).

  Payroll Officer : create Payroll Entry -> create draft slips -> review exceptions
                    -> request_approval()
  HR/Finance Mgr  : approve()  -> slips submitted, accrual JV posted to ERPNext (GL),
                                  `novacore_payroll_approved` hooks run (bank, SMS)
                    reject(reason) -> returned to Payroll Officer for correction
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from novacore_ph.utils import send_email
from hrms.payroll.doctype.payroll_entry.payroll_entry import PayrollEntry

PREPARER_ROLES = {"Payroll Officer", "HR Manager", "System Manager"}
APPROVER_ROLES = {"HR Finance Manager", "System Manager"}


def approval_required() -> bool:
	return bool(cint(frappe.db.get_single_value("PH Statutory Settings", "require_payroll_approval")))


class NovaCorePayrollEntry(PayrollEntry):
	def before_submit(self):
		if not self.get("employees"):
			frappe.throw(
				_("Add employees first: use 'Get Employees' and save before submitting the Payroll Entry"),
				title=_("No Employees"),
			)
		super().before_submit()

	@frappe.whitelist()
	def submit_salary_slips(self):
		if approval_required() and not frappe.flags.ph_payroll_approved:
			frappe.throw(
				_("Salary slips are released only after HR/Finance approval. Use Payroll Approval > Request Approval."),
				title=_("Approval Required"),
			)
		return super().submit_salary_slips()


def _require_roles(roles: set, action: str):
	if not roles & set(frappe.get_roles()):
		frappe.throw(_("You are not permitted to {0}").format(action), frappe.PermissionError)


def _get_entry(name: str):
	doc = frappe.get_doc("Payroll Entry", name)
	doc.check_permission("read")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the Payroll Entry and create salary slips first"))
	return doc


def _draft_slip_count(name: str) -> int:
	return frappe.db.count("Salary Slip", {"payroll_entry": name, "docstatus": 0})


@frappe.whitelist()
def request_approval(payroll_entry: str):
	_require_roles(PREPARER_ROLES, _("request payroll approval"))
	doc = _get_entry(payroll_entry)
	if doc.approval_status == "Pending Approval":
		frappe.throw(_("Approval was already requested"))
	if doc.approval_status == "Approved":
		frappe.throw(_("This payroll is already approved"))
	if not _draft_slip_count(doc.name):
		frappe.throw(_("There are no draft salary slips to approve"))

	doc.db_set(
		{
			"approval_status": "Pending Approval",
			"approval_requested_by": frappe.session.user,
			"rejection_reason": None,
		}
	)
	doc.add_comment("Info", _("Approval requested by {0}").format(frappe.session.user))
	notify_approvers(doc)
	return doc.approval_status


@frappe.whitelist()
def approve(payroll_entry: str):
	_require_roles(APPROVER_ROLES, _("approve payroll"))
	doc = _get_entry(payroll_entry)
	if doc.approval_status != "Pending Approval":
		frappe.throw(_("Only payroll pending approval can be approved"))
	if doc.approval_requested_by == frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Segregation of duties: you cannot approve a payroll you submitted for approval"))

	doc.db_set({"approval_status": "Approved", "approved_by": frappe.session.user, "approved_on": now_datetime()})
	doc.add_comment("Info", _("Payroll approved by {0}").format(frappe.session.user))

	frappe.enqueue(
		release_payroll,
		queue="long",
		timeout=3600,
		payroll_entry=doc.name,
		enqueue_after_commit=True,
	)
	return doc.approval_status


@frappe.whitelist()
def reject(payroll_entry: str, reason: str):
	_require_roles(APPROVER_ROLES, _("reject payroll"))
	reason = (reason or "").strip()
	if len(reason) < 5:
		frappe.throw(_("Enter a reason for rejecting (at least 5 characters)"))
	doc = _get_entry(payroll_entry)
	if doc.approval_status != "Pending Approval":
		frappe.throw(_("Only payroll pending approval can be rejected"))

	doc.db_set({"approval_status": "Rejected", "rejection_reason": reason})
	doc.add_comment("Info", _("Payroll rejected by {0}: {1}").format(frappe.session.user, reason))
	if doc.approval_requested_by:
		send_email(
			recipients=[doc.approval_requested_by],
			subject=_("Payroll {0} returned for correction").format(doc.name),
			message=_("Payroll {0} was rejected.<br><br>Reason: {1}").format(doc.name, frappe.utils.escape_html(reason)),
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)
	return doc.approval_status


def release_payroll(payroll_entry: str):
	"""Background job: submit slips (+ GL accrual via HRMS), then run integration hooks."""
	# Authorization was enforced in approve(); post as Administrator so the approver does not
	# also need Salary Slip / Journal Entry submit rights. approved_by keeps the audit trail.
	frappe.set_user("Administrator")
	doc = frappe.get_doc("Payroll Entry", payroll_entry)
	frappe.flags.ph_payroll_approved = True
	try:
		from hrms.payroll.doctype.payroll_entry.payroll_entry import submit_salary_slips_for_employees

		slips = doc.get_sal_slip_list(ss_status=0)
		submit_salary_slips_for_employees(doc, slips, publish_progress=False)
	finally:
		frappe.flags.ph_payroll_approved = False

	doc.reload()
	if not cint(doc.salary_slips_submitted):
		doc.add_comment("Info", _("Salary slip submission failed; see Error Log"))
		return

	for handler in frappe.get_hooks("novacore_payroll_approved"):
		try:
			frappe.get_attr(handler)(doc)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Payroll release hook {handler} failed for {doc.name}")


def notify_approvers(doc):
	approvers = [
		r.parent
		for r in frappe.get_all("Has Role", filters={"role": "HR Finance Manager", "parenttype": "User"}, fields=["parent"])
		if r.parent not in ("Administrator", "Guest") and frappe.db.get_value("User", r.parent, "enabled")
	]
	if not approvers:
		return
	from novacore_ph.utils import assign_to

	assign_to(
		doc.doctype,
		doc.name,
		approvers,
		_("Approve payroll {0} ({1} to {2})").format(doc.name, doc.start_date, doc.end_date),
		priority="High",
	)

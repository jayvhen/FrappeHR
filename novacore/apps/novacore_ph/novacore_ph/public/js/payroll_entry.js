// NovaCore payroll approval workflow buttons on Payroll Entry
frappe.ui.form.on("Payroll Entry", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.salary_slips_submitted) return;

		const status = frm.doc.approval_status || "Draft";
		const roles = frappe.user_roles;
		const canPrepare = ["Payroll Officer", "HR Manager", "System Manager"].some((r) => roles.includes(r));
		const canApprove = ["HR Finance Manager", "System Manager"].some((r) => roles.includes(r));
		const call = (method, args = {}) =>
			frappe
				.call({
					method: `novacore_ph.payroll.payroll_entry.${method}`,
					args: { payroll_entry: frm.doc.name, ...args },
					freeze: true,
				})
				.then(() => frm.reload_doc());

		// HRMS adds its own "Submit Salary Slip" button; it is gated server-side,
		// so hide it until approval to avoid a confusing error.
		if (status !== "Approved") {
			frm.remove_custom_button(__("Submit Salary Slip"));
		}

		frm.dashboard.add_comment(
			__("Payroll approval: {0}", [`<b>${__(status)}</b>`]) +
				(frm.doc.rejection_reason ? ` — ${frappe.utils.escape_html(frm.doc.rejection_reason)}` : ""),
			{ "Pending Approval": "orange", Approved: "green", Rejected: "red" }[status] || "blue",
			true
		);

		if (canPrepare && ["Draft", "Rejected"].includes(status)) {
			frm.add_custom_button(__("Request Approval"), () => call("request_approval"), __("Payroll Approval"));
		}
		if (canApprove && status === "Pending Approval") {
			frm.add_custom_button(
				__("Approve & Release"),
				() =>
					frappe.confirm(
						__("Approve this payroll? Salary slips will be submitted, posted to accounting and disbursed."),
						() => call("approve")
					),
				__("Payroll Approval")
			);
			frm.add_custom_button(
				__("Reject"),
				() =>
					frappe.prompt(
						{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
						(v) => call("reject", { reason: v.reason }),
						__("Reject Payroll"),
						__("Reject")
					),
				__("Payroll Approval")
			);
		}
		frm.add_custom_button(
			__("Exceptions Report"),
			() => frappe.set_route("query-report", "Payroll Exceptions", { payroll_entry: frm.doc.name }),
			__("Payroll Approval")
		);
	},
});

frappe.ui.form.on("Payroll Entry", {
	refresh(frm) {
		if (!frm.doc.salary_slips_submitted || frm.doc.disbursement_status === "Sent to Bank") return;
		if (!["HR Finance Manager", "System Manager"].some((r) => frappe.user_roles.includes(r))) return;
		frm.add_custom_button(
			__("Retry Bank Disbursement"),
			() =>
				frappe
					.call({
						method: "novacore_integrations.connectors.bank.retry_disbursement",
						args: { payroll_entry: frm.doc.name },
						freeze: true,
					})
					.then(() => frm.reload_doc()),
			__("Payroll Approval")
		);
	},
});

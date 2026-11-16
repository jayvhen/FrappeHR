frappe.ui.form.on("Job Offer", {
	refresh(frm) {
		if (frm.is_new() || ["Sent", "Signed"].includes(frm.doc.e_signature_status)) return;
		if (frm.doc.docstatus === 2) return;
		frm.add_custom_button(__("Send for e-Signature"), () =>
			frappe
				.call({
					method: "novacore_integrations.connectors.esignature.send_for_signature",
					args: { job_offer: frm.doc.name },
					freeze: true,
					freeze_message: __("Sending offer for signature..."),
				})
				.then(() => {
					frappe.show_alert({ message: __("Offer sent for e-signature"), indicator: "green" });
					frm.reload_doc();
				})
		);
	},
});

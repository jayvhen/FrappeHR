frappe.ui.form.on("ERP Event Subscription", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.enabled) return;
		frm.add_custom_button(__("Send Test Event"), () =>
			frm.call("send_test_event").then((r) => frappe.show_alert({ message: r.message, indicator: "blue" }))
		);
	},
});

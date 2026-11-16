// NovaCore employee lifecycle indicator
frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.employment_stage) return;
		const colors = {
			Probationary: "blue",
			Regular: "green",
			"On Leave": "orange",
			Suspended: "red",
			"Notice Period": "yellow",
			Separated: "gray",
		};
		let msg = __("Employment stage: {0}", [`<b>${__(frm.doc.employment_stage)}</b>`]);
		if (frm.doc.employment_stage === "Probationary" && frm.doc.probation_end_date) {
			msg += " · " + __("probation ends {0}", [frappe.datetime.str_to_user(frm.doc.probation_end_date)]);
		}
		frm.dashboard.add_comment(msg, colors[frm.doc.employment_stage] || "blue", true);
	},
});

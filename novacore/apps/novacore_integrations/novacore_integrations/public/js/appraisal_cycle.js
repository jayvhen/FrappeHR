frappe.ui.form.on("Appraisal Cycle", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status === "Completed") return;
		frm.add_custom_button(
			__("Import KPIs from QA System"),
			() =>
				frappe
					.call({
						method: "novacore_integrations.connectors.kpi.import_kpis",
						args: { appraisal_cycle: frm.doc.name },
						freeze: true,
					})
					.then(({ message: r }) => {
						let msg = __("{0} appraisals updated.", [r.updated]);
						if (r.not_found.length) msg += "<br>" + __("No draft appraisal for: {0}", [r.not_found.join(", ")]);
						if (r.invalid.length) msg += "<br>" + __("Invalid scores for: {0}", [r.invalid.join(", ")]);
						frappe.msgprint({ title: __("KPI Import"), message: msg, indicator: "green" });
					}),
			__("Actions")
		);
	},
});

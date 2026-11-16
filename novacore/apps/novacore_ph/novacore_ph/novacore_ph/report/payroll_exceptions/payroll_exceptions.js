// Copyright (c) 2026, NovaCore Business Solutions Inc.
// License: MIT

frappe.query_reports["Payroll Exceptions"] = {
	filters: [
		{ fieldname: "payroll_entry", label: __("Payroll Entry"), fieldtype: "Link", options: "Payroll Entry" },
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "severity" && data) {
			const color = { High: "red", Medium: "orange", Low: "blue" }[data.severity];
			value = `<span class="indicator-pill ${color}">${value}</span>`;
		}
		return value;
	},
};

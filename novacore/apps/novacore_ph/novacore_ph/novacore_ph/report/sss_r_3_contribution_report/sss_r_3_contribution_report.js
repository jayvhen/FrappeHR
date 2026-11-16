// Copyright (c) 2026, NovaCore Business Solutions Inc.
// License: MIT

frappe.query_reports["SSS R-3 Contribution Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			reqd: 1,
			options: [
				"January", "February", "March", "April", "May", "June",
				"July", "August", "September", "October", "November", "December",
			],
			default: moment().format("MMMM"),
		},
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			reqd: 1,
			default: moment().year(),
		},
	],
};

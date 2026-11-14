frappe.query_reports["IQ Supplier Performance"] = {
	filters: [
		{ fieldname: "include_unmeasured", label: __("Include suppliers with no delivered shipments"), fieldtype: "Check" },
		{ fieldname: "include_inactive", label: __("Include inactive suppliers"), fieldtype: "Check" },
	],
};

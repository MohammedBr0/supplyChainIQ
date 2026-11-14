frappe.query_reports["IQ Stock Summary"] = {
	filters: [
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "IQ Warehouse" },
		{ fieldname: "item", label: __("Item"), fieldtype: "Link", options: "IQ Item" },
		{ fieldname: "only_attention", label: __("Only lines needing attention"), fieldtype: "Check" },
	],
};

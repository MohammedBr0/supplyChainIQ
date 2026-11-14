frappe.query_reports["IQ Landed Cost"] = {
	filters: [
		{ fieldname: "from_date", label: __("Planned ETA From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Planned ETA To"), fieldtype: "Date" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: ["", "Planned", "Booked", "In Transit", "At Port", "Customs Clearance", "Released", "Delivered", "Closed", "Cancelled"] },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "IQ Supplier" },
		{ fieldname: "only_costed", label: __("Only shipments with costs"), fieldtype: "Check", default: 1 },
	],
};

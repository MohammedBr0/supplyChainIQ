// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Stock Movement", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && ["Issue", "Transfer"].includes(frm.doc.movement_type)) {
			frm.set_intro(__("Leave Batch blank to let IQ allocate by FEFO (first expiry, first out). Save to see the allocation before submitting."), "blue");
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Stock Ledger"), () => frappe.set_route("List", "IQ Stock Ledger Entry", { reference_name: frm.doc.name }));
		}
	},
	movement_type(frm) { frm.trigger("refresh"); },
});

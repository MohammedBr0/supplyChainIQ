// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ LC Case", {
	refresh(frm) {
		frm.set_intro(__("IQ tracks your LC process. It does not issue LCs, allocate foreign currency or make bank decisions. Confirm all requirements and dates with your bank."), "blue");
		if (!frm.is_new()) {
			frm.add_custom_button(__("Load Checklist Template"), () => frm.call({ doc: frm.doc, method: "load_standard_checklist" }).then(() => frm.reload_doc()));
			frm.add_custom_button(__("Linked Shipments"), () => frappe.set_route("List", "IQ Shipment", { lc_case: frm.doc.name }));
		}
	},
});

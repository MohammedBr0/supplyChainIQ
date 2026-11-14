// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Customs Case", {
	refresh(frm) {
		frm.set_intro(__("Record amounts exactly as assessed by customs. Status follows the process dates; paid duties are added to the shipment's landed cost automatically."), "blue");
		if (frm.doc.shipment) frm.add_custom_button(__("Shipment"), () => frappe.set_route("Form", "IQ Shipment", frm.doc.shipment));
	},
});

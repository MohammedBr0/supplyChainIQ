// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Shipment", {
	refresh(frm) {
		if (frm.is_new()) return;
		if ((frm.doc.lines || []).some((l) => l.item && (l.quantity || 0) > (l.received_qty || 0))) {
			frm.add_custom_button(__("Create Receipt"), () => {
				frappe.prompt({ fieldname: "warehouse", label: __("Receive into warehouse"), fieldtype: "Link", options: "IQ Warehouse", reqd: 1 }, (v) =>
					frm.call({ doc: frm.doc, method: "create_receipt", args: v }).then((r) => frappe.set_route("Form", "IQ Stock Movement", r.message)),
				__("Create receipt from item lines"));
			}, __("Create"));
		}
		if (!frm.doc.customs_case) {
			frm.add_custom_button(__("Customs Case"), () => frappe.new_doc("IQ Customs Case", { shipment: frm.doc.name, declarant: frm.doc.transitor }), __("Create"));
		} else {
			frm.add_custom_button(__("Customs Case"), () => frappe.set_route("Form", "IQ Customs Case", frm.doc.customs_case), __("View"));
		}
		frm.add_custom_button(__("Cost Lines"), () => frappe.set_route("List", "IQ Cost Line", { shipment: frm.doc.name }), __("View"));
		if (frm.doc.created_via_portal) frm.set_intro(__("Created by the supplier through the portal (advance shipping notice). Check the details."), "blue");
	},
});

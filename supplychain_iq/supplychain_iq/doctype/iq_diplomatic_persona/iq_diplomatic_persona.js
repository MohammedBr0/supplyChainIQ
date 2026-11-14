// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Diplomatic Persona", {
	refresh(frm) {
		frm.set_intro(__("Personal data: visible only to Protocol Officers, HR Officers and Org Admins of your organization."), "blue");
		if (frm.is_new()) return;
		frm.add_custom_button(__("Diplomatic IDs"), () => frappe.set_route("List", "IQ Diplomatic ID", { persona: frm.doc.name }), __("View"));
		frm.add_custom_button(__("Personal Privileges"), () => frappe.set_route("List", "IQ Personal Privilege", { persona: frm.doc.name }), __("View"));
		frm.add_custom_button(__("Dependants"), () => frappe.set_route("List", "IQ Diplomatic Persona", { principal: frm.doc.name }), __("View"));
		frm.add_custom_button(__("New Diplomatic ID"), () => frappe.new_doc("IQ Diplomatic ID", { persona: frm.doc.name }), __("Add"));
		frm.add_custom_button(__("New Personal Privilege"), () => frappe.new_doc("IQ Personal Privilege", { persona: frm.doc.name }), __("Add"));
	},
});

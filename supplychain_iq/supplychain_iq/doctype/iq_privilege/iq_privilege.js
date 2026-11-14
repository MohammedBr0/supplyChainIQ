// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Privilege", {
	refresh(frm) {
		frm.set_intro(__("IQ tracks your organization's record of this approval. It is not the issuing authority and does not give legal advice; flag uncertain interpretations for legal review."), "blue");
		if (frm.is_new()) return;
		const call = (method, args) => frm.call({ doc: frm.doc, method, args }).then(() => frm.reload_doc());
		const ask = (title, method, required) => {
			frappe.prompt([{ fieldname: "notes", label: __("Notes"), fieldtype: "Small Text", reqd: required ? 1 : 0 }], (v) => call(method, v), title);
		};
		const s = frm.doc.review_status;
		if (["Draft", "Needs Legal Review"].includes(s)) frm.add_custom_button(__("Submit for Review"), () => call("submit_for_review")).addClass("btn-primary");
		const reviewer = ["IQ Compliance Officer", "IQ Org Admin", "System Manager"].some((r) => frappe.user.has_role(r));
		if (reviewer && s === "Under Review") {
			frm.add_custom_button(__("Confirm"), () => ask(__("Confirm privilege"), "confirm", false), __("Review"));
		}
		if (reviewer && ["Under Review", "Confirmed"].includes(s)) {
			frm.add_custom_button(__("Needs Legal Review"), () => ask(__("Flag for legal review"), "flag_legal_review", true), __("Review"));
			frm.add_custom_button(__("Revoke"), () => ask(__("Revoke"), "revoke", true), __("Review"));
		}
		frm.add_custom_button(__("Linked Shipments"), () => frappe.set_route("List", "IQ Shipment", { privilege: frm.doc.name }));
	},
});

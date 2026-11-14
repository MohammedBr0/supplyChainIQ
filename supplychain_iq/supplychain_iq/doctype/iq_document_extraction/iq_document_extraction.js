// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Document Extraction", {
	refresh(frm) {
		if (frm.is_new()) {
			frm.set_intro(__("Attach a PDF (with text) or .txt document and save. IQ proposes fields with evidence; you confirm before anything is applied."), "blue");
			return;
		}
		const call = (method, msg) => frm.call({ doc: frm.doc, method, freeze: true, freeze_message: msg }).then((r) => { frm.reload_doc(); return r; });
		if (["Draft", "Extracted"].includes(frm.doc.status)) {
			frm.add_custom_button(frm.doc.status === "Draft" ? __("Extract Fields") : __("Re-extract"), () => call("extract", __("Reading document..."))).addClass(frm.doc.status === "Draft" ? "btn-primary" : "");
		}
		if (frm.doc.status === "Extracted") {
			frm.set_intro(__("Check each value against the document (see the snippet), correct it if needed, tick Confirmed and save. Then Apply."), "orange");
			frm.add_custom_button(__("Apply Confirmed Fields"), () => {
				if (frm.is_dirty()) return frappe.msgprint(__("Save first."));
				call("apply").then((r) => r.message && frappe.show_alert({ message: __("Applied to {0}", [r.message]), indicator: "green" }));
			}).addClass("btn-success");
			frm.add_custom_button(__("Reject"), () => call("reject"), __("Actions"));
		}
		if (frm.doc.applied_to) frm.add_custom_button(__("Open {0}", [frm.doc.applied_to]), () => frappe.set_route("Form", frm.doc.applied_doctype, frm.doc.applied_to));
	},
});

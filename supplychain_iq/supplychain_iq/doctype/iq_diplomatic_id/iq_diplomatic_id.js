// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Diplomatic ID", {
	refresh(frm) {
		frm.set_intro(__("IQ tracks your organization's renewal workflow only. It does not submit anything to the Ministry of Foreign Affairs or any authority."), "blue");
		if (!frm.is_new()) {
			frm.add_custom_button(__("Load Requirements Template"), () =>
				frm.call({ doc: frm.doc, method: "load_standard_requirements" }).then(() => frm.reload_doc()));
		}
	},
});

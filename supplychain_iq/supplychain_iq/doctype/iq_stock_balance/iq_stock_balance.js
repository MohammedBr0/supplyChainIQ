// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Stock Balance", {
	refresh(frm) {
		if (!frm.is_new()) {
			frappe.db.count("IQ Stock Ledger Entry", { filters: { stock_balance: frm.doc.name } }).then((n) => {
				if (n) {
					frm.set_df_property("quantity", "read_only", 1);
					frm.set_df_property("quantity", "description", __("Managed by stock movements ({0} ledger entries). Use an Adjustment to correct it.", [n]));
					frm.add_custom_button(__("Stock Ledger"), () => frappe.set_route("List", "IQ Stock Ledger Entry", { stock_balance: frm.doc.name }));
				}
			});
		}
		if (frm.doc.qa_status === "Quarantined") {
			frm.set_intro(__("On QA hold: {0}", [frm.doc.qa_hold_reason || ""]), "red");
			const can = ["IQ QA Officer", "IQ Org Admin", "System Manager"].some((r) => frappe.user.has_role(r));
			if (can) {
				frm.add_custom_button(__("Record QA Decision"), () => {
					const d = new frappe.ui.Dialog({
						title: __("QA Decision"),
						fields: [
							{ fieldname: "decision", label: __("Decision"), fieldtype: "Select", options: "Released\nRejected", reqd: 1 },
							{ fieldname: "notes", label: __("Notes / evidence reviewed"), fieldtype: "Small Text", reqd: 1 },
						],
						primary_action_label: __("Record"),
						primary_action(v) {
							frm.call({ doc: frm.doc, method: "set_qa_decision", args: v }).then(() => { d.hide(); frm.reload_doc(); });
						},
					});
					d.show();
				}).addClass("btn-danger");
			}
		} else if (frm.doc.qa_status === "Rejected") {
			frm.set_intro(__("Rejected by QA. Dispose of it with an Adjustment Out movement."), "red");
		}
	},
});

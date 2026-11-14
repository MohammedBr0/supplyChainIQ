// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Import Batch", {
	refresh(frm) {
		if (frm.is_new()) return;
		const type = { "Existing Stock": "existing_stock", "Inbound Shipments": "inbound_shipments", "Temperature Readings": "temperature_readings" }[frm.doc.import_type];
		frm.add_custom_button(__("Download Template"), () => {
			window.open(`/assets/supplychain_iq/templates/${type}_template.csv`);
		});
		if (frm.doc.status === "Imported") {
			frm.set_intro(__("Imported by {0} on {1}. This batch is now read-only.", [frm.doc.imported_by, frm.doc.imported_on]), "green");
			frm.disable_save();
			return;
		}
		frm.add_custom_button(__("Validate & Preview"), () => {
			frm.call({ doc: frm.doc, method: "validate_file", freeze: true, freeze_message: __("Validating...") })
				.then(() => frm.reload_doc());
		}).addClass("btn-primary");
		if (frm.doc.status === "Validated") {
			frm.add_custom_button(__("Confirm Import"), () => {
				frappe.confirm(
					__("Import {0} rows into live records? This cannot be undone from this screen.", [frm.doc.total_rows]),
					() => frm.call({ doc: frm.doc, method: "confirm_import", freeze: true, freeze_message: __("Importing...") })
						.then((r) => {
							frappe.show_alert({ message: __("Created {0}, updated {1}", [r.message.created, r.message.updated]), indicator: "green" });
							frm.reload_doc();
						})
				);
			}).addClass("btn-success");
			frm.set_intro(__("Preview below. Check warnings, then Confirm Import."), "blue");
		} else if (frm.doc.status === "Has Errors") {
			frm.set_intro(__("Fix the errors in your file (or the column mapping), re-attach and validate again."), "red");
		} else {
			frm.set_intro(__("Save, then click Validate & Preview. Nothing is imported until you confirm."), "orange");
		}
	},
});

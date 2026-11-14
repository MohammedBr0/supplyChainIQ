// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Delivery", {
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, msg) => frm.call({ doc: frm.doc, method, freeze: true, freeze_message: msg }).then(() => frm.reload_doc());
		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Dispatch"), () =>
				frappe.confirm(__("Issue these items from {0} (FEFO) and mark dispatched?", [frm.doc.from_warehouse]), () => call("dispatch", __("Dispatching...")))
			).addClass("btn-primary");
		}
		if (frm.doc.status === "Dispatched") {
			frm.set_intro(__("To confirm: enter Delivered On, Received By, attach Proof of Delivery and (if short) the delivered quantities, save, then click Confirm Delivery."), "blue");
			frm.add_custom_button(__("Confirm Delivery"), () => {
				if (frm.is_dirty()) return frappe.msgprint(__("Save first."));
				call("confirm_delivery", __("Confirming..."));
			}).addClass("btn-success");
		}
		if (["Draft", "Dispatched"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Cancel Delivery"), () =>
				frappe.confirm(__("Cancel this delivery? Dispatched stock is returned to the warehouse."), () => call("cancel_delivery"))
			, __("Actions"));
		}
		if (frm.doc.status === "Partially Delivered") {
			frm.set_intro(__("Short delivery. Record returned goods with Record Return; the delivery closes when every unit is delivered or returned."), "orange");
		}
		if (["Dispatched", "Delivered", "Partially Delivered"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Record Return"), () => {
				const fields = frm.doc.items.map((r, i) => ({ fieldname: "q" + i, fieldtype: "Float", label: `${r.item_name || r.item} (${__("dispatched")} ${r.quantity}, ${__("returned")} ${r.returned_qty || 0})` }));
				fields.push({ fieldname: "warehouse", fieldtype: "Link", options: "IQ Warehouse", label: __("Return to warehouse"), default: frm.doc.from_warehouse, reqd: 1 });
				fields.push({ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 });
				const d = new frappe.ui.Dialog({ title: __("Record Return (goods go on QA hold for inspection)"), fields,
					primary_action_label: __("Record"),
					primary_action(v) {
						const returns = frm.doc.items.map((r, i) => ({ item: r.item, quantity: v["q" + i] || 0 }));
						frm.call({ doc: frm.doc, method: "record_return", args: { returns, warehouse: v.warehouse, reason: v.reason } }).then(() => { d.hide(); frm.reload_doc(); });
					} });
				d.show();
			}, __("Actions"));
		}
	},
});

// Copyright (c) 2026, SupplyChain IQ

frappe.ui.form.on("IQ Integration Connection", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(frm.doc.api_key ? __("Rotate API Credentials") : __("Generate API Credentials"), () =>
			frappe.confirm(__("Generate new credentials? Any previous secret stops working immediately."), () =>
				frm.call({ doc: frm.doc, method: "generate_credentials" }).then((r) => {
					frappe.msgprint({
						title: __("Copy the secret now"),
						message: `<p>${__("API key")}: <code>${frappe.utils.escape_html(r.message.api_key)}</code></p>
							<p>${__("API secret")}: <code>${frappe.utils.escape_html(r.message.api_secret)}</code></p>
							<p>${__("It will not be shown again. Send requests with the header")} <code>Authorization: token &lt;key&gt;:&lt;secret&gt;</code></p>
							<p>${__("Endpoints")}: <code>/api/method/supplychain_iq.api.integration.upsert_purchase_orders</code>, <code>…upsert_shipments</code>, <code>…upsert_stock_counts</code></p>`,
					});
					frm.reload_doc();
				})));
		frm.add_custom_button(__("Integration Log"), () => frappe.set_route("List", "IQ Integration Log", { connection: frm.doc.name }));
	},
});

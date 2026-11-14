"""Diplomatic Affairs now lives in the SupplyChain IQ desk module: drop the old module and its sidebar."""

import frappe


def execute():
	for dt in ("IQ Diplomatic Persona", "IQ Diplomatic ID", "IQ Personal Privilege", "IQ Privilege Utilisation", "IQ Renewal Requirement"):
		if frappe.db.exists("DocType", dt):
			frappe.db.set_value("DocType", dt, "module", "SupplyChain IQ", update_modified=False)
	if frappe.db.exists("Page", "iq-diplomatic"):
		frappe.db.set_value("Page", "iq-diplomatic", "module", "SupplyChain IQ", update_modified=False)
	if frappe.db.exists("Sidebar", "Diplomatic Affairs"):
		frappe.delete_doc("Sidebar", "Diplomatic Affairs", force=True, ignore_permissions=True)
	if frappe.db.exists("Module Def", "Diplomatic Affairs") and not frappe.db.exists("DocType", {"module": "Diplomatic Affairs"}):
		frappe.delete_doc("Module Def", "Diplomatic Affairs", force=True, ignore_permissions=True)
	frappe.clear_cache()

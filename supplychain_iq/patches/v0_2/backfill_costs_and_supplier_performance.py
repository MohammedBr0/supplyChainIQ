"""Stage 4: fill the new calculated shipment and supplier fields for existing records."""

import frappe

from supplychain_iq.intelligence import costs, suppliers


def execute():
	for name in frappe.get_all("IQ Shipment", pluck="name"):
		costs.update_shipment_costs(name)
	for name in frappe.get_all("IQ Supplier", pluck="name"):
		suppliers.update_supplier(name)

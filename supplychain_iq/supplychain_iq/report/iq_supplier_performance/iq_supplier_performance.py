# Supplier on-time arrival, delay, transit and PO lead time.

import frappe
from frappe import _

from supplychain_iq.intelligence.suppliers import compute


def execute(filters=None):
	filters = frappe._dict(filters or {})
	f = {"is_active": 1} if not filters.include_inactive else {}
	# get_list applies SupplyChain IQ tenant filtering and role permissions
	suppliers = frappe.get_list("IQ Supplier", filters=f, fields=["name", "supplier_name", "country"], limit_page_length=0)
	data = []
	for s in suppliers:
		perf = compute(s.name)  # live calculation, not the cached fields
		if not perf["shipments_measured"] and not filters.include_unmeasured:
			continue
		data.append({**s, **perf})
	data.sort(key=lambda r: (r["on_time_rate"] is None, r["on_time_rate"] or 0))
	columns = [
		{"fieldname": "name", "label": _("Supplier"), "fieldtype": "Link", "options": "IQ Supplier", "width": 120},
		{"fieldname": "supplier_name", "label": _("Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "country", "label": _("Country"), "fieldtype": "Data", "width": 100},
		{"fieldname": "shipments_measured", "label": _("Shipments Measured"), "fieldtype": "Int", "width": 130},
		{"fieldname": "on_time_shipments", "label": _("On Time"), "fieldtype": "Int", "width": 90},
		{"fieldname": "on_time_rate", "label": _("On-Time %"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "avg_delay_days", "label": _("Avg Delay (days)"), "fieldtype": "Float", "precision": 1, "width": 120},
		{"fieldname": "avg_transit_days", "label": _("Avg Transit (days)"), "fieldtype": "Float", "precision": 1, "width": 130},
		{"fieldname": "avg_po_lead_time_days", "label": _("Avg PO Lead Time (days)"), "fieldtype": "Float", "precision": 1, "width": 160},
	]
	return columns, data

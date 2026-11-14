# Landed cost per shipment, by cost category, in the organization's base currency.

import frappe
from frappe import _

from supplychain_iq.intelligence import calculations as calc
from supplychain_iq.intelligence.costs import base_currency

CATEGORIES = (
	"Purchase Price", "Freight", "Insurance", "Duties & Taxes", "Customs Clearance", "Port & Handling",
	"Storage", "Demurrage & Detention", "Inland Transport", "Distribution", "Other",
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	ship_filters = {}
	if filters.status:
		ship_filters["status"] = filters.status
	if filters.supplier:
		ship_filters["supplier"] = filters.supplier
	if filters.from_date and filters.to_date:
		ship_filters["planned_eta"] = ["between", [filters.from_date, filters.to_date]]
	elif filters.from_date:
		ship_filters["planned_eta"] = [">=", filters.from_date]
	elif filters.to_date:
		ship_filters["planned_eta"] = ["<=", filters.to_date]

	# get_list applies SupplyChain IQ tenant filtering and role permissions
	shipments = frappe.get_list(
		"IQ Shipment",
		filters=ship_filters,
		fields=["name", "organization", "shipment_title", "status", "supplier", "planned_eta", "quantity", "uom"],
		order_by="planned_eta desc",
		limit_page_length=0,
	)
	lines = frappe.get_list(
		"IQ Cost Line",
		filters={"shipment": ["in", [s.name for s in shipments] or [""]]},
		fields=["shipment", "cost_category", "cost_status", "amount_base"],
		limit_page_length=0,
	)
	by_ship = {}
	for line in lines:
		by_ship.setdefault(line.shipment, []).append(line)

	data = []
	for s in shipments:
		summary = calc.landed_cost(by_ship.get(s.name, []))
		if filters.only_costed and not by_ship.get(s.name):
			continue
		row = {
			"shipment": s.name, "shipment_title": s.shipment_title, "status": s.status, "supplier": s.supplier,
			"planned_eta": s.planned_eta, "currency": base_currency(s.organization),
			"estimate": summary["estimate"], "actual": summary["actual"], "landed_cost": summary["total"],
			"quantity": s.quantity, "uom": s.uom, "per_unit": calc.per_unit(summary["total"], s.quantity),
			"overrun_pct": summary["overrun_pct"],
		}
		for cat in CATEGORIES:
			row[frappe.scrub(cat)] = summary["by_category"].get(cat, 0)
		data.append(row)
	return get_columns(), data


def get_columns():
	cols = [
		{"fieldname": "shipment", "label": _("Shipment"), "fieldtype": "Link", "options": "IQ Shipment", "width": 150},
		{"fieldname": "shipment_title", "label": _("Description"), "fieldtype": "Data", "width": 220},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "supplier", "label": _("Supplier"), "fieldtype": "Link", "options": "IQ Supplier", "width": 120},
		{"fieldname": "planned_eta", "label": _("Planned ETA"), "fieldtype": "Date", "width": 100},
		{"fieldname": "currency", "label": _("Base Currency"), "fieldtype": "Data", "width": 80},
	]
	for cat in CATEGORIES:
		cols.append({"fieldname": frappe.scrub(cat), "label": _(cat), "fieldtype": "Float", "precision": 2, "width": 110})
	cols += [
		{"fieldname": "estimate", "label": _("Estimated Total"), "fieldtype": "Float", "precision": 2, "width": 120},
		{"fieldname": "actual", "label": _("Actual Total"), "fieldtype": "Float", "precision": 2, "width": 120},
		{"fieldname": "landed_cost", "label": _("Landed Cost"), "fieldtype": "Float", "precision": 2, "width": 130},
		{"fieldname": "quantity", "label": _("Quantity"), "fieldtype": "Float", "width": 90},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Data", "width": 80},
		{"fieldname": "per_unit", "label": _("Landed Cost / Unit"), "fieldtype": "Float", "precision": 4, "width": 130},
		{"fieldname": "overrun_pct", "label": _("Overrun %"), "fieldtype": "Percent", "width": 90},
	]
	return cols

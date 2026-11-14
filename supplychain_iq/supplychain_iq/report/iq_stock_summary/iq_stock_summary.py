# Stock by item and warehouse: on hand, issuable, on hold, expired, consumption and cover.

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today


def execute(filters=None):
	filters = frappe._dict(filters or {})
	t = getdate(today())
	bf = {}
	if filters.warehouse:
		bf["warehouse"] = filters.warehouse
	if filters.item:
		bf["item"] = filters.item
	# get_list applies SupplyChain IQ tenant filtering and role permissions
	balances = frappe.get_list(
		"IQ Stock Balance",
		filters=bf,
		fields=["item", "item_name", "uom", "warehouse", "quantity", "expiry_date", "qa_status", "avg_monthly_consumption"],
		limit_page_length=0,
	)
	issues = {}
	if frappe.has_permission("IQ Stock Ledger Entry", "read"):
		for e in frappe.get_list(
			"IQ Stock Ledger Entry",
			filters={"entry_type": "Issue", "is_cancelled": 0, "posting_date": [">=", add_days(t, -90)], **bf},
			fields=["item", "warehouse", "qty_change"],
			limit_page_length=0,
		):
			key = (e.item, e.warehouse)
			issues[key] = issues.get(key, 0) - flt(e.qty_change)
	wh_names = dict(frappe.get_list("IQ Warehouse", fields=["name", "warehouse_name"], as_list=True, limit_page_length=0))
	rows = {}
	for b in balances:
		key = (b.item, b.warehouse)
		r = rows.setdefault(key, {
			"item": b.item, "item_name": b.item_name, "uom": b.uom, "warehouse": b.warehouse,
			"warehouse_name": wh_names.get(b.warehouse, b.warehouse), "on_hand": 0, "available": 0,
			"on_hold": 0, "expired": 0, "recorded_amc": 0, "earliest_expiry": None,
		})
		qty = flt(b.quantity)
		expired = bool(b.expiry_date and getdate(b.expiry_date) < t)
		r["on_hand"] += qty
		if b.qa_status != "Released":
			r["on_hold"] += qty
		elif expired:
			r["expired"] += qty
		else:
			r["available"] += qty
			if b.expiry_date and qty > 0 and (r["earliest_expiry"] is None or getdate(b.expiry_date) < r["earliest_expiry"]):
				r["earliest_expiry"] = getdate(b.expiry_date)
		r["recorded_amc"] = max(r["recorded_amc"], flt(b.avg_monthly_consumption))
	data = []
	for key, r in rows.items():
		issued = issues.get(key, 0)
		r["issued_90d"] = issued
		if issued > 0:
			r["amc"], r["amc_basis"] = round(issued / 3, 2), _("Issues, last 90 days")
		elif r["recorded_amc"]:
			r["amc"], r["amc_basis"] = r["recorded_amc"], _("Recorded on stock lines")
		else:
			r["amc"], r["amc_basis"] = None, _("Unknown")
		r["cover_months"] = round(r["available"] / r["amc"], 2) if r["amc"] else None
		if filters.only_attention and not (r["on_hold"] or r["expired"] or (r["cover_months"] is not None and r["cover_months"] < 1) or not r["available"]):
			continue
		data.append(r)
	data.sort(key=lambda r: (r["cover_months"] is None, r["cover_months"] or 0))
	return COLUMNS, data


COLUMNS = [
	{"fieldname": "item", "label": _("Item"), "fieldtype": "Link", "options": "IQ Item", "width": 110},
	{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 200},
	{"fieldname": "warehouse", "label": _("Warehouse"), "fieldtype": "Link", "options": "IQ Warehouse", "width": 100},
	{"fieldname": "warehouse_name", "label": _("Warehouse Name"), "fieldtype": "Data", "width": 170},
	{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Data", "width": 70},
	{"fieldname": "on_hand", "label": _("On Hand"), "fieldtype": "Float", "width": 90},
	{"fieldname": "available", "label": _("Issuable"), "fieldtype": "Float", "width": 90},
	{"fieldname": "on_hold", "label": _("QA Hold"), "fieldtype": "Float", "width": 80},
	{"fieldname": "expired", "label": _("Expired"), "fieldtype": "Float", "width": 80},
	{"fieldname": "earliest_expiry", "label": _("Next Expiry (issuable)"), "fieldtype": "Date", "width": 130},
	{"fieldname": "issued_90d", "label": _("Issued (90d)"), "fieldtype": "Float", "width": 100},
	{"fieldname": "amc", "label": _("Avg Monthly Consumption"), "fieldtype": "Float", "precision": 2, "width": 120},
	{"fieldname": "amc_basis", "label": _("AMC Basis"), "fieldtype": "Data", "width": 160},
	{"fieldname": "cover_months", "label": _("Cover (months)"), "fieldtype": "Float", "precision": 2, "width": 110},
]

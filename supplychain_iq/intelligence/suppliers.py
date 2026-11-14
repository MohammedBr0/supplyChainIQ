"""Supplier performance roll-up (on-time arrival, delay, transit, PO lead time)."""

import frappe
from frappe.utils import getdate, now_datetime

from supplychain_iq.intelligence import calculations as calc

MEASURED_STATUSES = ("Delivered", "Closed")


def _d(value):
	return getdate(value) if value else None


def compute(supplier: str) -> dict:
	shipments = frappe.get_all(
		"IQ Shipment",
		filters={"supplier": supplier, "status": ["in", MEASURED_STATUSES]},
		fields=["planned_eta", "actual_eta", "actual_etd", "purchase_order"],
	)
	rows = [
		{
			"planned_eta": _d(s.planned_eta),
			"actual_eta": _d(s.actual_eta),
			"actual_etd": _d(s.actual_etd),
			"purchase_order": s.purchase_order,
		}
		for s in shipments
	]
	pos = {s.purchase_order for s in shipments if s.purchase_order}
	po_dates = {
		p.name: _d(p.order_date)
		for p in frappe.get_all("IQ Purchase Order", filters={"name": ["in", list(pos)]}, fields=["name", "order_date"])
	} if pos else {}
	return calc.supplier_performance(rows, po_dates)


def update_supplier(supplier: str | None):
	if not supplier or not frappe.db.exists("IQ Supplier", supplier):
		return
	perf = compute(supplier)
	values = {k: (v if v is not None else 0) for k, v in perf.items()}
	values["performance_updated_on"] = now_datetime()
	frappe.db.set_value("IQ Supplier", supplier, values, update_modified=False)


def update_all():
	for supplier in frappe.get_all("IQ Supplier", pluck="name"):
		update_supplier(supplier)
	frappe.db.commit()

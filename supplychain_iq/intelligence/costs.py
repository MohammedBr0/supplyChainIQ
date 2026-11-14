"""Exchange-rate resolution and shipment landed-cost roll-up."""

import re

import frappe
from frappe import _
from frappe.utils import getdate, today

from supplychain_iq.intelligence import calculations as calc

STOP_MILESTONES = ("Customs Released", "Delivered to Warehouse", "Goods Received")
STOPPED_STATUSES = ("Released", "Delivered", "Closed", "Cancelled")


def normalize_currency(value: str | None, label: str = "Currency") -> str | None:
	if not value:
		return None
	value = value.strip().upper()
	if not re.fullmatch(r"[A-Z]{3}", value):
		frappe.throw(_("{0} must be a 3-letter ISO code, got {1}").format(label, value))
	return value


def base_currency(org: str) -> str:
	return (frappe.db.get_value("IQ Organization", org, "base_currency") or "ETB").upper()


def resolve_rate(org: str, currency: str, on_date) -> tuple[float, str, str | None]:
	"""Return (rate to base, basis, exchange rate record) for a currency on a date."""
	base = base_currency(org)
	if currency == base:
		return 1.0, "Same Currency", None
	rows = frappe.get_all(
		"IQ Exchange Rate",
		filters={"organization": org, "from_currency": currency, "rate_date": ["<=", on_date]},
		fields=["name", "rate"],
		order_by="rate_date desc, creation desc",
		limit=1,
	)
	if not rows:
		frappe.throw(
			_("No exchange rate from {0} to {1} on or before {2}. Add an IQ Exchange Rate or enter a manual rate.").format(
				currency, base, on_date
			)
		)
	return float(rows[0].rate), "Exchange Rate Record", rows[0].name


def shipment_cost_summary(shipment: str) -> dict:
	lines = frappe.get_all(
		"IQ Cost Line",
		filters={"shipment": shipment},
		fields=["cost_category", "cost_status", "amount_base"],
	)
	summary = calc.landed_cost(lines)
	summary["count"] = len(lines)
	return summary


def update_shipment_costs(shipment: str):
	"""Write the cost roll-up onto the shipment without re-running its validation."""
	if not frappe.db.exists("IQ Shipment", shipment):
		return
	org, qty = frappe.db.get_value("IQ Shipment", shipment, ["organization", "quantity"])
	values = cost_fields(shipment, org, qty)
	frappe.db.set_value("IQ Shipment", shipment, values, update_modified=False)


def cost_fields(shipment: str | None, org: str, quantity) -> dict:
	s = shipment_cost_summary(shipment) if shipment else calc.landed_cost([]) | {"count": 0}
	return {
		"base_currency": base_currency(org),
		"landed_cost_estimate": s["estimate"],
		"landed_cost_actual": s["actual"],
		"landed_cost_total": s["total"],
		"landed_cost_per_unit": calc.per_unit(s["total"], quantity) or 0,
		"cost_lines_count": s["count"],
	}


def demurrage_stop_date(doc) -> object:
	"""Date demurrage stopped accruing, from milestones; None while still accruing."""
	dates = [getdate(m.actual_date) for m in doc.get("milestones") or [] if m.milestone in STOP_MILESTONES and m.actual_date]
	if dates:
		return min(dates)
	if doc.status in STOPPED_STATUSES:
		return getdate(doc.actual_eta) if doc.actual_eta else getdate(doc.modified or today())
	return None


def shipment_demurrage(doc) -> dict:
	return calc.demurrage(
		getdate(doc.free_time_start) if doc.free_time_start else None,
		doc.free_time_days if doc.free_time_start else None,
		doc.demurrage_rate_per_day,
		demurrage_stop_date(doc),
		getdate(today()),
	)

"""Deterministic business calculations.

No AI is involved here: every number shown in IQ comes from these functions so
it can be traced back to the source record values.
"""

from datetime import date

SHIPMENT_CLOSED_STATUSES = ("Delivered", "Closed", "Cancelled")


def stock_cover_months(quantity: float | None, avg_monthly_consumption: float | None) -> float | None:
	"""Months of stock left at the recorded consumption rate.

	Returns None when consumption is missing or zero: stock cover cannot be
	calculated without it, and IQ must not invent a value.
	"""
	if quantity is None or not avg_monthly_consumption or avg_monthly_consumption <= 0:
		return None
	return round(float(quantity) / float(avg_monthly_consumption), 2)


def days_to_expiry(expiry: date | None, today: date) -> int | None:
	if not expiry:
		return None
	return (expiry - today).days


def stock_status(
	quantity: float,
	cover_months: float | None,
	expiry_days: int | None,
	low_cover_threshold: float,
	expiry_warning_days: int,
	qa_status: str | None = None,
) -> str:
	"""Single headline status; most severe condition wins."""
	if qa_status in ("Quarantined", "Rejected"):
		return "QA Hold"
	if expiry_days is not None and expiry_days < 0:
		return "Expired"
	if not quantity or quantity <= 0:
		return "Out of Stock"
	if expiry_days is not None and expiry_days <= expiry_warning_days:
		return "Expiring Soon"
	if cover_months is not None and cover_months < low_cover_threshold:
		return "Low"
	return "OK"


def shipment_delay_days(
	planned_eta: date | None, actual_eta: date | None, status: str, today: date
) -> int:
	"""Days past planned ETA.

	Arrived shipments compare actual vs planned ETA; open shipments compare
	today vs planned ETA. Never negative (early arrival = 0).
	"""
	if not planned_eta:
		return 0
	if actual_eta:
		reference = actual_eta
	elif status in SHIPMENT_CLOSED_STATUSES:
		return 0
	else:
		reference = today
	return max(0, (reference - planned_eta).days)


def milestone_status(planned: date | None, actual: date | None, current: str, today: date) -> str:
	if current == "Not Applicable":
		return current
	if actual:
		return "Done"
	if planned and planned < today:
		return "Overdue"
	return "Pending"


def delay_severity(delay_days: int, high_after: int, critical_after: int) -> str:
	if delay_days > critical_after:
		return "Critical"
	if delay_days > high_after:
		return "High"
	return "Medium"


# ---------------------------------------------------------------- cost intelligence


def landed_cost(lines: list[dict]) -> dict:
	"""Aggregate cost lines already converted to base currency.

	lines: dicts with cost_category, cost_status ("Estimate"/"Actual"), amount_base.
	Per category, actuals replace estimates once any actual exists, so the
	landed cost moves from estimate to actual as invoices arrive.
	"""
	by_cat: dict[str, dict[str, float]] = {}
	for line in lines:
		cat = by_cat.setdefault(line["cost_category"], {"Estimate": 0.0, "Actual": 0.0, "has_actual": False})
		amount = float(line.get("amount_base") or 0)
		cat[line["cost_status"]] += amount
		if line["cost_status"] == "Actual":
			cat["has_actual"] = True
	categories = {
		k: round(v["Actual"] if v["has_actual"] else v["Estimate"], 2) for k, v in by_cat.items()
	}
	estimate = round(sum(v["Estimate"] for v in by_cat.values()), 2)
	actual = round(sum(v["Actual"] for v in by_cat.values()), 2)
	# overrun is only meaningful where both an estimate and an actual exist
	compared = [v for v in by_cat.values() if v["has_actual"] and v["Estimate"]]
	compared_estimate = sum(v["Estimate"] for v in compared)
	compared_actual = sum(v["Actual"] for v in compared)
	overrun_pct = (
		round(100.0 * (compared_actual - compared_estimate) / compared_estimate, 1) if compared_estimate else None
	)
	return {
		"total": round(sum(categories.values()), 2),
		"estimate": estimate,
		"actual": actual,
		"by_category": categories,
		"overrun_pct": overrun_pct,
		"compared_estimate": round(compared_estimate, 2),
		"compared_actual": round(compared_actual, 2),
	}


def per_unit(total: float, quantity: float | None) -> float | None:
	if not quantity or quantity <= 0:
		return None
	return round(total / quantity, 4)


def demurrage(
	free_time_start: date | None,
	free_time_days: int | None,
	rate_per_day: float | None,
	stop_date: date | None,
	today: date,
) -> dict:
	"""Chargeable demurrage days and exposure.

	stop_date: when charges stop (cargo released/delivered); None = still accruing.
	"""
	if not free_time_start or free_time_days is None:
		return {"free_time_ends": None, "days": 0, "exposure": 0.0, "days_left": None}
	from datetime import timedelta

	ends = free_time_start + timedelta(days=int(free_time_days))
	reference = stop_date or today
	days = max(0, (reference - ends).days)
	return {
		"free_time_ends": ends,
		"days": days,
		"exposure": round(days * float(rate_per_day or 0), 2),
		"days_left": None if stop_date else (ends - today).days,
	}


# ---------------------------------------------------------------- supplier performance


def supplier_performance(shipments: list[dict], po_dates: dict | None = None) -> dict:
	"""On-time rate, delay, transit and PO lead time from delivered shipments.

	shipments: dicts with planned_eta, actual_eta, actual_etd, purchase_order.
	Only shipments with both planned and actual arrival are measured.
	"""
	po_dates = po_dates or {}
	measured = [s for s in shipments if s.get("planned_eta") and s.get("actual_eta")]
	on_time = [s for s in measured if s["actual_eta"] <= s["planned_eta"]]
	delays = [max(0, (s["actual_eta"] - s["planned_eta"]).days) for s in measured]
	transits = [
		(s["actual_eta"] - s["actual_etd"]).days
		for s in measured
		if s.get("actual_etd") and s["actual_eta"] >= s["actual_etd"]
	]
	leads = [
		(s["actual_etd"] - po_dates[s["purchase_order"]]).days
		for s in shipments
		if s.get("purchase_order") in po_dates and s.get("actual_etd") and po_dates[s["purchase_order"]]
		and s["actual_etd"] >= po_dates[s["purchase_order"]]
	]

	def avg(values):
		return round(sum(values) / len(values), 1) if values else None

	return {
		"shipments_measured": len(measured),
		"on_time_shipments": len(on_time),
		"on_time_rate": round(100.0 * len(on_time) / len(measured), 1) if measured else None,
		"avg_delay_days": avg(delays),
		"avg_transit_days": avg(transits),
		"avg_po_lead_time_days": avg(leads),
	}


# ---------------------------------------------------------------- warehouse


class InsufficientStock(ValueError):
	pass


def fefo_allocate(batches: list[dict], quantity: float) -> list[dict]:
	"""First-expiry-first-out allocation.

	batches: dicts with batch_no, quantity, expiry_date (date or None), already
	filtered to issuable stock (not expired, not on QA hold). Batches without an
	expiry date are used last. Returns [{batch_no, expiry_date, quantity}].
	"""
	if quantity <= 0:
		raise ValueError("Quantity must be positive")
	ordered = sorted(
		(b for b in batches if (b.get("quantity") or 0) > 0),
		key=lambda b: (b.get("expiry_date") is None, b.get("expiry_date") or date.max, str(b.get("batch_no") or "")),
	)
	remaining = quantity
	out = []
	for b in ordered:
		take = min(remaining, b["quantity"])
		out.append({"batch_no": b.get("batch_no"), "expiry_date": b.get("expiry_date"), "quantity": take})
		remaining = round(remaining - take, 9)
		if remaining <= 0:
			return out
	available = round(quantity - remaining, 9)
	raise InsufficientStock(f"only {available} available, {quantity} requested")


# ---------------------------------------------------------------- shipment lines


def allocate_cost(lines: list[dict], total: float, basis: str) -> list[dict]:
	"""Share a landed cost across lines by value (default) or quantity.

	lines: dicts with quantity and line_value. Falls back to quantity when no
	line has a value. Returns [{allocated_cost, landed_unit_cost}] in order;
	rounding residue goes to the last line so the parts add up to the total.
	"""
	if not lines:
		return []
	weights = [float(l.get("line_value") or 0) for l in lines] if basis == "Value" else []
	if not weights or not sum(weights):
		weights = [float(l.get("quantity") or 0) for l in lines]
	total_weight = sum(weights)
	out, running = [], 0.0
	for i, (line, w) in enumerate(zip(lines, weights, strict=True)):
		if i == len(lines) - 1:
			share = round(total - running, 2)
		else:
			share = round(total * w / total_weight, 2) if total_weight else 0.0
			running += share
		qty = float(line.get("quantity") or 0)
		out.append({"allocated_cost": share, "landed_unit_cost": round(share / qty, 4) if qty else 0.0})
	return out

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
) -> str:
	"""Single headline status; most severe condition wins."""
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

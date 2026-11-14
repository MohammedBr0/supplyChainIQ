"""Date parsing for spreadsheet intake, including Ethiopian-calendar dates.

Ambiguous numeric dates such as 03/04/2026 are read day-first (DD/MM/YYYY),
the usual convention in Ethiopia and most of Africa. The importer reports which
format was used so the user can check it in the preview.
"""

from datetime import date, datetime, timedelta

# Ethiopian (Amete Mihret) epoch expressed as a Julian Day Number offset.
_ETHIOPIAN_EPOCH_JDN = 1723856
_JDN_TO_ORDINAL = 1721425  # date.fromordinal(jdn - _JDN_TO_ORDINAL)

_FORMATS = (
	"%Y-%m-%d",
	"%d/%m/%Y",
	"%d-%m-%Y",
	"%d.%m.%Y",
	"%Y/%m/%d",
	"%d %b %Y",
	"%d %B %Y",
	"%b %d %Y",
	"%B %d %Y",
	"%d-%b-%Y",
	"%d-%b-%y",
)


class DateParseError(ValueError):
	pass


def ethiopian_to_gregorian(year: int, month: int, day: int) -> date:
	"""Convert an Ethiopian calendar date to the Gregorian calendar.

	Months 1-12 have 30 days; month 13 (Pagume) has 5 days, or 6 in the year
	before a Gregorian leap year (Ethiopian year % 4 == 3).
	"""
	if not (1 <= month <= 13):
		raise DateParseError(f"Ethiopian month must be 1-13, got {month}")
	max_day = 30 if month <= 12 else (6 if year % 4 == 3 else 5)
	if not (1 <= day <= max_day):
		raise DateParseError(f"Ethiopian month {month} has {max_day} days, got day {day}")
	jdn = _ETHIOPIAN_EPOCH_JDN + 365 + 365 * (year - 1) + year // 4 + 30 * month + day - 31
	return date.fromordinal(jdn - _JDN_TO_ORDINAL)


def _excel_serial(value: float) -> date:
	# Excel's day 0 is 1899-12-30 once the 1900 leap-year bug is accounted for
	return date(1899, 12, 30) + timedelta(days=int(value))


def _split_numeric(text: str) -> tuple[int, int, int] | None:
	for sep in ("-", "/", "."):
		parts = text.split(sep)
		if len(parts) == 3 and all(p.strip().isdigit() for p in parts):
			a, b, c = (int(p) for p in parts)
			if len(parts[0].strip()) == 4:
				return a, b, c  # Y M D
			return c, b, a  # D M Y -> Y M D
	return None


def parse_date(value, calendar: str = "Gregorian") -> date | None:
	"""Parse a cell value into a Gregorian date. Empty -> None."""
	if value is None:
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	if isinstance(value, int | float) and not isinstance(value, bool):
		if calendar == "Ethiopian":
			raise DateParseError("Ethiopian dates must be written as text, e.g. 01/13/2017 (DD/MM/YYYY)")
		if 1 <= value < 2958466:
			return _excel_serial(value)
		raise DateParseError(f"Unrecognised date number {value}")

	text = str(value).strip()
	if not text:
		return None

	if calendar == "Ethiopian":
		ymd = _split_numeric(text.split(" ")[0])
		if not ymd:
			raise DateParseError(f"Could not read Ethiopian date '{text}'. Use DD/MM/YYYY")
		return ethiopian_to_gregorian(*ymd)

	# strip a trailing time component, e.g. "2026-01-31 00:00:00"
	if len(text) > 10 and text[10] in " T" and text[:4].isdigit():
		text = text[:10]
	for fmt in _FORMATS:
		try:
			return datetime.strptime(text, fmt).date()
		except ValueError:
			continue
	try:
		serial = float(text)
	except ValueError:
		raise DateParseError(f"Could not read date '{value}'. Use YYYY-MM-DD or DD/MM/YYYY")
	return parse_date(serial, calendar)


_DT_FORMATS = (
	"%Y-%m-%d %H:%M:%S",
	"%Y-%m-%d %H:%M",
	"%Y-%m-%dT%H:%M:%S",
	"%Y-%m-%dT%H:%M",
	"%d/%m/%Y %H:%M:%S",
	"%d/%m/%Y %H:%M",
	"%d-%m-%Y %H:%M:%S",
	"%d-%m-%Y %H:%M",
	"%d.%m.%Y %H:%M",
)


def parse_datetime(value) -> datetime | None:
	"""Parse a logger timestamp (Gregorian). Date-only values become midnight."""
	if value is None:
		return None
	if isinstance(value, datetime):
		return value.replace(tzinfo=None)
	if isinstance(value, date):
		return datetime(value.year, value.month, value.day)
	if isinstance(value, int | float) and not isinstance(value, bool):
		if 1 <= value < 2958466:
			return datetime(1899, 12, 30) + timedelta(days=float(value))
		raise DateParseError(f"Unrecognised date-time number {value}")
	text = str(value).strip()
	if not text:
		return None
	text = text.rstrip("Z")
	for fmt in _DT_FORMATS:
		try:
			return datetime.strptime(text, fmt)
		except ValueError:
			continue
	try:
		return datetime.fromisoformat(text).replace(tzinfo=None)
	except ValueError:
		pass
	d = parse_date(text)
	return datetime(d.year, d.month, d.day) if d else None

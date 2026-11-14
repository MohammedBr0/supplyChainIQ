"""Deterministic document field extraction (no AI, no OCR).

Text comes from the PDF text layer (or a .txt file). Fields are proposed by
labelled patterns, each with a confidence and the snippet it came from.
Identifiers with check digits are validated:

* container numbers: ISO 6346 (owner code + U/J/Z + 6 digits + check digit)
* air waybills: 3-digit airline prefix + 7-digit serial + check digit (serial mod 7)

Nothing is applied until a person confirms it.
"""

import io
import re

from supplychain_iq.intake.dates import DateParseError, parse_date

INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")
CURRENCIES = ("USD", "EUR", "ETB", "GBP", "CNY", "INR", "AED", "JPY", "KES", "CHF")
SNIPPET = 45


# ---------------------------------------------------------------- identifiers


def iso6346_valid(code: str) -> bool:
	code = (code or "").replace(" ", "").upper()
	if not re.fullmatch(r"[A-Z]{3}[UJZ]\d{7}", code):
		return False
	values, v = {}, 10
	for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
		if v % 11 == 0:
			v += 1
		values[ch] = v
		v += 1
	total = sum((values[c] if c.isalpha() else int(c)) * (2**i) for i, c in enumerate(code[:10]))
	return total % 11 % 10 == int(code[10])


def awb_valid(awb: str) -> bool:
	digits = re.sub(r"\D", "", awb or "")
	if len(digits) != 11:
		return False
	serial, check = int(digits[3:10]), int(digits[10])
	return serial % 7 == check


def format_awb(awb: str) -> str:
	d = re.sub(r"\D", "", awb)
	return f"{d[:3]}-{d[3:]}"


# ---------------------------------------------------------------- text


def read_pages(content: bytes, filename: str) -> list[str]:
	name = (filename or "").lower()
	if name.endswith(".pdf"):
		if isinstance(content, str):
			content = content.encode("latin-1", errors="replace")
		from pypdf import PdfReader

		reader = PdfReader(io.BytesIO(content))
		return [(page.extract_text() or "") for page in reader.pages]
	if name.endswith((".txt", ".csv")):
		return [content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content]
	raise ValueError("Upload a PDF (with a text layer) or a .txt file.")


def _snippet(text, m):
	start, end = max(0, m.start() - SNIPPET), min(len(text), m.end() + SNIPPET)
	return re.sub(r"\s+", " ", text[start:end]).strip()


def _first(pages, pattern, flags=re.I):
	for p, text in enumerate(pages, start=1):
		m = re.search(pattern, text, flags)
		if m:
			return m, p, text
	return None, None, None


def _date_field(pages, key, label, labels):
	pattern = r"(?:" + "|".join(labels) + r")\s*[:\-]?\s*([0-9]{1,4}[./\- ][0-9A-Za-z]{1,9}[./\- ,]+[0-9]{2,4})"
	m, p, text = _first(pages, pattern)
	if not m:
		return None
	try:
		value = parse_date(m.group(1).strip().replace(",", ""))
	except DateParseError:
		return {"field_key": key, "label": label, "value": m.group(1).strip(), "confidence": "Low", "source_snippet": _snippet(text, m), "page": p}
	return {"field_key": key, "label": label, "value": value.isoformat(), "confidence": "Medium", "source_snippet": _snippet(text, m), "page": p}


def _labelled(pages, key, label, pattern, confidence="Medium", transform=None):
	m, p, text = _first(pages, pattern)
	if not m:
		return None
	value = m.group(1).strip()
	if transform:
		value = transform(value)
	return {"field_key": key, "label": label, "value": value, "confidence": confidence, "source_snippet": _snippet(text, m), "page": p}


def _incoterm(pages):
	m, p, text = _first(pages, r"\b(" + "|".join(INCOTERMS) + r")\b(?:\s+[A-Z][A-Za-z]+)?", flags=0)
	if m:
		return {"field_key": "incoterm", "label": "Incoterm", "value": m.group(1), "confidence": "Medium", "source_snippet": _snippet(text, m), "page": p}
	return None


def _total(pages):
	cur = "|".join(CURRENCIES)
	m, p, text = _first(pages, r"(?:grand\s+total|invoice\s+total|total\s+amount|amount\s+due|total)\s*(?:value)?\s*[:\-]?\s*(" + cur + r")?\s*([0-9][0-9,]*\.[0-9]{2})")
	if not m:
		return []
	out = [{"field_key": "cargo_value", "label": "Invoice total", "value": m.group(2).replace(",", ""), "confidence": "Medium", "source_snippet": _snippet(text, m), "page": p}]
	currency = m.group(1)
	if not currency:
		mc, pc, tc = _first(pages, r"\b(" + cur + r")\b", flags=0)
		if mc:
			out.append({"field_key": "currency", "label": "Currency", "value": mc.group(1), "confidence": "Low", "source_snippet": _snippet(tc, mc), "page": pc})
	else:
		out.append({"field_key": "currency", "label": "Currency", "value": currency.upper(), "confidence": "High", "source_snippet": _snippet(text, m), "page": p})
	return out


def _containers(pages):
	found = []
	for p, text in enumerate(pages, start=1):
		for m in re.finditer(r"\b([A-Z]{3}[UJZ])\s?(\d{6})\s?-?\s?(\d)\b", text):
			code = "".join(m.groups())
			if code not in [f["value"] for f in found]:
				ok = iso6346_valid(code)
				found.append({"field_key": "container", "label": "Container no." + ("" if ok else " (check digit FAILS)"),
					"value": code, "confidence": "High" if ok else "Low", "source_snippet": _snippet(text, m), "page": p})
	return found


def _awb(pages):
	for p, text in enumerate(pages, start=1):
		for m in re.finditer(r"\b(\d{3})[\s\-]?(\d{4})\s?(\d{4})\b", text):
			raw = "".join(m.groups())
			if awb_valid(raw):
				return {"field_key": "awb_bl_number", "label": "Air waybill no.", "value": format_awb(raw), "confidence": "High", "source_snippet": _snippet(text, m), "page": p}
	m, p, text = _first(pages, r"(?:AWB|air\s*waybill)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([0-9]{3}[\s\-]?[0-9]{4}\s?[0-9]{4})")
	if m:
		return {"field_key": "awb_bl_number", "label": "Air waybill no. (check digit FAILS)", "value": m.group(1), "confidence": "Low", "source_snippet": _snippet(text, m), "page": p}
	return None


def extract(document_type: str, pages: list[str]) -> list[dict]:
	f = []
	add = lambda x: f.extend(x if isinstance(x, list) else ([x] if x else []))  # noqa: E731
	ports = [
		_labelled(pages, "origin", "Port of loading", r"port\s+of\s+loading\s*[:\-]?\s*([A-Za-z][A-Za-z ,.\-]{2,40}?)(?:\n|\s{2,}|$)"),
		_labelled(pages, "destination", "Port of discharge / destination", r"(?:port\s+of\s+discharge|final\s+destination|place\s+of\s+delivery)\s*[:\-]?\s*([A-Za-z][A-Za-z ,.\-]{2,40}?)(?:\n|\s{2,}|$)"),
	]
	if document_type == "Commercial Invoice":
		add(_labelled(pages, "invoice_number", "Invoice no.", r"invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,30})"))
		add(_date_field(pages, "invoice_date", "Invoice date", ["invoice\\s+date", "date\\s+of\\s+issue", "date"]))
		add(_total(pages))
		add(_incoterm(pages))
		add(ports)
	elif document_type == "Packing List":
		add(_labelled(pages, "packages", "Number of packages", r"(?:total\s+)?(?:no\.?\s+of\s+)?(?:packages|cartons|pkgs|boxes)\s*[:\-]?\s*([0-9][0-9,]*)", transform=lambda v: v.replace(",", "")))
		add(_labelled(pages, "gross_weight", "Gross weight (kg)", r"gross\s+weight\s*[:\-]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:kgs?|kilograms?)", transform=lambda v: v.replace(",", "")))
		add(_labelled(pages, "net_weight", "Net weight (kg)", r"net\s+weight\s*[:\-]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:kgs?|kilograms?)", transform=lambda v: v.replace(",", "")))
		add(_containers(pages))
	elif document_type == "Bill of Lading":
		add(_labelled(pages, "awb_bl_number", "B/L no.", r"(?:b/?l|bill\s+of\s+lading)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{5,24})"))
		add(_date_field(pages, "actual_etd", "Shipped on board", ["shipped\\s+on\\s+board(?:\\s+date)?", "on\\s+board\\s+date", "date\\s+of\\s+shipment"]))
		add(_labelled(pages, "vessel", "Vessel / voyage", r"(?:vessel|ocean\s+vessel)\s*(?:/\s*voy(?:age)?\.?)?\s*[:\-]?\s*([A-Z0-9][A-Za-z0-9 .\-/]{2,40}?)(?:\n|\s{2,}|$)"))
		add(_containers(pages))
		add(ports)
	elif document_type == "Air Waybill":
		add(_awb(pages))
		add(_date_field(pages, "actual_etd", "Flight / execution date", ["executed\\s+on", "flight\\s+date", "date\\s+of\\s+issue"]))
		add(ports)
	elif document_type == "Duty-Free Privilege Approval":
		add(_labelled(pages, "reference_no", "Authority reference", r"(?:our\s+)?ref(?:erence)?\.?\s*(?:no\.?)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-.]{3,30})"))
		add(_date_field(pages, "effective_date", "Effective / issue date", ["effective\\s+(?:from|date)", "date\\s+of\\s+issue", "issued\\s+on", "date"]))
		add(_date_field(pages, "expiry_date", "Expiry / valid until", ["valid\\s+until", "expiry\\s+date", "expires\\s+on", "valid\\s+till"]))
		add(_labelled(pages, "authority", "Issuing authority", r"((?:ministry|authority|commission|agency)\s+of\s+[A-Za-z ,]{3,60}?)(?:\n|\.|$)", confidence="Low"))
	return f

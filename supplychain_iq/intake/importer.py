"""Staged spreadsheet import: parse -> map -> validate -> preview -> confirm.

Nothing is written to live records until an authorized user confirms a batch
that validated without errors. Confirmation re-reads and re-validates the
source file, so what gets imported is exactly what the preview showed.
"""

import csv
import io
import json
import re

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from supplychain_iq.entitlements import check_usage_limit, get_entitlements
from supplychain_iq.intake.dates import DateParseError, parse_date
from supplychain_iq.intake.mapping import detect_mapping, missing_required, validate_mapping

MAX_ROWS_HARD_LIMIT = 20000

UOM_SYNONYMS = {
	"PCS": "EA", "PC": "EA", "EACH": "EA", "PIECE": "EA", "PIECES": "EA", "NOS": "EA", "NO": "EA", "UNIT": "EA", "UNITS": "EA",
	"KGS": "KG", "KILOGRAM": "KG", "KILOGRAMS": "KG",
	"LTR": "L", "LITRE": "L", "LITER": "L", "LITRES": "L", "LITERS": "L",
	"CTN": "CARTON", "CARTONS": "CARTON", "BOXES": "BOX", "VIALS": "VIAL", "BOTTLES": "BOTTLE",
	"MT": "TONNE", "TON": "TONNE", "TONS": "TONNE", "TONNES": "TONNE",
}

MODE_SYNONYMS = {
	"sea": "Sea", "ocean": "Sea", "vessel": "Sea", "fcl": "Sea", "lcl": "Sea",
	"air": "Air", "airfreight": "Air", "air_freight": "Air",
	"rail": "Rail", "train": "Rail",
	"road": "Road", "truck": "Road", "trucking": "Road",
	"multimodal": "Multimodal", "multi_modal": "Multimodal", "intermodal": "Multimodal",
}

SHIPMENT_STATUSES = ("Planned", "Booked", "In Transit", "At Port", "Customs Clearance", "Released", "Delivered", "Closed", "Cancelled")
INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")


# ---------------------------------------------------------------- file reading


def read_table(content: bytes, filename: str) -> tuple[list, list[list]]:
	"""Return (headers, rows) from CSV or XLSX bytes. Blank rows are dropped."""
	name = (filename or "").lower()
	if name.endswith(".xlsx"):
		from openpyxl import load_workbook

		wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
		ws = wb.worksheets[0]
		raw = [list(r) for r in ws.iter_rows(values_only=True)]
	elif name.endswith(".csv") or name.endswith(".txt"):
		text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
		raw = list(csv.reader(io.StringIO(text)))
	else:
		frappe.throw(_("Unsupported file type. Upload a .csv or .xlsx file."))

	raw = [r for r in raw if any(c not in (None, "") and str(c).strip() for c in r)]
	if not raw:
		frappe.throw(_("The file is empty."))
	headers = [str(h).strip() if h is not None else "" for h in raw[0]]
	rows = [list(r) + [None] * (len(headers) - len(r)) for r in raw[1:]]
	return headers, rows


def get_file_content(file_url: str) -> tuple[bytes, str]:
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	return file_doc.get_content(), file_doc.file_name


# ---------------------------------------------------------------- value helpers


def clean(value):
	if value is None:
		return None
	if isinstance(value, str):
		value = value.strip()
		return value or None
	return value


def to_number(value):
	value = clean(value)
	if value is None:
		return None
	if isinstance(value, int | float) and not isinstance(value, bool):
		return float(value)
	text = str(value).replace(",", "").replace(" ", "")
	try:
		return float(text)
	except ValueError:
		raise ValueError(f"'{value}' is not a number")


def normalize_uom(value) -> str | None:
	value = clean(value)
	if value is None:
		return None
	key = re.sub(r"[^A-Z]", "", str(value).upper())
	return UOM_SYNONYMS.get(key, key or None)


# ---------------------------------------------------------------- row validation


class RowResult:
	def __init__(self, number):
		self.number = number
		self.errors, self.warnings, self.data = [], [], {}

	@property
	def status(self):
		return "Error" if self.errors else ("Warning" if self.warnings else "Valid")


def _date(row, field, value, calendar):
	try:
		return parse_date(value, calendar)
	except DateParseError as e:
		row.errors.append(f"{field}: {e}")
		return None


class Validator:
	def __init__(self, batch):
		self.batch = batch
		self.org = batch.organization
		self.calendar = batch.date_calendar or "Gregorian"
		self.create_masters = bool(batch.create_missing_masters)
		self.today = frappe.utils.getdate(today())
		self.new_masters = {"IQ Warehouse": set(), "IQ Item": set(), "IQ Supplier": set()}

	# lookups are scoped to the batch organization explicitly
	def find(self, doctype, field, value):
		if value is None:
			return None
		rows = frappe.db.sql(
			f"select name from `tab{doctype}` where `organization`=%s and lower(`{field}`)=lower(%s) limit 1",
			(self.org, str(value)),
		)
		return rows[0][0] if rows else None

	def find_warehouse(self, value):
		return self.find("IQ Warehouse", "name", value) or self.find("IQ Warehouse", "warehouse_name", value)

	def validate_stock(self, number, rec, seen):
		row = RowResult(number)
		d = row.data
		d["item_code"] = clean(rec.get("item_code"))
		d["item_name"] = clean(rec.get("item_name"))
		d["warehouse"] = clean(rec.get("warehouse"))
		d["batch_no"] = clean(rec.get("batch_no"))
		d["uom"] = normalize_uom(rec.get("uom"))
		for f in ("item_code", "warehouse"):
			if d[f] is None:
				row.errors.append(f"{f} is required")
		if d["item_code"] is not None:
			d["item_code"] = str(d["item_code"])
		if d["batch_no"] is not None:
			d["batch_no"] = str(d["batch_no"])

		for f in ("quantity", "avg_monthly_consumption"):
			try:
				d[f] = to_number(rec.get(f))
			except ValueError as e:
				row.errors.append(f"{f}: {e}")
				d[f] = None
		if d["quantity"] is None and not any(e.startswith("quantity") for e in row.errors):
			row.errors.append("quantity is required")
		elif d["quantity"] is not None:
			if d["quantity"] < 0:
				row.errors.append("quantity cannot be negative")
			elif d["quantity"] > 1e9:
				row.warnings.append("quantity is unusually large - please check")
		if d["avg_monthly_consumption"] is not None and d["avg_monthly_consumption"] < 0:
			row.errors.append("avg_monthly_consumption cannot be negative")

		expiry = _date(row, "expiry_date", rec.get("expiry_date"), self.calendar)
		d["expiry_date"] = expiry.isoformat() if expiry else None
		if expiry and expiry < self.today:
			row.warnings.append(f"batch already expired on {expiry.isoformat()}")

		if d["warehouse"]:
			wh = self.find_warehouse(d["warehouse"])
			if wh:
				d["warehouse_id"] = wh
			elif self.create_masters:
				self.new_masters["IQ Warehouse"].add(d["warehouse"].lower())
				row.warnings.append(f"warehouse '{d['warehouse']}' will be created")
			else:
				row.errors.append(f"warehouse '{d['warehouse']}' not found")

		if d["item_code"]:
			item = self.find("IQ Item", "item_code", d["item_code"])
			if item:
				d["item_id"] = item
				item_uom = frappe.db.get_value("IQ Item", item, "uom")
				if d["uom"] and normalize_uom(item_uom) != d["uom"]:
					row.errors.append(f"UOM '{d['uom']}' does not match item UOM '{item_uom}'")
			elif self.create_masters:
				if not d["uom"]:
					row.errors.append("uom is required to create a new item")
				else:
					self.new_masters["IQ Item"].add(d["item_code"].lower())
					row.warnings.append(f"item '{d['item_code']}' will be created")
			else:
				row.errors.append(f"item '{d['item_code']}' not found")

		key = (str(d["item_code"]).lower(), str(d["warehouse"]).lower(), str(d["batch_no"] or "").lower())
		if d["item_code"] and d["warehouse"]:
			if key in seen:
				row.errors.append(f"duplicate of row {seen[key]} (same item, warehouse and batch)")
			else:
				seen[key] = number
		return row

	def validate_shipment(self, number, rec, seen):
		row = RowResult(number)
		d = row.data
		for f in ("shipment_title", "awb_bl_number", "supplier", "po_reference", "origin", "destination", "uom"):
			v = clean(rec.get(f))
			d[f] = str(v) if v is not None else None
		for f in ("shipment_title", "origin", "destination"):
			if not d[f]:
				row.errors.append(f"{f} is required")

		mode = clean(rec.get("transport_mode"))
		key = re.sub(r"[^a-z]+", "_", str(mode or "").lower()).strip("_")
		d["transport_mode"] = MODE_SYNONYMS.get(key)
		if not mode:
			row.errors.append("transport_mode is required")
		elif not d["transport_mode"]:
			row.errors.append(f"transport_mode '{mode}' is not one of Sea, Air, Rail, Road, Multimodal")

		for f in ("planned_etd", "planned_eta", "actual_etd", "actual_eta"):
			v = _date(row, f, rec.get(f), self.calendar)
			d[f] = v.isoformat() if v else None
		if not d["planned_eta"] and not any(e.startswith("planned_eta") for e in row.errors):
			row.errors.append("planned_eta is required")
		if d["planned_etd"] and d["planned_eta"] and d["planned_eta"] < d["planned_etd"]:
			row.errors.append("planned_eta is before planned_etd")
		if d["actual_etd"] and d["actual_eta"] and d["actual_eta"] < d["actual_etd"]:
			row.errors.append("actual_eta is before actual_etd")

		for f in ("quantity", "cargo_value"):
			try:
				d[f] = to_number(rec.get(f))
			except ValueError as e:
				row.errors.append(f"{f}: {e}")
				d[f] = None
			if d[f] is not None and d[f] < 0:
				row.errors.append(f"{f} cannot be negative")

		currency = clean(rec.get("currency"))
		d["currency"] = str(currency).upper() if currency else None
		if d["currency"] and not re.fullmatch(r"[A-Z]{3}", d["currency"]):
			row.errors.append(f"currency '{currency}' must be a 3-letter ISO code")

		incoterm = clean(rec.get("incoterm"))
		d["incoterm"] = str(incoterm).upper()[:3] if incoterm else None
		if d["incoterm"] and d["incoterm"] not in INCOTERMS:
			row.warnings.append(f"incoterm '{incoterm}' not recognised - left blank")
			d["incoterm"] = None

		status = clean(rec.get("status"))
		match = next((s for s in SHIPMENT_STATUSES if status and s.lower() == str(status).lower()), None)
		if status and not match:
			row.warnings.append(f"status '{status}' not recognised - set to Planned")
		d["status"] = match or "Planned"

		if d["supplier"]:
			sup = self.find("IQ Supplier", "supplier_name", d["supplier"])
			if sup:
				d["supplier_id"] = sup
			elif self.create_masters:
				self.new_masters["IQ Supplier"].add(d["supplier"].lower())
				row.warnings.append(f"supplier '{d['supplier']}' will be created")
			else:
				row.errors.append(f"supplier '{d['supplier']}' not found")

		if d["awb_bl_number"]:
			awb = d["awb_bl_number"].lower()
			if awb in seen:
				row.errors.append(f"duplicate AWB/BL of row {seen[awb]}")
			else:
				seen[awb] = number
			existing = self.find("IQ Shipment", "awb_bl_number", d["awb_bl_number"])
			if existing:
				d["existing_shipment"] = existing
				row.warnings.append(f"will update existing shipment {existing}")
		return row


# ---------------------------------------------------------------- pipeline


def run_validation(batch) -> dict:
	"""Parse and validate the batch file. Returns a result dict; does not write records."""
	content, filename = get_file_content(batch.source_file)
	headers, raw_rows = read_table(content, filename)

	batch_errors, notes, fuzzy = [], [], []
	if batch.column_mapping:
		try:
			mapping = json.loads(batch.column_mapping)
		except ValueError:
			frappe.throw(_("Column Mapping is not valid JSON."))
		unknown = [h for h in mapping if h not in headers]
		if unknown:
			batch_errors.append(f"Mapping refers to columns not in the file: {', '.join(unknown)}")
		for h in headers:
			mapping.setdefault(h, None)
		batch_errors += validate_mapping(mapping, batch.import_type)
		_auto, _notes, auto_fuzzy = detect_mapping(headers, batch.import_type)
		# a fuzzy guess the user has not changed still needs confirmation
		fuzzy = [h for h in auto_fuzzy if mapping.get(h) == _auto.get(h)]
		notes = ["Using the saved column mapping."]
	else:
		mapping, notes, fuzzy = detect_mapping(headers, batch.import_type)

	missing = missing_required(mapping, batch.import_type)
	if missing:
		batch_errors.append(f"Required fields not mapped: {', '.join(missing)}")

	limit = get_entitlements(batch.organization).max_import_rows or MAX_ROWS_HARD_LIMIT
	if len(raw_rows) > min(limit, MAX_ROWS_HARD_LIMIT):
		batch_errors.append(f"The file has {len(raw_rows)} rows; your package allows {limit} per import.")

	validator = Validator(batch)
	results = []
	if not batch_errors:
		seen = {}
		fn = validator.validate_stock if batch.import_type == "Existing Stock" else validator.validate_shipment
		for i, raw in enumerate(raw_rows, start=2):  # row 1 is the header
			rec = {mapping[h]: v for h, v in zip(headers, raw, strict=False) if mapping.get(h)}
			results.append(fn(i, rec, seen))

		ent = get_entitlements(batch.organization)
		new_wh = len(validator.new_masters["IQ Warehouse"])
		if new_wh and ent.max_warehouses:
			have = frappe.db.count("IQ Warehouse", {"organization": batch.organization})
			if have + new_wh > ent.max_warehouses:
				batch_errors.append(
					f"Creating {new_wh} warehouses would exceed your package limit of {ent.max_warehouses}."
				)
		if batch.import_type == "Inbound Shipments" and ent.max_shipments:
			new_shp = sum(1 for r in results if not r.errors and not r.data.get("existing_shipment"))
			active = frappe.db.count(
				"IQ Shipment",
				{"organization": batch.organization, "status": ["not in", ["Closed", "Cancelled"]]},
			)
			if active + new_shp > ent.max_shipments:
				batch_errors.append(
					f"Importing {new_shp} new shipments would exceed your package limit of {ent.max_shipments} active shipments."
				)

	return {
		"headers": headers,
		"mapping": mapping,
		"notes": notes,
		"fuzzy": fuzzy,
		"batch_errors": batch_errors,
		"rows": results,
	}


def apply_validation(batch, result):
	batch.column_mapping = json.dumps(result["mapping"], indent=1, ensure_ascii=False)
	batch.mapping_notes = "\n".join(result["notes"])
	batch.set("rows", [])
	for r in result["rows"]:
		batch.append(
			"rows",
			{
				"row_number": r.number,
				"row_status": r.status,
				"messages": "; ".join(r.errors + r.warnings),
				"data": json.dumps(r.data, ensure_ascii=False, default=str),
			},
		)
	rows = result["rows"]
	batch.total_rows = len(rows)
	batch.error_rows = sum(1 for r in rows if r.status == "Error")
	batch.warning_rows = sum(1 for r in rows if r.status == "Warning")
	batch.valid_rows = sum(1 for r in rows if r.status == "Valid")
	summary = list(result["batch_errors"])
	if result["fuzzy"]:
		summary.append("Some columns were mapped by similarity: tick Mapping Confirmed after checking them.")
	summary.append(
		f"{batch.total_rows} rows: {batch.valid_rows} valid, {batch.warning_rows} with warnings, {batch.error_rows} with errors."
	)
	batch.validation_summary = "\n".join(summary)
	batch.status = "Has Errors" if (result["batch_errors"] or batch.error_rows or not rows) else "Validated"
	batch.flags.iq_fuzzy_columns = result["fuzzy"]


def confirm_import(batch):
	"""Write validated rows to live records. Runs in one transaction."""
	if batch.status == "Imported":
		frappe.throw(_("This batch has already been imported."))
	result = run_validation(batch)
	apply_validation(batch, result)
	if batch.status != "Validated":
		batch.save()
		frappe.throw(_("The file no longer validates cleanly. Review the preview and fix the errors."))
	if result["fuzzy"] and not batch.mapping_confirmed:
		frappe.throw(_("Some columns were mapped by similarity. Check the mapping and tick Mapping Confirmed."))

	writer = StockWriter(batch) if batch.import_type == "Existing Stock" else ShipmentWriter(batch)
	created = updated = 0
	for r in result["rows"]:
		c, u = writer.write(r.data)
		created += c
		updated += u

	batch.status = "Imported"
	batch.imported_by = frappe.session.user
	batch.imported_on = now_datetime()
	batch.records_created = created
	batch.records_updated = updated
	batch.flags.iq_allow_status_change = True
	batch.save()
	return {"created": created, "updated": updated}


class _Writer:
	def __init__(self, batch):
		self.batch = batch
		self.org = batch.organization
		self.cache = {}

	def ensure(self, doctype, lookup_field, value, values):
		key = (doctype, str(value).lower())
		if key in self.cache:
			return self.cache[key]
		rows = frappe.db.sql(
			f"select name from `tab{doctype}` where `organization`=%s and lower(`{lookup_field}`)=lower(%s) limit 1",
			(self.org, str(value)),
		)
		if rows:
			name = rows[0][0]
		else:
			doc = frappe.get_doc({"doctype": doctype, "organization": self.org, **values})
			doc.insert()
			name = doc.name
		self.cache[key] = name
		return name


class StockWriter(_Writer):
	def write(self, d):
		warehouse = d.get("warehouse_id") or self.ensure(
			"IQ Warehouse", "warehouse_name", d["warehouse"], {"warehouse_name": d["warehouse"]}
		)
		item = d.get("item_id") or self.ensure(
			"IQ Item",
			"item_code",
			d["item_code"],
			{"item_code": d["item_code"], "item_name": d.get("item_name") or d["item_code"], "uom": d["uom"]},
		)
		existing = frappe.db.get_value(
			"IQ Stock Balance",
			{"organization": self.org, "item": item, "warehouse": warehouse, "batch_no": d.get("batch_no") or ""},
		)
		if not existing and not d.get("batch_no"):
			existing = frappe.db.get_value(
				"IQ Stock Balance",
				{"organization": self.org, "item": item, "warehouse": warehouse, "batch_no": ["is", "not set"]},
			)
		values = {
			"quantity": d["quantity"],
			"expiry_date": d.get("expiry_date"),
			"avg_monthly_consumption": d.get("avg_monthly_consumption"),
			"source_import": self.batch.name,
		}
		if existing:
			doc = frappe.get_doc("IQ Stock Balance", existing)
			doc.update(values)
			doc.save()
			return 0, 1
		doc = frappe.get_doc(
			{
				"doctype": "IQ Stock Balance",
				"organization": self.org,
				"item": item,
				"warehouse": warehouse,
				"batch_no": d.get("batch_no"),
				**values,
			}
		)
		doc.insert()
		return 1, 0


class ShipmentWriter(_Writer):
	FIELDS = (
		"shipment_title", "awb_bl_number", "po_reference", "transport_mode", "origin", "destination",
		"planned_etd", "planned_eta", "actual_etd", "actual_eta", "quantity", "uom", "cargo_value",
		"currency", "incoterm", "status",
	)

	def write(self, d):
		values = {f: d.get(f) for f in self.FIELDS if d.get(f) is not None}
		if d.get("supplier"):
			values["supplier"] = d.get("supplier_id") or self.ensure(
				"IQ Supplier", "supplier_name", d["supplier"], {"supplier_name": d["supplier"]}
			)
		values["source_import"] = self.batch.name
		if d.get("existing_shipment"):
			doc = frappe.get_doc("IQ Shipment", d["existing_shipment"])
			doc.update(values)
			doc.save()
			return 0, 1
		doc = frappe.get_doc({"doctype": "IQ Shipment", "organization": self.org, **values})
		doc.insert()
		return 1, 0

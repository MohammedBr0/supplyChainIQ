"""Column mapping from customer spreadsheets to IQ canonical fields.

Mapping is deterministic: exact synonym matches are trusted, similarity matches
are applied but flagged so the user must confirm them before import.
"""

import difflib
import re

SIMILARITY_CUTOFF = 0.8


def normalize_header(header) -> str:
	text = str(header or "").strip().lower()
	text = re.sub(r"[^a-z0-9]+", "_", text)
	return text.strip("_")


# canonical field -> (required, synonyms)
SCHEMAS = {
	"Existing Stock": {
		"item_code": (True, ["item_code", "item", "sku", "product_code", "material", "material_code", "item_no", "code"]),
		"item_name": (False, ["item_name", "description", "item_description", "product", "product_name", "name"]),
		"uom": (False, ["uom", "unit", "unit_of_measure", "units", "unit_of_issue"]),
		"warehouse": (True, ["warehouse", "store", "location", "warehouse_name", "site", "depot"]),
		"quantity": (True, ["quantity", "qty", "balance", "stock", "on_hand", "quantity_on_hand", "soh", "stock_on_hand", "closing_balance"]),
		"batch_no": (False, ["batch_no", "batch", "lot", "lot_no", "batch_number", "lot_number"]),
		"expiry_date": (False, ["expiry_date", "expiry", "exp_date", "expiration_date", "best_before", "expires"]),
		"avg_monthly_consumption": (False, ["avg_monthly_consumption", "amc", "monthly_consumption", "average_monthly_consumption", "avg_consumption", "consumption"]),
	},
	"Inbound Shipments": {
		"shipment_title": (True, ["shipment_title", "commodity", "description", "cargo", "goods", "cargo_description"]),
		"awb_bl_number": (False, ["awb_bl_number", "awb", "bl", "bl_number", "awb_number", "bill_of_lading", "awb_bl", "tracking_number"]),
		"supplier": (False, ["supplier", "vendor", "supplier_name", "vendor_name", "shipper"]),
		"po_reference": (False, ["po_reference", "po", "po_number", "purchase_order", "po_no", "order_number"]),
		"transport_mode": (True, ["transport_mode", "mode", "mode_of_transport", "transport"]),
		"origin": (True, ["origin", "from", "port_of_loading", "pol", "origin_country"]),
		"destination": (True, ["destination", "to", "final_destination", "delivery_place"]),
		"planned_etd": (False, ["planned_etd", "etd", "departure_date", "planned_departure"]),
		"planned_eta": (True, ["planned_eta", "eta", "arrival_date", "expected_arrival", "planned_arrival"]),
		"actual_etd": (False, ["actual_etd", "atd", "actual_departure"]),
		"actual_eta": (False, ["actual_eta", "ata", "actual_arrival"]),
		"quantity": (False, ["quantity", "qty", "packages", "pieces"]),
		"uom": (False, ["uom", "unit", "unit_of_measure"]),
		"cargo_value": (False, ["cargo_value", "value", "invoice_value", "amount"]),
		"currency": (False, ["currency", "curr", "ccy"]),
		"incoterm": (False, ["incoterm", "incoterms", "terms"]),
		"status": (False, ["status", "shipment_status"]),
	},
}


def required_fields(import_type: str) -> list[str]:
	return [f for f, (req, _syn) in SCHEMAS[import_type].items() if req]


def detect_mapping(headers: list, import_type: str) -> tuple[dict, list[str], list[str]]:
	"""Return (mapping, notes, fuzzy_columns).

	mapping: {original header: canonical field or None (ignored)}.
	"""
	schema = SCHEMAS[import_type]
	synonyms = {}
	for field, (_req, syns) in schema.items():
		for s in syns:
			synonyms.setdefault(s, field)

	mapping, notes, fuzzy, used = {}, [], [], set()
	# pass 1: exact synonym matches
	for header in headers:
		key = normalize_header(header)
		field = synonyms.get(key)
		if field and field not in used:
			mapping[header] = field
			used.add(field)
		else:
			mapping[header] = None
	# pass 2: similarity for still-unmapped headers
	for header in headers:
		if mapping[header]:
			continue
		key = normalize_header(header)
		if not key:
			continue
		match = difflib.get_close_matches(key, list(synonyms), n=1, cutoff=SIMILARITY_CUTOFF)
		if match and synonyms[match[0]] not in used:
			field = synonyms[match[0]]
			mapping[header] = field
			used.add(field)
			fuzzy.append(header)
			notes.append(f"'{header}' mapped to {field} by similarity - please confirm.")
	for header, field in mapping.items():
		if field is None:
			notes.append(f"Column '{header}' is not used.")
	return mapping, notes, fuzzy


def missing_required(mapping: dict, import_type: str) -> list[str]:
	mapped = {v for v in mapping.values() if v}
	return [f for f in required_fields(import_type) if f not in mapped]


def validate_mapping(mapping: dict, import_type: str) -> list[str]:
	"""Errors in a user-edited mapping."""
	errors = []
	schema = SCHEMAS[import_type]
	seen = {}
	for header, field in mapping.items():
		if not field:
			continue
		if field not in schema:
			errors.append(f"Column '{header}' is mapped to unknown field '{field}'.")
		elif field in seen:
			errors.append(f"Field '{field}' is mapped from both '{seen[field]}' and '{header}'.")
		else:
			seen[field] = header
	return errors

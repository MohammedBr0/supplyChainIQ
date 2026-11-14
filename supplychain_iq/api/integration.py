"""ERP integration API (token-authenticated, idempotent upserts).

Authenticate as the connection's API user:  Authorization: token <api_key>:<api_secret>

POST /api/method/supplychain_iq.api.integration.upsert_purchase_orders   {"records": [...]}
POST /api/method/supplychain_iq.api.integration.upsert_shipments         {"records": [...]}
POST /api/method/supplychain_iq.api.integration.upsert_stock_counts      {"records": [...]}

Every record carries an ``external_id``; sending the same record again
updates it instead of creating a duplicate. Records are validated with the
same rules as file imports and processed independently: one bad record does
not block the others. Each call is written to the IQ Integration Log.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from supplychain_iq.entitlements import require_module
from supplychain_iq.intake.importer import ShipmentWriter, StockWriter, Validator

MAX_RECORDS = 500
PO_STATUSES = ("Draft", "Confirmed", "Partially Shipped", "Shipped", "Closed", "Cancelled")


def _connection(allow_field):
	user = frappe.session.user
	conn = frappe.db.get_value(
		"IQ Integration Connection", {"integration_user": user, "enabled": 1},
		["name", "organization", "allow_purchase_orders", "allow_shipments", "allow_stock", "create_missing_masters"],
		as_dict=True,
	)
	if not conn:
		frappe.throw(_("This API user is not linked to an enabled integration connection."), frappe.PermissionError)
	require_module(conn.organization, "ERP Integration")
	if not conn.get(allow_field):
		frappe.throw(_("This connection is not allowed to send these records."), frappe.PermissionError)
	return conn


def _records(records):
	records = json.loads(records) if isinstance(records, str) else records
	if not isinstance(records, list):
		frappe.throw(_("'records' must be a list."))
	if len(records) > MAX_RECORDS:
		frappe.throw(_("Send at most {0} records per call.").format(MAX_RECORDS))
	return records


def _run(conn, endpoint, records, handle):
	created = updated = 0
	errors = []
	for i, rec in enumerate(records):
		ext = str((rec or {}).get("external_id") or "").strip()
		if not ext:
			errors.append({"index": i, "external_id": None, "error": "external_id is required"})
			continue
		frappe.db.savepoint("iq_integration_record")
		try:
			c, u = handle(rec, ext)
			created += c
			updated += u
		except Exception as e:
			frappe.db.rollback(save_point="iq_integration_record")
			msg = frappe.utils.strip_html(str(e)) or e.__class__.__name__
			errors.append({"index": i, "external_id": ext, "error": msg[:500]})
			frappe.clear_messages()
	status = "Success" if not errors else ("Failed" if not (created or updated) else "Partial")
	log = frappe.get_doc({
		"doctype": "IQ Integration Log", "organization": conn.organization, "connection": conn.name,
		"endpoint": endpoint, "status": status, "received": len(records), "created_count": created,
		"updated_count": updated, "error_count": len(errors), "errors": json.dumps(errors, indent=1) if errors else None,
	})
	log.flags.ignore_permissions = True
	log.insert(ignore_links=True)
	frappe.db.set_value("IQ Integration Connection", conn.name, "last_used_on", now_datetime(), update_modified=False)
	return {"status": status, "received": len(records), "created": created, "updated": updated, "errors": errors, "log": log.name}


def _mark(doctype, name, conn, ext, action):
	frappe.db.set_value(doctype, name, {"external_id": ext, "external_system": conn.name}, update_modified=False)
	from supplychain_iq import audit

	audit.integration_action(frappe.get_doc(doctype, name), f"{action} via integration {conn.name} (external id {ext})")


@frappe.whitelist(methods=["POST"])
def upsert_purchase_orders(records):
	conn = _connection("allow_purchase_orders")
	require_module(conn.organization, "Procurement Intelligence")

	def handle(rec, ext):
		org = conn.organization
		po_number = str(rec.get("po_number") or "").strip()
		supplier_name = str(rec.get("supplier") or "").strip()
		if not po_number or not supplier_name:
			raise frappe.ValidationError("po_number and supplier are required")
		supplier = frappe.db.get_value("IQ Supplier", {"organization": org, "supplier_name": supplier_name})
		if not supplier:
			if not conn.create_missing_masters:
				raise frappe.ValidationError(f"supplier '{supplier_name}' not found")
			s = frappe.get_doc({"doctype": "IQ Supplier", "organization": org, "supplier_name": supplier_name})
			s.flags.ignore_permissions = True
			s.insert()
			supplier = s.name
		status = rec.get("status") or "Confirmed"
		if status not in PO_STATUSES:
			raise frappe.ValidationError(f"status '{status}' is not one of {', '.join(PO_STATUSES)}")
		values = {"po_number": po_number, "supplier": supplier, "status": status,
			"currency": (rec.get("currency") or "USD").upper(), "total_value": flt(rec.get("total_value")) or None}
		for f in ("order_date", "expected_ship_date"):
			if rec.get(f):
				values[f] = getdate(rec[f])
		name = frappe.db.get_value("IQ Purchase Order", {"organization": org, "external_id": ext}) or frappe.db.get_value(
			"IQ Purchase Order", {"organization": org, "po_number": po_number})
		doc = frappe.get_doc("IQ Purchase Order", name) if name else frappe.new_doc("IQ Purchase Order")
		doc.update({"organization": org, **values})
		doc.flags.ignore_permissions = True
		doc.save()
		_mark("IQ Purchase Order", doc.name, conn, ext, "updated" if name else "created")
		return (0, 1) if name else (1, 0)

	return _run(conn, "upsert_purchase_orders", _records(records), handle)


def _pseudo_batch(conn):
	return frappe._dict(organization=conn.organization, date_calendar="Gregorian",
		create_missing_masters=conn.create_missing_masters, name=conn.name)


@frappe.whitelist(methods=["POST"])
def upsert_shipments(records):
	conn = _connection("allow_shipments")
	require_module(conn.organization, "Shipment Control Tower")
	batch = _pseudo_batch(conn)
	writer = ShipmentWriter(batch)
	writer.ref_doctype, writer.ignore_permissions = "IQ Integration Connection", True

	def handle(rec, ext):
		row = Validator(batch).validate_shipment(0, rec, {})
		if row.errors:
			raise frappe.ValidationError("; ".join(row.errors))
		existing = frappe.db.get_value("IQ Shipment", {"organization": conn.organization, "external_id": ext})
		if existing:
			row.data["existing_shipment"] = existing
		c, u = writer.write(row.data)
		_mark("IQ Shipment", writer.last_name, conn, ext, "updated" if u else "created")
		return c, u

	return _run(conn, "upsert_shipments", _records(records), handle)


@frappe.whitelist(methods=["POST"])
def upsert_stock_counts(records):
	"""Stock counts per item / warehouse / batch (external_id identifies the count line in the ERP)."""
	conn = _connection("allow_stock")
	require_module(conn.organization, "Inventory Intelligence")
	batch = _pseudo_batch(conn)
	writer = StockWriter(batch)
	writer.ref_doctype, writer.entry_type, writer.ignore_permissions = "IQ Integration Connection", "Stock Count (Integration)", True

	def handle(rec, ext):
		row = Validator(batch).validate_stock(0, rec, {})
		if row.errors:
			raise frappe.ValidationError("; ".join(row.errors))
		return writer.write(row.data)

	return _run(conn, "upsert_stock_counts", _records(records), handle)

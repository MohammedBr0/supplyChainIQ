"""Partner portal API (suppliers and transitors).

Portal users are website users with no desk permissions. Every call here
resolves the caller's portal link (organization + supplier or transitor),
checks that the requested record belongs to that link, and then writes with
ignore_permissions. Each change is recorded in the record's timeline.
"""

import base64
import os

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from supplychain_iq.entitlements import has_module, require_module

MODULE = "Partner Portals"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".xls", ".csv", ".docx", ".doc"}

RULES = {
	"Supplier": {
		"fields": ("planned_etd", "actual_etd", "awb_bl_number"),
		"milestones": ("PO Confirmed", "Cargo Ready", "Departed Origin"),
		"documents": ("Commercial Invoice", "Packing List", "Certificate of Origin", "Insurance Certificate", "Bill of Lading", "Air Waybill"),
		"statuses": ("Booked", "In Transit"),
	},
	"Transitor": {
		"fields": ("awb_bl_number", "free_time_start", "actual_eta"),
		"milestones": ("Arrived Port of Discharge", "Arrived Dry Port", "Customs Declaration Lodged", "Customs Released", "Delivered to Warehouse"),
		"documents": ("Bill of Lading", "Air Waybill", "Customs Declaration", "Import Permit", "Other"),
		"statuses": ("In Transit", "At Port", "Customs Clearance", "Released"),
		"cost_categories": ("Customs Clearance", "Port & Handling", "Storage", "Inland Transport", "Demurrage & Detention", "Freight", "Other"),
	},
}
SHIPMENT_FIELDS = ["name", "shipment_title", "status", "transport_mode", "origin", "destination", "awb_bl_number",
	"planned_etd", "actual_etd", "planned_eta", "actual_eta", "po_reference", "purchase_order", "quantity", "uom",
	"incoterm", "missing_documents", "free_time_start", "supplier", "transitor"]


def context() -> frappe._dict:
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)
	link = frappe.db.get_value(
		"IQ Portal User", {"user": user, "is_active": 1},
		["name", "organization", "portal_type", "supplier", "transitor"], as_dict=True,
	)
	if not link:
		frappe.throw(_("Your login is not linked to a partner portal."), frappe.PermissionError)
	require_module(link.organization, MODULE)
	link.partner = link.supplier if link.portal_type == "Supplier" else link.transitor
	link.partner_name = (
		frappe.db.get_value("IQ Supplier", link.supplier, "supplier_name")
		if link.portal_type == "Supplier"
		else frappe.db.get_value("IQ Transitor", link.transitor, "transitor_name")
	)
	link.rules = RULES[link.portal_type]
	return link


def _shipment_filters(ctx):
	f = {"organization": ctx.organization, "status": ["!=", "Cancelled"]}
	f["supplier" if ctx.portal_type == "Supplier" else "transitor"] = ctx.partner
	return f


def _get_shipment(ctx, name):
	f = _shipment_filters(ctx)
	f["name"] = name
	if not frappe.db.exists("IQ Shipment", f):
		frappe.throw(_("Shipment not found."), frappe.PermissionError)
	return frappe.get_doc("IQ Shipment", name)


def _note(doc, ctx, text):
	doc.add_comment("Info", f"{ctx.portal_type} portal ({ctx.partner_name}, {frappe.session.user}): {text}")


def _save(doc):
	doc.flags.ignore_permissions = True
	doc.save()


@frappe.whitelist()
def get_portal_data():
	ctx = context()
	data = {
		"portal_type": ctx.portal_type,
		"partner_name": ctx.partner_name,
		"organization": ctx.organization,
		"rules": ctx.rules,
		"shipments": frappe.get_all("IQ Shipment", filters=_shipment_filters(ctx), fields=SHIPMENT_FIELDS, order_by="planned_eta asc"),
	}
	if ctx.portal_type == "Supplier" and has_module(ctx.organization, "Procurement Intelligence"):
		data["purchase_orders"] = frappe.get_all(
			"IQ Purchase Order",
			filters={"organization": ctx.organization, "supplier": ctx.supplier, "status": ["!=", "Cancelled"]},
			fields=["name", "po_number", "status", "order_date", "expected_ship_date", "currency", "total_value"],
			order_by="order_date desc",
		)
	data["can_submit_costs"] = ctx.portal_type == "Transitor" and has_module(ctx.organization, "Cost Intelligence")
	return data


@frappe.whitelist()
def get_shipment(name: str):
	ctx = context()
	doc = _get_shipment(ctx, name)
	out = {f: doc.get(f) for f in SHIPMENT_FIELDS}
	out["legs"] = [{k: leg.get(k) for k in ("sequence", "mode", "origin", "destination", "carrier", "planned_arrival", "actual_arrival", "status")} for leg in doc.legs]
	out["milestones"] = [{k: m.get(k) for k in ("milestone", "planned_date", "actual_date", "status")} for m in doc.milestones]
	out["documents"] = [{"document_type": d.document_type, "required": d.required, "received": d.received, "has_file": bool(d.attachment)} for d in doc.documents]
	if ctx.portal_type == "Transitor":
		out["my_costs"] = frappe.get_all(
			"IQ Cost Line",
			filters={"shipment": name, "vendor": ctx.partner_name},
			fields=["cost_category", "currency", "amount", "cost_date", "invoice_reference", "cost_status"],
		)
	return out


@frappe.whitelist(methods=["POST"])
def confirm_purchase_order(name: str, expected_ship_date: str | None = None, notes: str | None = None):
	ctx = context()
	if ctx.portal_type != "Supplier":
		frappe.throw(_("Only suppliers can confirm purchase orders."), frappe.PermissionError)
	if not frappe.db.exists("IQ Purchase Order", {"name": name, "organization": ctx.organization, "supplier": ctx.supplier}):
		frappe.throw(_("Purchase order not found."), frappe.PermissionError)
	po = frappe.get_doc("IQ Purchase Order", name)
	if po.status not in ("Draft", "Confirmed"):
		frappe.throw(_("This purchase order can no longer be confirmed (status {0}).").format(po.status))
	po.status = "Confirmed"
	if expected_ship_date:
		po.expected_ship_date = getdate(expected_ship_date)
	_save(po)
	_note(po, ctx, f"confirmed the order" + (f", expected ship date {expected_ship_date}" if expected_ship_date else "") + (f". Note: {notes}" if notes else ""))
	return po.status


@frappe.whitelist(methods=["POST"])
def update_shipment(name: str, values: str | dict):
	ctx = context()
	values = frappe.parse_json(values) if isinstance(values, str) else values
	doc = _get_shipment(ctx, name)
	allowed = set(ctx.rules["fields"]) | {"status"}
	bad = set(values) - allowed
	if bad:
		frappe.throw(_("You cannot change: {0}").format(", ".join(sorted(bad))), frappe.PermissionError)
	changes = []
	for field, value in values.items():
		if field == "status":
			if value not in ctx.rules["statuses"]:
				frappe.throw(_("Status {0} cannot be set from the portal.").format(value))
		elif field in ("planned_etd", "actual_etd", "actual_eta", "free_time_start") and value:
			value = getdate(value)
			if field != "planned_etd" and value > getdate(today()):
				frappe.throw(_("{0} cannot be in the future.").format(doc.meta.get_label(field)))
		if doc.get(field) != value:
			changes.append(f"{doc.meta.get_label(field)}: {doc.get(field) or '-'} -> {value or '-'}")
			doc.set(field, value or None)
	if changes:
		_save(doc)
		_note(doc, ctx, "updated " + "; ".join(changes))
	return len(changes)


@frappe.whitelist(methods=["POST"])
def set_milestone(name: str, milestone: str, actual_date: str):
	ctx = context()
	if milestone not in ctx.rules["milestones"]:
		frappe.throw(_("You cannot update the milestone {0}.").format(milestone), frappe.PermissionError)
	when = getdate(actual_date)
	if when > getdate(today()):
		frappe.throw(_("Milestone dates cannot be in the future."))
	doc = _get_shipment(ctx, name)
	row = next((m for m in doc.milestones if m.milestone == milestone), None) or doc.append("milestones", {"milestone": milestone})
	row.actual_date = when
	_save(doc)
	_note(doc, ctx, f"recorded '{milestone}' on {when}")
	return True


def _attach(doc, ctx, filename, content_b64):
	ext = os.path.splitext(filename or "")[1].lower()
	if ext not in ALLOWED_EXTENSIONS:
		frappe.throw(_("File type {0} is not allowed.").format(ext or "?"))
	try:
		content = base64.b64decode(content_b64.split(",", 1)[-1], validate=True)
	except Exception:
		frappe.throw(_("The file could not be read."))
	if len(content) > MAX_UPLOAD_BYTES:
		frappe.throw(_("Files must be 10 MB or smaller."))
	f = frappe.get_doc({
		"doctype": "File", "file_name": f"{ctx.portal_type.lower()}-{os.path.basename(filename)}", "content": content,
		"is_private": 1, "attached_to_doctype": doc.doctype, "attached_to_name": doc.name,
	})
	f.flags.ignore_permissions = True
	try:
		f.insert()
	except frappe.ValidationError:
		raise
	except Exception:
		frappe.log_error(title="IQ portal upload failed")
		frappe.throw(_("The file could not be processed. Check that it is not damaged and try again."))
	return f.file_url


@frappe.whitelist(methods=["POST"])
def upload_document(name: str, document_type: str, filename: str, content: str):
	ctx = context()
	if document_type not in ctx.rules["documents"]:
		frappe.throw(_("You cannot upload {0} documents.").format(document_type), frappe.PermissionError)
	doc = _get_shipment(ctx, name)
	url = _attach(doc, ctx, filename, content)
	row = next((d for d in doc.documents if d.document_type == document_type and not d.attachment), None)
	if not row:
		row = doc.append("documents", {"document_type": document_type, "required": 0})
	row.attachment, row.received = url, 1
	row.remarks = f"Uploaded via {ctx.portal_type.lower()} portal"
	_save(doc)
	_note(doc, ctx, f"uploaded {document_type} ({filename})")
	return True


@frappe.whitelist(methods=["POST"])
def submit_cost(name: str, cost_category: str, currency: str, amount: float, invoice_reference: str, cost_date: str,
		filename: str, content: str):
	"""Agent charges arrive as estimates for internal verification; they never become actuals by themselves."""
	ctx = context()
	if ctx.portal_type != "Transitor" or cost_category not in ctx.rules["cost_categories"]:
		frappe.throw(_("You cannot submit this cost."), frappe.PermissionError)
	require_module(ctx.organization, "Cost Intelligence")
	if flt(amount) <= 0:
		frappe.throw(_("Amount must be greater than zero."))
	if not (invoice_reference or "").strip():
		frappe.throw(_("Enter your invoice reference."))
	doc = _get_shipment(ctx, name)
	url = _attach(doc, ctx, filename, content)
	line = frappe.get_doc({
		"doctype": "IQ Cost Line", "organization": ctx.organization, "shipment": doc.name,
		"cost_category": cost_category, "cost_status": "Estimate", "currency": currency, "amount": flt(amount),
		"cost_date": getdate(cost_date), "vendor": ctx.partner_name, "invoice_reference": invoice_reference.strip(),
		"source_document": url, "description": "Submitted via transitor portal - verify against the invoice before recording an actual",
	})
	line.flags.ignore_permissions = True
	line.insert()
	_note(doc, ctx, f"submitted {cost_category} charge {flt(amount):,.2f} {currency} (invoice {invoice_reference})")
	return line.name

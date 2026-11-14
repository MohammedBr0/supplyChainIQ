"""Unified dashboard data: one organization's upstream / in-transit / downstream picture."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from supplychain_iq import tenancy
from supplychain_iq.entitlements import get_entitlements, require_module
from supplychain_iq.intelligence import exceptions as exc_engine

IN_TRANSIT = ("Booked", "In Transit", "At Port", "Customs Clearance", "Released")
SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _resolve_org(organization: str | None) -> str:
	if tenancy.is_platform_admin():
		if organization:
			if not frappe.db.exists("IQ Organization", organization):
				frappe.throw(_("Unknown organization"))
			return organization
		org = tenancy.get_user_organization() or frappe.db.get_value("IQ Organization", {}, "name", order_by="creation asc")
		if not org:
			frappe.throw(_("No organizations exist yet."))
		return org
	return tenancy.require_organization()


@frappe.whitelist()
def get_organizations():
	if tenancy.is_platform_admin():
		return frappe.get_all("IQ Organization", fields=["name", "package", "subscription_status"], order_by="name")
	org = tenancy.require_organization()
	return frappe.get_all("IQ Organization", filters={"name": org}, fields=["name", "package", "subscription_status"])


@frappe.whitelist()
def get_dashboard_data(organization: str | None = None):
	org = _resolve_org(organization)
	ent = get_entitlements(org)
	require_module(org, "Unified Dashboard")
	t = getdate(today())
	data = {
		"organization": org,
		"package": ent.package,
		"modules": sorted(ent.modules),
		"as_of": str(t),
	}
	f = {"organization": org}

	if "Shipment Control Tower" in ent.modules:
		shipments = frappe.get_all(
			"IQ Shipment",
			filters={**f, "status": ["not in", ["Closed", "Cancelled"]]},
			fields=["name", "shipment_title", "status", "transport_mode", "origin", "destination",
				"planned_eta", "actual_eta", "delay_days", "is_delayed", "missing_documents", "awb_bl_number"],
			order_by="planned_eta asc",
		)
		active = [s for s in shipments if s.status != "Delivered"]
		data["shipments"] = {
			"active": len(active),
			"planned": sum(1 for s in active if s.status == "Planned"),
			"in_transit": sum(1 for s in active if s.status in IN_TRANSIT),
			"in_customs": sum(1 for s in active if s.status == "Customs Clearance"),
			"delayed": sum(1 for s in active if s.is_delayed),
			"missing_documents": sum(1 for s in active if s.missing_documents),
			"arriving_7_days": sum(
				1 for s in active
				if s.planned_eta and not s.actual_eta and 0 <= (getdate(s.planned_eta) - t).days <= 7
			),
			"by_status": _count_by(active, "status"),
			"by_mode": _count_by(active, "transport_mode"),
			"in_transit_list": [s for s in active if s.status in IN_TRANSIT][:15],
			"upcoming_list": [s for s in active if s.status == "Planned"][:10],
		}
		delivered = frappe.get_all(
			"IQ Shipment",
			filters={**f, "status": ["in", ["Delivered", "Closed"]], "actual_eta": ["is", "set"]},
			fields=["planned_eta", "actual_eta"],
		)
		on_time = sum(1 for d in delivered if d.planned_eta and getdate(d.actual_eta) <= getdate(d.planned_eta))
		data["performance"] = {
			"delivered_shipments": len(delivered),
			"on_time_rate": round(100.0 * on_time / len(delivered), 1) if delivered else None,
			"on_time_definition": "Delivered/closed shipments whose actual arrival is on or before planned ETA.",
		}

	if "Procurement Intelligence" in ent.modules:
		data["procurement"] = {
			"open_pos": frappe.db.count("IQ Purchase Order", {**f, "status": ["in", ["Draft", "Confirmed", "Partially Shipped"]]}),
			"pos_due_14_days": frappe.db.count(
				"IQ Purchase Order",
				{**f, "status": ["in", ["Draft", "Confirmed"]], "expected_ship_date": ["between", [t, add_days(t, 14)]]},
			),
		}

	if "Inventory Intelligence" in ent.modules:
		stock = frappe.get_all(
			"IQ Stock Balance",
			filters=f,
			fields=["name", "item", "item_name", "warehouse", "batch_no", "quantity", "uom",
				"stock_cover_months", "cover_available", "days_to_expiry", "expiry_date", "stock_status"],
		)
		wh_names = dict(frappe.get_all("IQ Warehouse", filters=f, fields=["name", "warehouse_name"], as_list=True))
		for s in stock:
			s.warehouse_name = wh_names.get(s.warehouse, s.warehouse)
			if not s.cover_available:
				s.stock_cover_months = None
			if not s.expiry_date:
				s.days_to_expiry = None
		alerts = [s for s in stock if s.stock_status != "OK"]
		alerts.sort(key=lambda s: ({"Expired": 0, "Out of Stock": 1, "Expiring Soon": 2, "Low": 3}.get(s.stock_status, 9), s.days_to_expiry if s.days_to_expiry is not None else 99999))
		data["inventory"] = {
			"stock_lines": len(stock),
			"items": len({s.item for s in stock}),
			"warehouses": frappe.db.count("IQ Warehouse", f),
			"by_status": _count_by(stock, "stock_status"),
			"expiring_90_days": sum(1 for s in stock if s.days_to_expiry is not None and 0 <= s.days_to_expiry <= 90),
			"cover_unknown": sum(1 for s in stock if s.stock_cover_months is None and (s.quantity or 0) > 0),
			"alerts": alerts[:15],
		}

	if "Exception Management" in ent.modules:
		exc = frappe.get_all(
			"IQ Exception",
			filters={**f, "status": ["in", ["Open", "In Progress"]]},
			fields=["name", "title", "exception_type", "severity", "status", "reference_doctype",
				"reference_name", "due_date", "assigned_to"],
		)
		exc.sort(key=lambda e: (SEVERITY_ORDER.get(e.severity, 9), str(e.due_date or "")))
		data["exceptions"] = {
			"open": len(exc),
			"critical": sum(1 for e in exc if e.severity == "Critical"),
			"high": sum(1 for e in exc if e.severity == "High"),
			"overdue": sum(1 for e in exc if e.due_date and getdate(e.due_date) < t),
			"by_type": _count_by(exc, "exception_type"),
			"top": exc[:12],
		}

	if "Data Intake" in ent.modules:
		data["imports"] = frappe.get_all(
			"IQ Import Batch",
			filters=f,
			fields=["name", "import_type", "status", "total_rows", "error_rows", "modified"],
			order_by="modified desc",
			limit=5,
		)
	return data


@frappe.whitelist(methods=["POST"])
def run_checks(organization: str | None = None):
	org = _resolve_org(organization)
	if not (tenancy.is_platform_admin() or frappe.has_permission("IQ Exception", "write")):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	require_module(org, "Exception Management")
	return exc_engine.run_for_organization(org)


def _count_by(rows, field):
	out = {}
	for r in rows:
		key = r.get(field) or "Not set"
		out[key] = out.get(key, 0) + 1
	return out

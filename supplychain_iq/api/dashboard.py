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
		exc_filters = {**f, "status": ["in", ["Open", "In Progress"]]}
		if not tenancy.can_see_restricted():
			exc_filters["restricted"] = 0
		exc = frappe.get_all(
			"IQ Exception",
			filters=exc_filters,
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

	if "Cost Intelligence" in ent.modules:
		data["costs"] = cost_section(org, t)

	if "Supplier Intelligence" in ent.modules:
		data["suppliers"] = frappe.get_all(
			"IQ Supplier",
			filters={**f, "shipments_measured": [">", 0]},
			fields=["name", "supplier_name", "shipments_measured", "on_time_rate", "avg_delay_days",
				"avg_transit_days", "avg_po_lead_time_days"],
			order_by="on_time_rate asc",
			limit=10,
		)

	if ent.modules & {"Warehouse & Batch Control", "Distribution & Delivery", "Cold Chain Intelligence"}:
		data["operations"] = operations_section(org, t, ent.modules)

	if ent.modules & {"Regulatory & Privileges", "LC & Import Finance"}:
		comp = {}
		if "Regulatory & Privileges" in ent.modules:
			privs = frappe.get_all("IQ Privilege", filters={**f, "review_status": ["!=", "Revoked"]}, fields=["validity_status", "review_status"])
			comp["privileges_by_validity"] = _count_by(privs, "validity_status")
			comp["privileges_pending_review"] = sum(1 for p in privs if p.review_status in ("Draft", "Under Review", "Needs Legal Review"))
		if "LC & Import Finance" in ent.modules:
			comp["lc_cases"] = frappe.get_all(
				"IQ LC Case",
				filters={**f, "status": ["not in", ["Payment Made", "Closed", "Cancelled"]]},
				fields=["name", "lc_number", "bank", "status", "currency", "amount", "next_deadline", "checklist_progress"],
				order_by="next_deadline asc",
				limit=8,
			)
		data["compliance"] = comp
	if "Customs Management" in ent.modules:
		cases = frappe.get_all(
			"IQ Customs Case", filters={**f, "status": ["!=", "Cancelled"]},
			fields=["name", "shipment", "declaration_number", "customs_office", "status", "lane", "clearance_days", "release_date"],
			order_by="lodged_date desc",
		)
		released = [c for c in cases if c.status == "Released" and c.clearance_days is not None]
		data.setdefault("compliance", {})["customs"] = {
			"open": [c for c in cases if c.status not in ("Released", "Draft")][:8],
			"by_status": _count_by(cases, "status"),
			"avg_clearance_days": round(sum(c.clearance_days for c in released) / len(released), 1) if released else None,
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


def operations_section(org, t, modules):
	out = {}
	f = {"organization": org}
	if "Warehouse & Batch Control" in modules:
		since = add_days(t, -30)
		moves = frappe.get_all(
			"IQ Stock Movement",
			filters={**f, "docstatus": 1, "posting_date": [">=", since]},
			fields=["name", "movement_type", "posting_date", "total_quantity", "from_warehouse", "to_warehouse"],
			order_by="posting_date desc, creation desc",
		)
		out["movements_30d"] = _count_by(moves, "movement_type")
		out["recent_movements"] = moves[:8]
		out["draft_movements"] = frappe.db.count("IQ Stock Movement", {**f, "docstatus": 0})
	if "Distribution & Delivery" in modules:
		deliveries = frappe.get_all(
			"IQ Delivery",
			filters={**f, "status": ["!=", "Cancelled"]},
			fields=["name", "recipient", "destination", "status", "planned_delivery_date", "delivered_on", "on_time"],
			order_by="planned_delivery_date asc",
		)
		done = [d for d in deliveries if d.status in ("Delivered", "Partially Delivered")]
		out["deliveries"] = {
			"to_dispatch": sum(1 for d in deliveries if d.status == "Draft"),
			"in_transit": sum(1 for d in deliveries if d.status == "Dispatched"),
			"overdue": sum(1 for d in deliveries if d.status in ("Draft", "Dispatched") and getdate(d.planned_delivery_date) < t),
			"short": sum(1 for d in deliveries if d.status == "Partially Delivered"),
			"delivered": len(done),
			"on_time_rate": round(100.0 * sum(1 for d in done if d.on_time) / len(done), 1) if done else None,
			"open_list": [d for d in deliveries if d.status in ("Draft", "Dispatched")][:8],
		}
	if "Cold Chain Intelligence" in modules or "Warehouse & Batch Control" in modules:
		out["qa_hold"] = frappe.get_all(
			"IQ Stock Balance",
			filters={**f, "qa_status": "Quarantined", "quantity": [">", 0]},
			fields=["name", "item_name", "item", "warehouse", "batch_no", "quantity", "uom", "qa_hold_reason"],
		)
	if "Cold Chain Intelligence" in modules:
		out["excursions_7d"] = frappe.db.count(
			"IQ Temperature Log", {**f, "is_excursion": 1, "reading_time": [">=", add_days(t, -7)]}
		)
		out["readings_7d"] = frappe.db.count("IQ Temperature Log", {**f, "reading_time": [">=", add_days(t, -7)]})
	return out


def cost_section(org, t):
	from supplychain_iq.intelligence import costs

	base = costs.base_currency(org)
	open_shipments = frappe.get_all(
		"IQ Shipment",
		filters={"organization": org, "status": ["not in", ["Cancelled"]]},
		fields=["name", "shipment_title", "status", "landed_cost_total", "landed_cost_estimate", "landed_cost_actual",
			"landed_cost_per_unit", "uom", "cost_lines_count", "free_time_start", "free_time_days",
			"demurrage_rate_per_day", "demurrage_currency", "actual_eta", "modified"],
	)
	lines = frappe.get_all(
		"IQ Cost Line",
		filters={"organization": org},
		fields=["shipment", "cost_category", "cost_status", "amount_base"],
	)
	from supplychain_iq.intelligence import calculations as calc

	by_shipment = {}
	for line in lines:
		by_shipment.setdefault(line.shipment, []).append(line)
	by_category = {}
	for rows in by_shipment.values():
		for cat, amount in calc.landed_cost(rows)["by_category"].items():
			by_category[cat] = round(by_category.get(cat, 0) + amount, 2)

	exposure = []
	for s in open_shipments:
		if not s.free_time_start or s.status in ("Released", "Delivered", "Closed"):
			continue
		doc = frappe.get_doc("IQ Shipment", s.name)
		d = costs.shipment_demurrage(doc)
		if d["days"] > 0 or (d["days_left"] is not None and d["days_left"] <= 7):
			exposure.append({
				"name": s.name, "shipment_title": s.shipment_title, "free_time_ends": d["free_time_ends"],
				"days": d["days"], "days_left": d["days_left"], "exposure": d["exposure"],
				"currency": s.demurrage_currency,
			})
	costed = [s for s in open_shipments if s.cost_lines_count]
	costed.sort(key=lambda s: -(s.landed_cost_total or 0))
	return {
		"base_currency": base,
		"landed_cost_total": round(sum(s.landed_cost_total or 0 for s in costed), 2),
		"estimate_total": round(sum(s.landed_cost_estimate or 0 for s in costed), 2),
		"actual_total": round(sum(s.landed_cost_actual or 0 for s in costed), 2),
		"shipments_costed": len(costed),
		"shipments_uncosted": len([s for s in open_shipments if not s.cost_lines_count]),
		"by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
		"top_shipments": costed[:8],
		"demurrage": exposure,
		"demurrage_note": "Exposure is in each shipment's demurrage currency; days are counted until customs release or delivery.",
	}


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

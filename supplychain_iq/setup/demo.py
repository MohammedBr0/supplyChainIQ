"""Synthetic demo data. Never load real customer, UN, employer or government data.

    DEMO_PASSWORD='...' bench --site <site> execute supplychain_iq.setup.demo.create_demo

Creates two organizations so tenant isolation can be demonstrated:
* Demo Relief Org (IQ Professional): multimodal Djibouti -> Modjo -> Addis shipments, medical stock.
* Demo Pharma Importer (IQ Essential): a smaller importer.
"""

import os

import frappe
from frappe.utils import add_days, getdate, today

from supplychain_iq.intelligence.exceptions import run_for_organization
from supplychain_iq.setup.install import after_install

ORGS = {
	"Demo Relief Org": {
		"organization_type": "NGO / INGO / UN-related",
		"package": "IQ Professional",
		"users": [
			("relief.admin@demo.example", "Relief", "Admin", "Org Admin"),
			("relief.logistics@demo.example", "Relief", "Logistics", "Logistics Officer"),
			("relief.warehouse@demo.example", "Relief", "Warehouse", "Warehouse Officer"),
		],
	},
	"Demo Pharma Importer": {
		"organization_type": "Medical / Pharmaceutical Distributor",
		"package": "IQ Essential",
		"users": [("pharma.admin@demo.example", "Pharma", "Admin", "Org Admin")],
	},
}


def create_demo(password: str | None = None):
	password = password or os.environ.get("DEMO_PASSWORD")
	if not password:
		frappe.throw("Pass a password for the demo users (or set DEMO_PASSWORD).")
	after_install()
	frappe.set_user("Administrator")
	for org_name, spec in ORGS.items():
		if frappe.db.exists("IQ Organization", org_name):
			continue
		for email, first, last, _role in spec["users"]:
			if not frappe.db.exists("User", email):
				u = frappe.get_doc({
					"doctype": "User", "email": email, "first_name": first, "last_name": last,
					"send_welcome_email": 0, "user_type": "System User", "new_password": password,
				})
				u.insert(ignore_permissions=True)
		org = frappe.get_doc({
			"doctype": "IQ Organization", "organization_name": org_name,
			"organization_type": spec["organization_type"], "package": spec["package"],
			"subscription_status": "Active", "country": "Ethiopia", "base_currency": "ETB",
			"members": [{"user": e, "iq_role": r} for e, _f, _l, r in spec["users"]],
		})
		org.insert()

	_relief_data("Demo Relief Org")
	_pharma_data("Demo Pharma Importer")
	for org in ORGS:
		run_for_organization(org)
	frappe.db.commit()
	return "Demo data created"


def _d(days):
	return add_days(getdate(today()), days)


def _get_or_create(doctype, filters, values):
	name = frappe.db.get_value(doctype, filters)
	if name:
		return name
	doc = frappe.get_doc({"doctype": doctype, **filters, **values})
	doc.insert()
	return doc.name


def _relief_data(org):
	if frappe.db.exists("IQ Shipment", {"organization": org}):
		return
	o = {"organization": org}
	sup1 = _get_or_create("IQ Supplier", {**o, "supplier_name": "Example Global Health Supplies"}, {"country": "India", "standard_lead_time_days": 60})
	sup2 = _get_or_create("IQ Supplier", {**o, "supplier_name": "Example Cold Chain Biologics"}, {"country": "Belgium", "standard_lead_time_days": 21})
	po1 = _get_or_create("IQ Purchase Order", {**o, "po_number": "DEMO-PO-1001"}, {"supplier": sup1, "status": "Confirmed", "order_date": _d(-75), "expected_ship_date": _d(-40), "currency": "USD", "total_value": 128000})
	po2 = _get_or_create("IQ Purchase Order", {**o, "po_number": "DEMO-PO-1002"}, {"supplier": sup2, "status": "Confirmed", "order_date": _d(-20), "expected_ship_date": _d(5), "currency": "EUR", "total_value": 46000})

	docs = lambda received: [  # noqa: E731
		{"document_type": t, "required": 1, "received": 1 if t in received else 0}
		for t in ("Commercial Invoice", "Packing List", "Bill of Lading", "Certificate of Origin", "Duty-Free Privilege Approval")
	]
	frappe.get_doc({
		"doctype": "IQ Shipment", **o, "shipment_title": "Essential medicines - 2x40ft containers",
		"status": "Customs Clearance", "transport_mode": "Multimodal", "supplier": sup1, "purchase_order": po1,
		"awb_bl_number": "DEMO-BL-778812", "origin": "Mumbai, IN", "destination": "Addis Ababa, ET",
		"quantity": 2, "uom": "CONTAINER", "cargo_value": 128000, "currency": "USD", "incoterm": "CFR",
		"planned_etd": _d(-45), "actual_etd": _d(-43), "planned_eta": _d(-6),
		"legs": [
			{"sequence": 1, "mode": "Sea", "origin": "Mumbai, IN", "destination": "Djibouti Port", "carrier": "Example Line", "reference": "DEMO-CONT-01", "planned_departure": _d(-45), "actual_departure": _d(-43), "planned_arrival": _d(-25), "actual_arrival": _d(-22)},
			{"sequence": 2, "mode": "Rail", "origin": "Djibouti Port", "destination": "Modjo Dry Port", "carrier": "Example Railway", "planned_departure": _d(-20), "actual_departure": _d(-15), "planned_arrival": _d(-18), "actual_arrival": _d(-13)},
			{"sequence": 3, "mode": "Road", "origin": "Modjo Dry Port", "destination": "Addis Ababa Central Warehouse", "planned_departure": _d(-8), "planned_arrival": _d(-6)},
		],
		"milestones": [
			{"milestone": "Departed Origin", "planned_date": _d(-45), "actual_date": _d(-43), "responsible_party": "Supplier"},
			{"milestone": "Arrived Port of Discharge", "planned_date": _d(-25), "actual_date": _d(-22), "responsible_party": "Freight forwarder"},
			{"milestone": "Arrived Dry Port", "planned_date": _d(-18), "actual_date": _d(-13), "responsible_party": "Freight forwarder"},
			{"milestone": "Customs Declaration Lodged", "planned_date": _d(-16), "actual_date": _d(-11), "responsible_party": "Clearing agent"},
			{"milestone": "Customs Released", "planned_date": _d(-10), "responsible_party": "Clearing agent"},
			{"milestone": "Delivered to Warehouse", "planned_date": _d(-6), "responsible_party": "Transporter"},
		],
		"documents": docs({"Commercial Invoice", "Packing List", "Bill of Lading", "Certificate of Origin"}),
	}).insert()
	frappe.get_doc({
		"doctype": "IQ Shipment", **o, "shipment_title": "Vaccines - temperature-controlled air freight",
		"status": "Booked", "transport_mode": "Air", "supplier": sup2, "purchase_order": po2,
		"awb_bl_number": "DEMO-AWB-17600001", "origin": "Brussels, BE", "destination": "Addis Ababa, ET",
		"quantity": 14, "uom": "BOX", "cargo_value": 46000, "currency": "EUR", "incoterm": "CIP",
		"planned_etd": _d(4), "planned_eta": _d(5),
		"milestones": [{"milestone": "Cargo Ready", "planned_date": _d(2), "responsible_party": "Supplier"}],
		"documents": docs({"Commercial Invoice"}),
	}).insert()
	frappe.get_doc({
		"doctype": "IQ Shipment", **o, "shipment_title": "Shelter kits - road from Djibouti",
		"status": "In Transit", "transport_mode": "Road", "supplier": sup1, "po_reference": "LEGACY-7781",
		"awb_bl_number": "DEMO-CMR-5521", "origin": "Djibouti Port", "destination": "Dire Dawa Regional Warehouse",
		"planned_etd": _d(-3), "actual_etd": _d(-3), "planned_eta": _d(2),
		"documents": docs({"Commercial Invoice", "Packing List", "Bill of Lading", "Certificate of Origin", "Duty-Free Privilege Approval"}),
	}).insert()
	frappe.get_doc({
		"doctype": "IQ Shipment", **o, "shipment_title": "Nutrition supplies (delivered)",
		"status": "Delivered", "transport_mode": "Sea", "supplier": sup1, "origin": "Jebel Ali, AE",
		"destination": "Addis Ababa, ET", "planned_etd": _d(-80), "actual_etd": _d(-80), "planned_eta": _d(-50), "actual_eta": _d(-47),
	}).insert()

	wh1 = _get_or_create("IQ Warehouse", {**o, "warehouse_name": "Addis Ababa Central Warehouse"}, {"city": "Addis Ababa", "warehouse_type": "Central"})
	wh2 = _get_or_create("IQ Warehouse", {**o, "warehouse_name": "Dire Dawa Regional Warehouse"}, {"city": "Dire Dawa", "warehouse_type": "Regional"})
	items = {
		"DEMO-AMX500": ("Amoxicillin 500mg caps (100)", "PACK", 0),
		"DEMO-ORS": ("Oral rehydration salts", "EA", 0),
		"DEMO-VAC-M": ("Measles vaccine 10-dose vial", "VIAL", 1),
		"DEMO-RUTF": ("Ready-to-use therapeutic food", "CARTON", 0),
		"DEMO-NET": ("Long-lasting insecticidal net", "EA", 0),
	}
	ids = {}
	for code, (name, uom, cold) in items.items():
		ids[code] = _get_or_create("IQ Item", {**o, "item_code": code}, {"item_name": name, "uom": uom, "requires_cold_chain": cold, "min_temperature": 2 if cold else None, "max_temperature": 8 if cold else None})
	for item, wh, batch, qty, exp, amc in (
		("DEMO-AMX500", wh1, "AMX-B1", 320, _d(400), 60),
		("DEMO-AMX500", wh2, "AMX-B2", 25, _d(40), 30),
		("DEMO-ORS", wh1, "ORS-B7", 900, _d(300), 1200),
		("DEMO-VAC-M", wh1, "VAC-B3", 150, _d(-5), 50),
		("DEMO-RUTF", wh2, "RUTF-B1", 0, _d(200), 80),
		("DEMO-NET", wh1, None, 4000, None, None),
	):
		frappe.get_doc({"doctype": "IQ Stock Balance", **o, "item": ids[item], "warehouse": wh, "batch_no": batch, "quantity": qty, "expiry_date": exp, "avg_monthly_consumption": amc}).insert()


def _pharma_data(org):
	if frappe.db.exists("IQ Shipment", {"organization": org}):
		return
	o = {"organization": org}
	sup = _get_or_create("IQ Supplier", {**o, "supplier_name": "Example Generics Manufacturer"}, {"country": "China"})
	frappe.get_doc({
		"doctype": "IQ Shipment", **o, "shipment_title": "Antibiotics consignment", "status": "In Transit",
		"transport_mode": "Sea", "supplier": sup, "po_reference": "PH-2026-044", "awb_bl_number": "DEMO-BL-PH-001",
		"origin": "Shanghai, CN", "destination": "Addis Ababa, ET", "planned_etd": _d(-30), "actual_etd": _d(-29), "planned_eta": _d(-2),
		"documents": [{"document_type": "Commercial Invoice", "required": 1, "received": 1}, {"document_type": "Import Permit", "required": 1, "received": 0}],
	}).insert()
	wh = _get_or_create("IQ Warehouse", {**o, "warehouse_name": "Bole Distribution Store"}, {"city": "Addis Ababa"})
	item = _get_or_create("IQ Item", {**o, "item_code": "PH-CIP500"}, {"item_name": "Ciprofloxacin 500mg tabs", "uom": "PACK"})
	frappe.get_doc({"doctype": "IQ Stock Balance", **o, "item": item, "warehouse": wh, "batch_no": "CIP-01", "quantity": 60, "expiry_date": _d(75), "avg_monthly_consumption": 90}).insert()

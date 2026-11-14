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
			("relief.qa@demo.example", "Relief", "QA", "QA Officer"),
			("relief.compliance@demo.example", "Relief", "Compliance", "Compliance Officer"),
			("relief.protocol@demo.example", "Relief", "Protocol", "Protocol Officer"),
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
		for email, first, last, _role in spec["users"]:
			if not frappe.db.exists("User", email):
				u = frappe.get_doc({
					"doctype": "User", "email": email, "first_name": first, "last_name": last,
					"send_welcome_email": 0, "user_type": "System User", "new_password": password,
				})
				u.insert(ignore_permissions=True)
		if frappe.db.exists("IQ Organization", org_name):
			# demo users added in later releases join the existing demo organization
			org = frappe.get_doc("IQ Organization", org_name)
			have = {m.user for m in org.members}
			missing = [(e, r) for e, _f, _l, r in spec["users"] if e not in have]
			for e, r in missing:
				org.append("members", {"user": e, "iq_role": r})
			if missing:
				org.save()
			continue
		org = frappe.get_doc({
			"doctype": "IQ Organization", "organization_name": org_name,
			"organization_type": spec["organization_type"], "package": spec["package"],
			"subscription_status": "Active", "country": "Ethiopia", "base_currency": "ETB",
			"members": [{"user": e, "iq_role": r} for e, _f, _l, r in spec["users"]],
		})
		org.insert()

	_relief_data("Demo Relief Org")
	_relief_costs("Demo Relief Org")
	_relief_operations("Demo Relief Org")
	_relief_compliance_and_partners("Demo Relief Org", password)
	_relief_diplomatic("Demo Relief Org")
	_relief_customs_and_lines("Demo Relief Org")
	frappe.set_user("Administrator")
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


def _relief_costs(org):
	"""Stage 4 demo: exchange rates, cost lines, demurrage terms (synthetic values)."""
	if frappe.db.exists("IQ Cost Line", {"organization": org}):
		return
	o = {"organization": org}
	for cur, rate in (("USD", 155.0), ("EUR", 168.0)):
		_get_or_create("IQ Exchange Rate", {**o, "from_currency": cur, "rate_date": _d(-90)},
			{"rate": rate, "source": "Other", "source_reference": "Synthetic demo rate - not a real quotation"})

	med = frappe.db.get_value("IQ Shipment", {**o, "awb_bl_number": "DEMO-BL-778812"})
	vac = frappe.db.get_value("IQ Shipment", {**o, "awb_bl_number": "DEMO-AWB-17600001"})
	nut = frappe.db.get_value("IQ Shipment", {**o, "shipment_title": "Nutrition supplies (delivered)"})
	if med:
		doc = frappe.get_doc("IQ Shipment", med)
		doc.free_time_start, doc.free_time_days = _d(-13), 7
		doc.demurrage_rate_per_day, doc.demurrage_currency = 150, "USD"
		doc.save()
	lines = []
	if med:
		lines += [
			(med, "Purchase Price", "Actual", "USD", 128000, -60, "Example Global Health Supplies"),
			(med, "Freight", "Estimate", "USD", 9000, -50, "Example Line"),
			(med, "Freight", "Actual", "USD", 11200, -20, "Example Line"),
			(med, "Insurance", "Actual", "USD", 640, -45, "Example Insurer"),
			(med, "Port & Handling", "Estimate", "USD", 1800, -22, "Djibouti terminal"),
			(med, "Inland Transport", "Estimate", "ETB", 350000, -15, "Example Railway"),
			(med, "Customs Clearance", "Estimate", "ETB", 85000, -11, "Example Clearing Agent"),
		]
	if vac:
		lines += [
			(vac, "Purchase Price", "Actual", "EUR", 46000, -20, "Example Cold Chain Biologics"),
			(vac, "Freight", "Estimate", "EUR", 5200, -5, "Example Air Cargo"),
		]
	if nut:
		lines += [
			(nut, "Purchase Price", "Actual", "USD", 54000, -85, "Example Global Health Supplies"),
			(nut, "Freight", "Actual", "USD", 4100, -60, "Example Line"),
			(nut, "Storage", "Actual", "ETB", 42000, -45, "Example Bonded Warehouse"),
		]
	for ship, cat, status, cur, amount, days, vendor in lines:
		frappe.get_doc({
			"doctype": "IQ Cost Line", **o, "shipment": ship, "cost_category": cat, "cost_status": status,
			"currency": cur, "amount": amount, "cost_date": _d(days), "vendor": vendor,
			"description": "Synthetic demo cost",
		}).insert()


def _relief_operations(org):
	"""Stage 6 demo: movements, deliveries, cold room readings (synthetic)."""
	if frappe.db.exists("IQ Stock Movement", {"organization": org}):
		return
	o = {"organization": org}
	central = frappe.db.get_value("IQ Warehouse", {**o, "warehouse_name": "Addis Ababa Central Warehouse"})
	dire = frappe.db.get_value("IQ Warehouse", {**o, "warehouse_name": "Dire Dawa Regional Warehouse"})
	cold = _get_or_create("IQ Warehouse", {**o, "warehouse_name": "Addis Cold Room"}, {
		"city": "Addis Ababa", "warehouse_type": "Cold Store", "temperature_controlled": 1, "min_temperature": 2, "max_temperature": 8,
	})
	item = lambda code: frappe.db.get_value("IQ Item", {**o, "item_code": code})  # noqa: E731
	if not (central and dire and item("DEMO-ORS")):
		return

	def move(mtype, rows, days, **kw):
		mv = frappe.get_doc({"doctype": "IQ Stock Movement", **o, "movement_type": mtype, "posting_date": _d(days), "items": rows, **kw})
		mv.insert()
		mv.submit()
		return mv

	move("Receipt", [
		{"item": item("DEMO-ORS"), "batch_no": "ORS-B9", "expiry_date": _d(500), "quantity": 2000},
		{"item": item("DEMO-AMX500"), "batch_no": "AMX-B5", "expiry_date": _d(600), "quantity": 150},
	], -20, to_warehouse=central)
	move("Receipt", [{"item": item("DEMO-VAC-M"), "batch_no": "VAC-B9", "expiry_date": _d(300), "quantity": 200}], -12, to_warehouse=cold)
	move("Transfer", [{"item": item("DEMO-ORS"), "quantity": 600}], -10, from_warehouse=central, to_warehouse=dire,
		reason="Pre-positioning for the regional response")
	move("Adjustment Out", [{"item": item("DEMO-VAC-M"), "batch_no": "VAC-B3", "quantity": 150}], -4, from_warehouse=central,
		reason="Disposal of expired vials (witnessed destruction)")

	pod = frappe.get_doc({"doctype": "File", "file_name": "demo-proof-of-delivery.txt", "is_private": 1,
		"content": b"Synthetic demo proof of delivery - signed by facility pharmacist"})
	pod.flags.ignore_permissions = True
	pod.insert()
	d1 = frappe.get_doc({
		"doctype": "IQ Delivery", **o, "recipient": "Example Health Centre, Adama", "recipient_type": "Health Facility",
		"destination": "Adama", "from_warehouse": central, "planned_delivery_date": _d(-6), "transport_reference": "DEMO-TRIP-031",
		"items": [{"item": item("DEMO-ORS"), "quantity": 400}, {"item": item("DEMO-AMX500"), "quantity": 60}],
	}).insert()
	d1.dispatch()
	d1.reload()
	d1.delivered_on, d1.received_by, d1.proof_of_delivery = _d(-5), "Facility pharmacist (demo)", pod.file_url
	d1.items[0].delivered_qty, d1.items[1].delivered_qty = 400, 55
	d1.save()
	d1.confirm_delivery()
	frappe.get_doc({
		"doctype": "IQ Delivery", **o, "recipient": "Example Nutrition Site, Jijiga", "recipient_type": "Beneficiary Site",
		"destination": "Jijiga", "from_warehouse": dire, "planned_delivery_date": _d(-2),
		"items": [{"item": item("DEMO-ORS"), "quantity": 200}],
	}).insert()
	frappe.get_doc({
		"doctype": "IQ Delivery", **o, "recipient": "Example Hospital, Hawassa", "recipient_type": "Health Facility",
		"destination": "Hawassa", "from_warehouse": central, "planned_delivery_date": _d(4),
		"items": [{"item": item("DEMO-NET"), "quantity": 500}],
	}).insert()

	from frappe.utils import add_to_date, now_datetime

	for hours, temp in ((-30, 4.6), (-24, 5.2), (-18, 5.9), (-12, 9.6), (-6, 6.1)):
		frappe.get_doc({
			"doctype": "IQ Temperature Log", **o, "location_type": "Warehouse", "warehouse": cold, "logger_id": "DEMO-LOGGER-07",
			"reading_time": add_to_date(now_datetime(), hours=hours), "temperature": temp,
		}).insert()


def _as(user, fn):
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")


def _website_user(email, first, password):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": first, "send_welcome_email": 0,
			"user_type": "Website User", "new_password": password}).insert(ignore_permissions=True)


def _relief_compliance_and_partners(org, password):
	"""Stage 5 + portals demo: privileges, LC case, transitor and portal logins (synthetic)."""
	if frappe.db.exists("IQ LC Case", {"organization": org}):
		return
	o = {"organization": org}
	pod = frappe.get_doc({"doctype": "File", "file_name": "demo-duty-free-approval.txt", "is_private": 1,
		"content": b"Synthetic demo approval letter - not a real authority document"})
	pod.flags.ignore_permissions = True
	pod.insert()
	priv = frappe.get_doc({
		"doctype": "IQ Privilege", **o, "title": "Duty-free privilege - medical supplies (demo)", "privilege_type": "Duty-Free Privilege",
		"authority": "Example Authority (demo)", "reference_no": "DEMO-DFP-2026-014", "beneficiary": org,
		"effective_date": _d(-150), "expiry_date": _d(25), "scope": "Essential medicines and medical consumables for the health programme (demo).",
		"source_document": pod.file_url, "confidence": "High",
		"conditions": [
			{"condition_type": "Authority-issued Condition", "condition_text": "Goods may not be sold or transferred.", "source_reference": "p.1 para 3"},
			{"condition_type": "Authority-issued Condition", "condition_text": "Present this approval with the customs declaration.", "source_reference": "p.2 para 1"},
		],
	}).insert()
	_as("relief.admin@demo.example", lambda: frappe.get_doc("IQ Privilege", priv.name).submit_for_review())
	_as("relief.compliance@demo.example", lambda: frappe.get_doc("IQ Privilege", priv.name).confirm("Checked against the original letter (demo)."))
	frappe.get_doc({
		"doctype": "IQ Privilege", **o, "title": "Import permit - cold-chain vaccines (demo)", "privilege_type": "Import Permit",
		"authority": "Example Regulator (demo)", "reference_no": "DEMO-IP-778", "effective_date": _d(-10), "no_expiry_stated": 1,
		"scope": "Measles vaccine, 14 boxes (demo).", "source_document": pod.file_url, "confidence": "Medium",
	}).insert()

	trn = _get_or_create("IQ Transitor", {**o, "transitor_name": "Example Clearing & Forwarding PLC"},
		{"license_number": "DEMO-CF-0091", "services": "Customs clearing, forwarding, inland transport"})
	med = frappe.db.get_value("IQ Shipment", {**o, "awb_bl_number": "DEMO-BL-778812"})
	kits = frappe.db.get_value("IQ Shipment", {**o, "awb_bl_number": "DEMO-CMR-5521"})
	for name, extra in ((med, {"privilege": priv.name}), (kits, {})):
		if name:
			doc = frappe.get_doc("IQ Shipment", name)
			doc.transitor = trn
			doc.update(extra)
			doc.save()

	po2 = frappe.db.get_value("IQ Purchase Order", {**o, "po_number": "DEMO-PO-1002"})
	lc = frappe.get_doc({
		"doctype": "IQ LC Case", **o, "bank": "Example Commercial Bank (demo)", "lc_number": "DEMO-LC-5512",
		"purchase_order": po2, "currency": "EUR", "amount": 46000, "proforma_reference": "PF-DEMO-221",
		"latest_shipment_date": _d(6), "expiry_date": _d(40), "presentation_days": 21,
		"milestones": [
			{"event": "Application Prepared", "event_date": _d(-18)},
			{"event": "Submitted to Bank", "event_date": _d(-15), "reference": "BANK-REF-DEMO-1"},
			{"event": "LC Issued", "event_date": _d(-10), "reference": "DEMO-LC-5512"},
		],
	}).insert()
	lc.load_standard_checklist()
	lc.reload()
	for c in lc.checklist[:4]:
		c.completed = 1
	lc.save()
	vac = frappe.db.get_value("IQ Shipment", {**o, "awb_bl_number": "DEMO-AWB-17600001"})
	if vac:
		doc = frappe.get_doc("IQ Shipment", vac)
		doc.lc_case = lc.name
		doc.save()

	sup = frappe.db.get_value("IQ Supplier", {**o, "supplier_name": "Example Global Health Supplies"})
	for email, first, ptype, link in (("supplier.demo@demo.example", "Supplier Demo", "Supplier", sup),
			("transitor.demo@demo.example", "Transitor Demo", "Transitor", trn)):
		_website_user(email, first, password)
		if not frappe.db.exists("IQ Portal User", {"user": email}):
			frappe.get_doc({"doctype": "IQ Portal User", **o, "user": email, "portal_type": ptype,
				"supplier": link if ptype == "Supplier" else None, "transitor": link if ptype == "Transitor" else None}).insert()
	if sup:
		_get_or_create("IQ Purchase Order", {**o, "po_number": "DEMO-PO-1003"},
			{"supplier": sup, "status": "Draft", "order_date": _d(-2), "currency": "USD", "total_value": 18500})


def _relief_diplomatic(org):
	"""Diplomatic Affairs demo: synthetic personas only (no real people)."""
	if frappe.db.exists("IQ Diplomatic Persona", {"organization": org}):
		return
	frappe.db.set_value("IQ Organization", org, "enable_diplomatic_id", 1)
	from supplychain_iq import tenancy

	tenancy.clear_cache()
	o = {"organization": org}
	alpha = frappe.get_doc({"doctype": "IQ Diplomatic Persona", **o, "full_name": "Demo Staff Alpha", "diplomatic_category": "Diplomatic Agent",
		"position": "Country Director (demo)", "nationality": "Exampleland", "arrival_date": _d(-700), "assignment_end_date": _d(45),
		"passport_type": "Diplomatic", "passport_number": "DEMO-P-0001", "passport_expiry": _d(150)}).insert()
	beta = frappe.get_doc({"doctype": "IQ Diplomatic Persona", **o, "full_name": "Demo Staff Beta", "diplomatic_category": "International Staff (non-diplomatic)",
		"position": "Logistics Coordinator (demo)", "nationality": "Sampleland", "arrival_date": _d(-300), "assignment_end_date": _d(400),
		"passport_type": "Service / Official", "passport_number": "DEMO-P-0002", "passport_expiry": _d(900)}).insert()
	frappe.get_doc({"doctype": "IQ Diplomatic Persona", **o, "full_name": "Demo Dependant Alpha-1", "diplomatic_category": "Dependant",
		"principal": alpha.name, "relationship": "Spouse", "passport_type": "Diplomatic", "passport_expiry": _d(1200)}).insert()
	frappe.get_doc({"doctype": "IQ Diplomatic ID", **o, "persona": alpha.name, "employee_name": alpha.full_name, "id_type": "Diplomatic ID",
		"id_number": "DEMO-ID-1001", "issue_date": _d(-325), "expiry_date": _d(40)}).insert()
	did = frappe.get_doc({"doctype": "IQ Diplomatic ID", **o, "persona": beta.name, "employee_name": beta.full_name, "id_type": "Service ID",
		"id_number": "DEMO-ID-1002", "issue_date": _d(-300), "expiry_date": _d(55)}).insert()
	did.load_standard_requirements()
	did.reload()
	for r in did.requirements:
		r.received = 1
	did.renewal_status = "Preparing Documents"
	did.save()
	did.reload()
	for r in did.requirements:
		r.received = 1
	did.renewal_status = "Internal Review Complete"
	did.save()
	did.renewal_status, did.submission_reference, did.submission_date, did.next_follow_up = "Submitted", "DEMO-SUB-77", _d(-12), _d(-2)
	did.save()

	src = frappe.get_doc({"doctype": "File", "file_name": "demo-personal-privilege.txt", "is_private": 1,
		"content": b"Synthetic demo authorisation - not a real document"})
	src.flags.ignore_permissions = True
	src.insert()
	for persona, ptype, quota, unit, used, expiry in (
		(alpha.name, "Vehicle Duty-Free Import", 1, "vehicle", [(_d(-600), "Vehicle import (demo)", 1)], _d(45)),
		(beta.name, "Personal Effects Duty-Free Import", 15000, "USD", [(_d(-250), "Household effects shipment (demo)", 9000)], _d(30)),
	):
		pp = frappe.get_doc({"doctype": "IQ Personal Privilege", **o, "persona": persona, "privilege_type": ptype,
			"authority": "Example Authority (demo)", "reference_no": f"DEMO-PP-{persona[-3:]}", "effective_date": _d(-700),
			"expiry_date": expiry, "entitlement": f"{ptype} as granted in the demo authorisation.", "quota_value": quota, "quota_unit": unit,
			"source_document": src.file_url, "utilisations": [{"use_date": d, "description": t, "value_used": v} for d, t, v in used]}).insert()
		_as("relief.protocol@demo.example", lambda pp=pp: frappe.get_doc("IQ Personal Privilege", pp.name).submit_for_review())
		_as("relief.admin@demo.example", lambda pp=pp: frappe.get_doc("IQ Personal Privilege", pp.name).confirm("Matches the original (demo)."))


def _relief_customs_and_lines(org):
	"""Customs case and ASN item lines (synthetic)."""
	if frappe.db.exists("IQ Customs Case", {"organization": org}):
		return
	o = {"organization": org}
	med = frappe.db.get_value("IQ Shipment", {**o, "awb_bl_number": "DEMO-BL-778812"})
	if med:
		sh = frappe.get_doc("IQ Shipment", med)
		frappe.get_doc({
			"doctype": "IQ Customs Case", **o, "shipment": med, "customs_office": "Modjo Dry Port (demo)",
			"procedure": "Duty-Free (Privilege)", "declaration_number": "DEMO-DEC-40817", "declarant": sh.transitor,
			"lane": "Yellow", "lodged_date": _d(-11), "assessed_date": _d(-9), "inspection_date": _d(-7), "payment_date": _d(-6),
			"currency": "ETB",
			"taxes": [
				{"tax_type": "Customs Duty", "assessed_amount": 1985000, "exempted": 1, "exemption_basis": sh.privilege or "Duty-free privilege"},
				{"tax_type": "VAT", "assessed_amount": 3275250, "exempted": 1, "exemption_basis": sh.privilege or "Duty-free privilege"},
				{"tax_type": "Withholding Tax", "assessed_amount": 59550, "paid_amount": 59550, "payment_reference": "DEMO-RCPT-5521"},
			],
			"notes": "Synthetic demo assessment - not real customs data.",
		}).insert()
	vac = frappe.db.get_value("IQ Shipment", {**o, "awb_bl_number": "DEMO-AWB-17600001"})
	item = frappe.db.get_value("IQ Item", {**o, "item_code": "DEMO-VAC-M"})
	if vac and item:
		sh = frappe.get_doc("IQ Shipment", vac)
		sh.set("lines", [
			{"item": item, "description": "Measles vaccine 10-dose vial", "quantity": 1200, "uom": "VIAL", "batch_no": "VAC-NEW-01", "expiry_date": _d(540), "unit_value": 32},
			{"item_code": "DEMO-DIL", "description": "Diluent 10-dose (no item master yet)", "quantity": 1200, "uom": "VIAL", "unit_value": 6.33},
		])
		sh.save()


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

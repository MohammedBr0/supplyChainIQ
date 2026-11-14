import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, flt, today

from supplychain_iq.api import portal
from supplychain_iq.intelligence import calculations as calc
from supplychain_iq.intelligence.exceptions import run_for_organization
from supplychain_iq.tests.test_compliance import purge, website_user
from supplychain_iq.tests.test_operations import purge_ops
from supplychain_iq.tests.utils import as_user, attach_csv, ensure_org

ORG = "_Test IQ Batch1 Org"
ADMIN = "iq.b1.admin@test.example"
WH = "iq.b1.wh@test.example"
SUP_USER = "iq.b1.supplier@test.example"
TRN_USER = "iq.b1.transitor@test.example"
OTHER_TRN_USER = "iq.b1.transitor2@test.example"


class TestAllocation(UnitTestCase):
	def test_by_value_and_quantity(self):
		lines = [{"quantity": 10, "line_value": 300}, {"quantity": 30, "line_value": 100}]
		by_value = calc.allocate_cost(lines, 1000, "Value")
		self.assertEqual([a["allocated_cost"] for a in by_value], [750, 250])
		self.assertEqual(by_value[0]["landed_unit_cost"], 75)
		by_qty = calc.allocate_cost(lines, 1000, "Quantity")
		self.assertEqual([a["allocated_cost"] for a in by_qty], [250, 750])
		# residue goes to the last line so parts always add up
		thirds = calc.allocate_cost([{"quantity": 1}] * 3, 100, "Quantity")
		self.assertEqual(round(sum(a["allocated_cost"] for a in thirds), 2), 100)
		self.assertEqual(calc.allocate_cost([], 100, "Value"), [])


class B1Case(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for e in (SUP_USER, TRN_USER, OTHER_TRN_USER):
			name = frappe.db.get_value("IQ Portal User", {"user": e})
			if name:
				frappe.delete_doc("IQ Portal User", name, force=True, ignore_permissions=True)
		ensure_org(ORG, package="IQ Enterprise", users=[(ADMIN, "Org Admin"), (WH, "Warehouse Officer")])

	def setUp(self):
		for n in frappe.get_all("IQ Customs Case", filters={"organization": ORG}, pluck="name"):
			frappe.delete_doc("IQ Customs Case", n, force=True, ignore_permissions=True)
		purge_ops(ORG)
		purge(ORG)
		as_user(ADMIN)
		frappe.get_doc({"doctype": "IQ Exchange Rate", "from_currency": "USD", "rate": 100, "rate_date": add_days(today(), -30), "source": "Commercial Bank"}).insert()
		self.wh = frappe.get_doc({"doctype": "IQ Warehouse", "warehouse_name": "Main"}).insert().name
		self.item = frappe.get_doc({"doctype": "IQ Item", "item_code": "MED1", "item_name": "Medicine 1", "uom": "BOX"}).insert().name
		self.trn = frappe.get_doc({"doctype": "IQ Transitor", "transitor_name": "Agent"}).insert().name
		self.trn2 = frappe.get_doc({"doctype": "IQ Transitor", "transitor_name": "Agent Two"}).insert().name
		self.sup = frappe.get_doc({"doctype": "IQ Supplier", "supplier_name": "Supplier"}).insert().name

	def tearDown(self):
		frappe.set_user("Administrator")

	def shipment(self, **kw):
		return frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Cargo", "transport_mode": "Sea", "status": "At Port",
			"origin": "A", "destination": "B", "planned_eta": today(), "currency": "USD", **kw}).insert()


class TestCustoms(B1Case):
	def test_status_totals_shipment_sync_and_cost_line(self):
		sh = self.shipment(transitor=self.trn)
		case = frappe.get_doc({"doctype": "IQ Customs Case", "shipment": sh.name, "customs_office": "Modjo", "procedure": "Home Consumption",
			"lodged_date": add_days(today(), -3), "assessed_date": add_days(today(), -2), "currency": "etb",
			"taxes": [{"tax_type": "Customs Duty", "assessed_amount": 1000}, {"tax_type": "VAT", "assessed_amount": 500, "exempted": 1, "exemption_basis": "Decision 12"}]}).insert()
		self.assertEqual((case.status, case.total_assessed, case.total_payable, case.declarant), ("Assessed", 1500, 1000, self.trn))
		sh.reload()
		self.assertEqual((sh.status, sh.customs_case), ("Customs Clearance", case.name))
		self.assertTrue(any(m.milestone == "Customs Declaration Lodged" and m.actual_date for m in sh.milestones))
		case.taxes[0].paid_amount, case.taxes[0].payment_reference, case.payment_date = 1000, "R-1", today()
		case.save()
		self.assertEqual(case.status, "Duties Paid")
		line = frappe.get_doc("IQ Cost Line", case.cost_line)
		self.assertEqual((line.cost_category, line.cost_status, line.amount_base), ("Duties & Taxes", "Actual", 1000))
		case.release_date = today()
		case.save()
		sh.reload()
		self.assertEqual((case.status, sh.status, case.clearance_days), ("Released", "Released", 3))
		with self.assertRaises(frappe.ValidationError):  # one open case per shipment
			frappe.get_doc({"doctype": "IQ Customs Case", "shipment": sh.name, "customs_office": "X", "procedure": "Transit"}).insert()

	def test_validation_and_alerts(self):
		sh = self.shipment()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "IQ Customs Case", "shipment": sh.name, "customs_office": "X", "procedure": "Transit", "assessed_date": today()}).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "IQ Customs Case", "shipment": sh.name, "customs_office": "X", "procedure": "Transit",
				"lodged_date": today(), "taxes": [{"tax_type": "VAT", "assessed_amount": 5, "exempted": 1}]}).insert()  # exemption needs a basis
		frappe.get_doc({"doctype": "IQ Customs Case", "shipment": sh.name, "customs_office": "Kality", "procedure": "Home Consumption",
			"lodged_date": add_days(today(), -12), "assessed_date": add_days(today(), -10), "lane": "Red",
			"taxes": [{"tax_type": "Customs Duty", "assessed_amount": 800}]}).insert()
		run_for_organization(ORG)
		types = set(frappe.get_all("IQ Exception", filters={"organization": ORG, "status": "Open"}, pluck="exception_type"))
		self.assertTrue({"Customs Delay", "Duties Unpaid"} <= types)


class TestLinesAndReturns(B1Case):
	def test_line_allocation_receipt_and_discrepancy(self):
		sh = self.shipment(status="In Transit", cost_allocation_basis="Value", lines=[
			{"item": self.item, "description": "", "quantity": 10, "unit_value": 30, "batch_no": "B1"},
			{"description": "Spare parts", "quantity": 5, "unit_value": 20},
		])
		self.assertEqual((sh.lines[0].description, sh.lines[0].uom, sh.lines[0].line_value), ("Medicine 1", "BOX", 300))
		frappe.get_doc({"doctype": "IQ Cost Line", "shipment": sh.name, "cost_category": "Freight", "cost_status": "Actual",
			"currency": "USD", "amount": 4, "cost_date": today()}).insert()  # 400 base
		sh.reload()
		self.assertEqual([r.allocated_cost for r in sh.lines], [300, 100])
		self.assertEqual(sh.lines[0].landed_unit_cost, 30)
		as_user(WH)
		mv_name = frappe.get_doc("IQ Shipment", sh.name).create_receipt(self.wh)
		mv = frappe.get_doc("IQ Stock Movement", mv_name)
		self.assertEqual([(r.item, r.batch_no, r.quantity) for r in mv.items], [(self.item, "B1", 10)])
		mv.items[0].quantity = 8  # two boxes short
		mv.save()
		mv.submit()
		sh.reload()
		self.assertEqual((sh.status, sh.lines[0].received_qty), ("Delivered", 8))
		run_for_organization(ORG)
		exc = frappe.get_doc("IQ Exception", {"organization": ORG, "exception_type": "Receipt Discrepancy"})
		self.assertIn("received 8 of 10", exc.description)

	def test_return_goes_on_hold_and_closes_delivery(self):
		as_user(WH)
		frappe.get_doc({"doctype": "IQ Stock Movement", "movement_type": "Receipt", "posting_date": today(), "to_warehouse": self.wh,
			"items": [{"item": self.item, "batch_no": "A", "expiry_date": add_days(today(), 100), "quantity": 20},
				{"item": self.item, "batch_no": "Z", "expiry_date": add_days(today(), 400), "quantity": 20}]}).insert().submit()
		d = frappe.get_doc({"doctype": "IQ Delivery", "recipient": "Clinic", "destination": "Adama", "from_warehouse": self.wh,
			"planned_delivery_date": today(), "items": [{"item": self.item, "quantity": 30}]}).insert()
		d.dispatch()
		d.reload()
		d.delivered_on, d.received_by, d.proof_of_delivery = today(), "Nurse", attach_csv("pod.csv", "x")
		d.items[0].delivered_qty = 26
		d.save()
		self.assertEqual(d.confirm_delivery(), "Partially Delivered")
		with self.assertRaises(frappe.ValidationError):
			d.record_return([{"item": self.item, "quantity": 31}], self.wh, "too many")
		d.record_return([{"item": self.item, "quantity": 4}], self.wh, "Not needed at the clinic")
		d.reload()
		self.assertEqual((d.status, d.items[0].returned_qty), ("Closed", 4))
		# FEFO dispatched A x20 + Z x10; returns go back to the latest-expiry batch first, on QA hold
		bal = frappe.get_doc("IQ Stock Balance", {"organization": ORG, "batch_no": "Z"})
		self.assertEqual((bal.quantity, bal.qa_status), (14, "Quarantined"))
		self.assertIn("inspect", bal.qa_hold_reason)


class TestPortalBatch1(B1Case):
	def setUp(self):
		super().setUp()
		for e in (SUP_USER, TRN_USER, OTHER_TRN_USER):
			website_user(e)
		for user, ptype, link in ((SUP_USER, "Supplier", self.sup), (TRN_USER, "Transitor", self.trn), (OTHER_TRN_USER, "Transitor", self.trn2)):
			frappe.get_doc({"doctype": "IQ Portal User", "user": user, "portal_type": ptype,
				"supplier": link if ptype == "Supplier" else None, "transitor": link if ptype == "Transitor" else None}).insert()
		self.po = frappe.get_doc({"doctype": "IQ Purchase Order", "po_number": "PO-ASN", "supplier": self.sup, "status": "Draft", "currency": "USD"}).insert().name

	def test_supplier_asn(self):
		as_user(SUP_USER)
		values = {"shipment_title": "Boxes", "transport_mode": "Air", "origin": "Delhi", "destination": "Addis", "planned_eta": add_days(today(), 9)}
		with self.assertRaises(frappe.ValidationError):
			portal.create_shipment(self.po, values, [])  # PO not confirmed yet
		portal.confirm_purchase_order(self.po)
		name = portal.create_shipment(self.po, values, [{"item_code": "MED1", "description": "Medicine", "quantity": 12, "unit_value": 3}])
		sh = frappe.get_doc("IQ Shipment", name)
		self.assertEqual((sh.supplier, sh.status, sh.created_via_portal, sh.purchase_order), (self.sup, "Booked", 1, self.po))
		self.assertEqual((sh.lines[0].item, sh.lines[0].line_value), (self.item, 36))
		portal.update_lines(name, [{"description": "Medicine", "quantity": 10}])
		self.assertEqual(len(frappe.get_doc("IQ Shipment", name).lines), 1)

	def test_transitor_customs_scope(self):
		sh = self.shipment(transitor=self.trn)
		as_user(TRN_USER)
		self.assertIsNone(portal.get_customs(sh.name))
		case = portal.save_customs(sh.name, {"customs_office": "Bole", "procedure": "Home Consumption", "declaration_number": "D-1", "lodged_date": today()},
			[{"tax_type": "VAT", "assessed_amount": 100, "paid_amount": 100, "payment_reference": "R"}])
		self.assertEqual(frappe.db.get_value("IQ Customs Case", case, "declarant"), self.trn)
		with self.assertRaises(frappe.PermissionError):
			portal.save_customs(sh.name, {"shipment": "other"})
		as_user(OTHER_TRN_USER)  # a different agent cannot see or touch it
		with self.assertRaises(frappe.PermissionError):
			portal.get_customs(sh.name)
		with self.assertRaises(frappe.PermissionError):
			portal.save_customs(sh.name, {"declaration_number": "hijack"})

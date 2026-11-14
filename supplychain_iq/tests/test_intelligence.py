from datetime import date

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, today

from supplychain_iq.api.dashboard import get_dashboard_data
from supplychain_iq.intelligence import calculations as calc
from supplychain_iq.intelligence.exceptions import run_for_organization
from supplychain_iq.tests.utils import as_user, ensure_org, purge_org_records

ORG = "_Test IQ Intel Org"
OTHER = "_Test IQ Intel Other"
USER = "iq.intel.admin@test.example"
OTHER_USER = "iq.intel.other@test.example"


class TestCalculations(UnitTestCase):
	def test_stock_cover(self):
		self.assertEqual(calc.stock_cover_months(100, 50), 2.0)
		self.assertIsNone(calc.stock_cover_months(100, 0))
		self.assertIsNone(calc.stock_cover_months(100, None))

	def test_stock_status_priority(self):
		self.assertEqual(calc.stock_status(10, 5, -1, 1, 90), "Expired")
		self.assertEqual(calc.stock_status(0, None, None, 1, 90), "Out of Stock")
		self.assertEqual(calc.stock_status(10, 0.5, 30, 1, 90), "Expiring Soon")
		self.assertEqual(calc.stock_status(10, 0.5, None, 1, 90), "Low")
		self.assertEqual(calc.stock_status(10, None, 400, 1, 90), "OK")

	def test_delay(self):
		t = date(2026, 11, 14)
		self.assertEqual(calc.shipment_delay_days(date(2026, 11, 10), None, "In Transit", t), 4)
		self.assertEqual(calc.shipment_delay_days(date(2026, 11, 10), date(2026, 11, 12), "Delivered", t), 2)
		self.assertEqual(calc.shipment_delay_days(date(2026, 11, 10), date(2026, 11, 8), "Delivered", t), 0)
		self.assertEqual(calc.shipment_delay_days(date(2026, 11, 10), None, "Cancelled", t), 0)
		self.assertEqual(calc.delay_severity(40, 14, 30), "Critical")
		self.assertEqual(calc.delay_severity(20, 14, 30), "High")
		self.assertEqual(calc.delay_severity(3, 14, 30), "Medium")


class TestExceptionEngine(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_org(ORG, users=[(USER, "Org Admin")])
		ensure_org(OTHER, users=[(OTHER_USER, "Org Admin")])

	def setUp(self):
		purge_org_records(ORG)
		purge_org_records(OTHER)
		as_user(USER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_delay_exception_lifecycle(self):
		sh = frappe.get_doc({
			"doctype": "IQ Shipment", "shipment_title": "Late cargo", "transport_mode": "Sea", "status": "In Transit",
			"origin": "A", "destination": "B", "planned_eta": add_days(today(), -20),
			"milestones": [{"milestone": "Customs Released", "planned_date": add_days(today(), -3)}],
			"documents": [{"document_type": "Packing List", "required": 1}],
		}).insert()
		self.assertEqual(sh.delay_days, 20)
		self.assertEqual(sh.milestones[0].status, "Overdue")
		self.assertEqual(sh.missing_documents, 1)

		res = run_for_organization(ORG)
		self.assertEqual(res["created"], 3)  # delay, overdue milestone, missing doc (ETA passed)
		delay = frappe.get_doc("IQ Exception", {"organization": ORG, "exception_type": "Shipment Delay"})
		self.assertEqual(delay.severity, "High")
		self.assertEqual(delay.reference_name, sh.name)
		self.assertIn("Planned ETA", delay.description)

		# running again does not duplicate
		self.assertEqual(run_for_organization(ORG)["created"], 0)

		# when the condition clears the exception auto-resolves
		sh.reload()
		sh.actual_eta = today()
		sh.status = "Delivered"
		sh.save()
		res = run_for_organization(ORG)
		self.assertEqual(res["resolved"], 3)
		self.assertEqual(frappe.db.get_value("IQ Exception", delay.name, "status"), "Resolved")

	def test_stock_rules_and_dashboard_scoping(self):
		wh = frappe.get_doc({"doctype": "IQ Warehouse", "warehouse_name": "Central"}).insert()
		item = frappe.get_doc({"doctype": "IQ Item", "item_code": "S1", "item_name": "Syrup", "uom": "BOTTLE"}).insert()
		frappe.get_doc({"doctype": "IQ Stock Balance", "item": item.name, "warehouse": wh.name, "batch_no": "OLD", "quantity": 5, "expiry_date": add_days(today(), -1)}).insert()
		frappe.get_doc({"doctype": "IQ Stock Balance", "item": item.name, "warehouse": wh.name, "batch_no": "LOW", "quantity": 5, "avg_monthly_consumption": 10, "expiry_date": add_days(today(), 365)}).insert()
		run_for_organization(ORG)
		types = set(frappe.get_all("IQ Exception", filters={"organization": ORG}, pluck="exception_type"))
		self.assertEqual(types, {"Expired Stock", "Low Stock"})

		as_user(OTHER_USER)
		frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Other", "transport_mode": "Air", "origin": "A", "destination": "B", "planned_eta": add_days(today(), 3)}).insert()
		as_user(USER)
		data = get_dashboard_data()
		self.assertEqual(data["organization"], ORG)
		self.assertEqual(data["inventory"]["stock_lines"], 2)
		self.assertEqual(data["shipments"]["active"], 0)  # other org's shipment not counted
		self.assertEqual(data["exceptions"]["open"], 2)
		# a member cannot request another organization's dashboard
		self.assertEqual(get_dashboard_data(organization=OTHER)["organization"], ORG)

	def test_resolving_requires_notes(self):
		frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Late", "transport_mode": "Sea", "status": "In Transit", "origin": "A", "destination": "B", "planned_eta": add_days(today(), -2)}).insert()
		run_for_organization(ORG)
		e = frappe.get_doc("IQ Exception", {"organization": ORG})
		e.status = "Resolved"
		with self.assertRaises(frappe.ValidationError):
			e.save()
		e.reload()
		e.status = "Resolved"
		e.resolution_notes = "Carrier confirmed new ETA"
		e.save()

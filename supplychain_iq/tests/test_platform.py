import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from supplychain_iq.api import integration
from supplychain_iq.intelligence.exceptions import run_for_organization
from supplychain_iq.tests.test_compliance import purge
from supplychain_iq.tests.test_operations import purge_ops
from supplychain_iq.tests.utils import as_user, ensure_org, ensure_package

ORG = "_Test IQ Platform Org"
OTHER = "_Test IQ Platform Other"
ADMIN = "iq.plat.admin@test.example"
LOGI = "iq.plat.logistics@test.example"
VIEWER = "iq.plat.viewer@test.example"
OTHER_ADMIN = "iq.plat.other@test.example"


class PlatCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_org(ORG, package="IQ Enterprise", users=[(ADMIN, "Org Admin"), (LOGI, "Logistics Officer"), (VIEWER, "Viewer")])
		ensure_org(OTHER, package="IQ Enterprise", users=[(OTHER_ADMIN, "Org Admin")])

	def setUp(self):
		for org in (ORG, OTHER):
			for n in frappe.get_all("IQ Integration Connection", filters={"organization": org}, pluck="name"):
				frappe.delete_doc("IQ Integration Connection", n, force=True, ignore_permissions=True)
			purge_ops(org)
			purge(org)
		frappe.db.delete("Notification Log", {"for_user": ["in", [ADMIN, LOGI, VIEWER]]})
		as_user(ADMIN)

	def tearDown(self):
		frappe.set_user("Administrator")


class TestAudit(PlatCase):
	def test_events_are_recorded_and_append_only(self):
		sup = frappe.get_doc({"doctype": "IQ Supplier", "supplier_name": "Audited"}).insert()
		sup.country = "Kenya"
		sup.save()
		events = frappe.get_all("IQ Audit Event", filters={"reference_name": sup.name}, fields=["name", "action", "summary", "user", "organization"], order_by="creation asc")
		self.assertEqual([e.action for e in events], ["Create", "Update"])
		self.assertIn("Country: - -> Kenya", events[1].summary)
		self.assertEqual((events[1].user, events[1].organization), (ADMIN, ORG))
		frappe.set_user("Administrator")
		ev = frappe.get_doc("IQ Audit Event", events[0].name)
		ev.summary = "tampered"
		with self.assertRaises(frappe.PermissionError):
			ev.save()
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("IQ Audit Event", ev.name, ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "IQ Audit Event", "action": "Create", "summary": "fake"}).insert(ignore_permissions=True)

	def test_visibility(self):
		frappe.get_doc({"doctype": "IQ Supplier", "supplier_name": "Mine"}).insert()
		as_user(OTHER_ADMIN)
		frappe.get_doc({"doctype": "IQ Supplier", "supplier_name": "Theirs"}).insert()
		as_user(ADMIN)
		orgs = {e.organization for e in frappe.get_list("IQ Audit Event", fields=["organization"])}
		self.assertEqual(orgs, {ORG})
		as_user(VIEWER)
		self.assertEqual(frappe.get_list("IQ Audit Event", ignore_permissions=False) if frappe.has_permission("IQ Audit Event", "read") else [], [])


class TestIntegration(PlatCase):
	def connect(self, **kw):
		conn = frappe.get_doc({"doctype": "IQ Integration Connection", "connection_name": "SAP", "system_type": "SAP", "create_missing_masters": 1, **kw}).insert()
		creds = conn.generate_credentials()
		conn.reload()
		self.assertEqual(conn.api_key, creds["api_key"])
		self.assertTrue(creds["api_secret"])
		return conn

	def test_purchase_order_upsert_is_idempotent(self):
		conn = self.connect()
		as_user(conn.integration_user)
		res = integration.upsert_purchase_orders([
			{"external_id": "4500001", "po_number": "4500001", "supplier": "Acme", "currency": "usd", "total_value": 100},
			{"external_id": "4500002", "po_number": "", "supplier": "Acme"},
			{"po_number": "x"},
		])
		self.assertEqual((res["status"], res["created"], len(res["errors"])), ("Partial", 1, 2))
		res = integration.upsert_purchase_orders([{"external_id": "4500001", "po_number": "4500001", "supplier": "Acme", "status": "Shipped"}])
		self.assertEqual((res["created"], res["updated"]), (0, 1))
		frappe.set_user("Administrator")
		po = frappe.get_doc("IQ Purchase Order", {"organization": ORG, "external_id": "4500001"})
		self.assertEqual((po.status, po.external_system), ("Shipped", conn.name))
		self.assertEqual(frappe.db.count("IQ Integration Log", {"connection": conn.name}), 2)
		self.assertTrue(frappe.db.exists("IQ Audit Event", {"reference_name": po.name, "action": "Integration"}))

	def test_shipments_and_stock(self):
		conn = self.connect()
		as_user(conn.integration_user)
		rec = {"external_id": "DLV-9", "shipment_title": "Kits", "transport_mode": "sea", "origin": "Mumbai", "destination": "Addis", "planned_eta": add_days(today(), 20)}
		self.assertEqual(integration.upsert_shipments([rec])["created"], 1)
		rec["planned_eta"] = add_days(today(), 25)
		self.assertEqual(integration.upsert_shipments([rec])["updated"], 1)
		bad = integration.upsert_shipments([{"external_id": "DLV-10", "shipment_title": "X", "transport_mode": "boat", "origin": "A", "destination": "B", "planned_eta": today()}])
		self.assertIn("transport_mode", bad["errors"][0]["error"])
		res = integration.upsert_stock_counts([{"external_id": "S1", "item_code": "ORS", "uom": "EA", "warehouse": "Central", "quantity": 40, "batch_no": "L1"}])
		self.assertEqual(res["created"], 1, res)
		frappe.set_user("Administrator")
		sh = frappe.get_doc("IQ Shipment", {"organization": ORG, "external_id": "DLV-9"})
		self.assertEqual(str(sh.planned_eta), add_days(today(), 25))
		self.assertEqual(frappe.db.get_value("IQ Stock Ledger Entry", {"organization": ORG, "entry_type": "Stock Count (Integration)"}, "qty_change"), 40)

	def test_access_rules(self):
		conn = self.connect(allow_stock=0)
		as_user(conn.integration_user)
		with self.assertRaises(frappe.PermissionError):
			integration.upsert_stock_counts([{"external_id": "S"}])
		self.assertFalse(frappe.has_permission("IQ Shipment", "read"))  # API user has no desk access
		as_user(ADMIN)
		conn.enabled = 0
		conn.save()
		self.assertEqual(frappe.db.get_value("User", conn.integration_user, "enabled"), 0)
		as_user(conn.integration_user)
		with self.assertRaises(frappe.PermissionError):
			integration.upsert_purchase_orders([])
		as_user(ADMIN)
		ensure_package("_Test No ERP", ["Shipment Control Tower", "Unified Dashboard"])
		ensure_org(OTHER, package="_Test No ERP", users=[(OTHER_ADMIN, "Org Admin")])
		as_user(OTHER_ADMIN)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "IQ Integration Connection", "connection_name": "X", "system_type": "Other"}).insert()
		ensure_org(OTHER, package="IQ Enterprise", users=[(OTHER_ADMIN, "Org Admin")])


class TestNotifications(PlatCase):
	def test_high_exception_and_assignment(self):
		frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Very late", "transport_mode": "Sea", "status": "In Transit",
			"origin": "A", "destination": "B", "planned_eta": add_days(today(), -40)}).insert()
		run_for_organization(ORG)
		subjects = lambda u: frappe.get_all("Notification Log", filters={"for_user": u}, pluck="subject")  # noqa: E731
		self.assertTrue(any("Very late" in s for s in subjects(LOGI)))
		self.assertTrue(any("Very late" in s for s in subjects(ADMIN)))
		self.assertFalse(subjects(VIEWER))
		exc = frappe.get_doc("IQ Exception", {"organization": ORG, "exception_type": "Shipment Delay"})
		exc.assigned_to = VIEWER
		exc.save()
		self.assertTrue(any(s.startswith("Assigned to you") for s in subjects(VIEWER)))

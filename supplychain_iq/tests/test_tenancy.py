import frappe
from frappe.tests import IntegrationTestCase

from supplychain_iq.entitlements import EntitlementError, UsageLimitError
from supplychain_iq.tests.utils import as_user, ensure_org, ensure_package, purge_org_records

A, B = "_Test IQ Org A", "_Test IQ Org B"
UA, UB = "iq.a.admin@test.example", "iq.b.admin@test.example"
UA_VIEW = "iq.a.viewer@test.example"


def _shipment(**kw):
	return frappe.get_doc({
		"doctype": "IQ Shipment", "shipment_title": "Test cargo", "transport_mode": "Sea",
		"origin": "Djibouti Port", "destination": "Addis Ababa", "planned_eta": "2030-01-10", **kw,
	})


class TestTenantIsolation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_org(A, users=[(UA, "Org Admin"), (UA_VIEW, "Viewer")])
		ensure_org(B, users=[(UB, "Org Admin")])

	def setUp(self):
		purge_org_records(A)
		purge_org_records(B)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_organization_is_stamped_from_user(self):
		as_user(UA)
		doc = _shipment().insert()
		self.assertEqual(doc.organization, A)

	def test_user_cannot_read_other_org_records(self):
		as_user(UB)
		b_ship = _shipment(shipment_title="B secret cargo").insert()
		as_user(UA)
		names = frappe.get_list("IQ Shipment", pluck="name")
		self.assertNotIn(b_ship.name, names)
		self.assertFalse(frappe.has_permission("IQ Shipment", "read", doc=b_ship.name))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("IQ Shipment", b_ship.name).check_permission("read")

	def test_report_query_is_filtered(self):
		as_user(UB)
		_shipment().insert()
		as_user(UA)
		_shipment().insert()
		rows = frappe.get_list("IQ Shipment", fields=["organization"], distinct=True)
		self.assertEqual({r.organization for r in rows}, {A})

	def test_cannot_write_into_other_org(self):
		as_user(UA)
		with self.assertRaises(frappe.PermissionError):
			_shipment(organization=B).insert()

	def test_cannot_link_other_org_master(self):
		as_user(UB)
		sup_b = frappe.get_doc({"doctype": "IQ Supplier", "supplier_name": "B Supplier"}).insert()
		as_user(UA)
		with self.assertRaises(frappe.PermissionError):
			_shipment(supplier=sup_b.name).insert()

	def test_viewer_cannot_create(self):
		as_user(UA_VIEW)
		with self.assertRaises(frappe.PermissionError):
			_shipment().insert()

	def test_org_admin_cannot_change_package(self):
		as_user(UA)
		org = frappe.get_doc("IQ Organization", A)
		org.package = "IQ Enterprise"
		with self.assertRaises(frappe.PermissionError):
			org.save()

	def test_org_admin_sees_only_own_organization(self):
		as_user(UA)
		self.assertEqual(frappe.get_list("IQ Organization", pluck="name"), [A])

	def test_user_in_one_org_only(self):
		frappe.set_user("Administrator")
		org = frappe.get_doc("IQ Organization", B)
		org.append("members", {"user": UA, "iq_role": "Viewer"})
		with self.assertRaises(frappe.ValidationError):
			org.save()

	def test_roles_synced_from_membership(self):
		roles = frappe.get_roles(UA_VIEW)
		self.assertIn("IQ Viewer", roles)
		self.assertNotIn("IQ Org Admin", roles)


class TestEntitlements(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_package("_Test Shipments Only", ["Shipment Control Tower", "Unified Dashboard"], max_shipments=2, max_users=3)
		ensure_org(A, package="_Test Shipments Only", users=[(UA, "Org Admin")])

	@classmethod
	def tearDownClass(cls):
		ensure_org(A, users=[(UA, "Org Admin"), (UA_VIEW, "Viewer")])
		super().tearDownClass()

	def setUp(self):
		purge_org_records(A)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_module_not_in_package_is_blocked(self):
		as_user(UA)
		with self.assertRaises(EntitlementError):
			frappe.get_doc({"doctype": "IQ Warehouse", "warehouse_name": "WH"}).insert()

	def test_multimodal_requires_module(self):
		as_user(UA)
		legs = [
			{"sequence": 1, "mode": "Sea", "origin": "X", "destination": "Djibouti"},
			{"sequence": 2, "mode": "Rail", "origin": "Djibouti", "destination": "Modjo"},
		]
		with self.assertRaises(frappe.ValidationError):
			_shipment(legs=legs).insert()

	def test_shipment_usage_limit(self):
		as_user(UA)
		_shipment().insert()
		_shipment().insert()
		with self.assertRaises(UsageLimitError):
			_shipment().insert()
		# closed shipments do not count towards the active limit
		frappe.set_user("Administrator")
		first = frappe.get_all("IQ Shipment", filters={"organization": A}, pluck="name")[0]
		frappe.db.set_value("IQ Shipment", first, "status", "Closed")
		as_user(UA)
		_shipment().insert()

	def test_suspended_subscription_blocks_writes_and_reads(self):
		as_user(UA)
		doc = _shipment().insert()
		ensure_org(A, package="_Test Shipments Only", users=[(UA, "Org Admin")], status="Suspended")
		as_user(UA)
		with self.assertRaises(EntitlementError):
			_shipment().insert()
		self.assertFalse(frappe.has_permission("IQ Shipment", "read", doc=doc.name))
		ensure_org(A, package="_Test Shipments Only", users=[(UA, "Org Admin")])

	def test_user_limit(self):
		frappe.set_user("Administrator")
		org = frappe.get_doc("IQ Organization", A)
		for i in range(4):
			email = f"iq.limit{i}@test.example"
			if not frappe.db.exists("User", email):
				frappe.get_doc({"doctype": "User", "email": email, "first_name": "L", "send_welcome_email": 0}).insert()
			org.append("members", {"user": email, "iq_role": "Viewer"})
		with self.assertRaises(UsageLimitError):
			org.save()

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from supplychain_iq.documents_store import section_summary
from supplychain_iq.intelligence.exceptions import run_for_organization
from supplychain_iq.tests.test_compliance import purge
from supplychain_iq.tests.utils import as_user, attach_csv, ensure_org

ORG = "_Test IQ DocStore Org"
OTHER = "_Test IQ DocStore Other"
ADMIN = "iq.ds.admin@test.example"
LOGI = "iq.ds.logistics@test.example"
PROT = "iq.ds.protocol@test.example"
OTHER_ADMIN = "iq.ds.other@test.example"


class TestDocumentStore(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_org(ORG, package="IQ Enterprise", users=[(ADMIN, "Org Admin"), (LOGI, "Logistics Officer"), (PROT, "Protocol Officer")])
		ensure_org(OTHER, package="IQ Enterprise", users=[(OTHER_ADMIN, "Org Admin")])
		frappe.db.set_value("IQ Organization", ORG, {"organization_type": "NGO / INGO / UN-related", "enable_diplomatic_id": 1})

	def setUp(self):
		for org in (ORG, OTHER):
			for n in frappe.get_all("IQ Document", filters={"organization": org}, pluck="name"):
				frappe.delete_doc("IQ Document", n, force=True, ignore_permissions=True)
			purge(org)
		as_user(LOGI)

	def tearDown(self):
		frappe.set_user("Administrator")

	def doc(self, **kw):
		return frappe.get_doc({"doctype": "IQ Document", "title": "Contract", "section": "Procurement & Contracts",
			"file": attach_csv("c.csv", "x"), **kw}).insert()

	def test_sections_expiry_and_exception(self):
		d = self.doc(expiry_date=add_days(today(), 10))
		self.assertEqual((d.validity_status, d.uploaded_by, d.restricted), ("Expiring Soon", LOGI, 0))
		self.assertEqual(self.doc(title="Policy", section="General").validity_status, "No Expiry")
		self.assertEqual(section_summary()["Procurement & Contracts"], {"total": 1, "expiring": 1, "expired": 0})
		run_for_organization(ORG)
		self.assertTrue(frappe.db.exists("IQ Exception", {"organization": ORG, "exception_type": "Document Expiry", "reference_name": d.name}))

	def test_auto_filing_from_shipment(self):
		url = attach_csv("bl.csv", "bl")
		sh = frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Kits", "transport_mode": "Sea", "origin": "A", "destination": "B",
			"planned_eta": today(), "documents": [{"document_type": "Bill of Lading", "attachment": url},
				{"document_type": "Customs Declaration", "attachment": attach_csv("dec.csv", "d")}]}).insert()
		sh.save()  # saving again must not duplicate
		docs = frappe.get_all("IQ Document", filters={"reference_name": sh.name}, fields=["section", "document_type", "auto_filed"], order_by="section")
		self.assertEqual([(d.section, d.document_type, d.auto_filed) for d in docs], [("Customs", "Customs Declaration", 1), ("Shipping", "Bill of Lading", 1)])

	def test_diplomatic_section_is_restricted(self):
		with self.assertRaises(frappe.PermissionError):
			self.doc(section="Diplomatic Affairs")
		as_user(PROT)
		d = self.doc(title="Passport copy", section="Diplomatic Affairs")
		self.assertEqual(d.restricted, 1)
		as_user(LOGI)
		self.assertNotIn(d.name, frappe.get_list("IQ Document", pluck="name"))
		self.assertFalse(frappe.has_permission("IQ Document", "read", doc=d.name))
		self.assertNotIn("Diplomatic Affairs", section_summary())

	def test_tenant_isolation_and_links(self):
		d = self.doc()
		as_user(OTHER_ADMIN)
		self.assertEqual(frappe.get_list("IQ Document", pluck="name"), [])
		other_sup = frappe.get_doc({"doctype": "IQ Supplier", "supplier_name": "Theirs"}).insert()
		as_user(LOGI)
		with self.assertRaises(frappe.PermissionError):
			self.doc(reference_doctype="IQ Supplier", reference_name=other_sup.name)
		with self.assertRaises(frappe.PermissionError):
			self.doc(reference_doctype="User", reference_name="Administrator")

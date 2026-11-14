import base64

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from supplychain_iq.api import diplomatic as dip_api
from supplychain_iq.api import portal
from supplychain_iq.diplomatic_affairs.access import has_app_permission
from supplychain_iq.entitlements import EntitlementError
from supplychain_iq.intelligence.exceptions import run_for_organization
from supplychain_iq.tests.utils import as_user, attach_csv, ensure_org, purge_org_records

ORG = "_Test IQ Compliance Org"
OTHER = "_Test IQ Compliance Other"
ADMIN = "iq.comp.admin@test.example"
COMP = "iq.comp.officer@test.example"
PROT = "iq.comp.protocol@test.example"
LOGI = "iq.comp.logistics@test.example"
VIEWER = "iq.comp.viewer@test.example"
OTHER_ADMIN = "iq.comp.other@test.example"
SUP_USER = "iq.portal.supplier@test.example"
SUP2_USER = "iq.portal.supplier2@test.example"
TRN_USER = "iq.portal.transitor@test.example"
EXTRA = ("IQ Portal User", "IQ Personal Privilege", "IQ Diplomatic ID", "IQ Diplomatic Persona", "IQ LC Case", "IQ Privilege", "IQ Transitor")


def purge(org):
	frappe.set_user("Administrator")
	for name in frappe.get_all("IQ Shipment", filters={"organization": org}, pluck="name"):
		frappe.db.set_value("IQ Shipment", name, {"privilege": None, "lc_case": None, "transitor": None})
	for dt in EXTRA:
		for name in frappe.get_all(dt, filters={"organization": org}, pluck="name"):
			frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
	purge_org_records(org)


def website_user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "Portal", "send_welcome_email": 0, "user_type": "Website User"}).insert(ignore_permissions=True)


class CompCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for e in (SUP_USER, SUP2_USER, TRN_USER):
			if frappe.db.exists("IQ Portal User", {"user": e}):
				frappe.delete_doc("IQ Portal User", frappe.db.get_value("IQ Portal User", {"user": e}), force=True, ignore_permissions=True)
		ensure_org(ORG, package="IQ Enterprise", users=[(ADMIN, "Org Admin"), (COMP, "Compliance Officer"), (PROT, "Protocol Officer"),
			(LOGI, "Logistics Officer"), (VIEWER, "Viewer")])
		ensure_org(OTHER, package="IQ Enterprise", users=[(OTHER_ADMIN, "Org Admin")])
		frappe.db.set_value("IQ Organization", ORG, {"organization_type": "NGO / INGO / UN-related", "enable_diplomatic_id": 1})
		frappe.db.set_value("IQ Organization", OTHER, {"organization_type": "Commercial Importer", "enable_diplomatic_id": 0})

	def setUp(self):
		purge(ORG)
		purge(OTHER)
		as_user(ADMIN)
		self.src = attach_csv("approval.csv", "synthetic approval")

	def tearDown(self):
		frappe.set_user("Administrator")

	def privilege(self, **kw):
		return frappe.get_doc({"doctype": "IQ Privilege", "title": "Duty-free", "privilege_type": "Duty-Free Privilege",
			"authority": "Authority", "reference_no": "REF-1", "effective_date": add_days(today(), -30),
			"expiry_date": add_days(today(), 100), "scope": "Medical supplies", "source_document": self.src, **kw}).insert()


class TestPrivileges(CompCase):
	def test_validity_never_assumed(self):
		with self.assertRaises(frappe.ValidationError):
			self.privilege(expiry_date=None)
		p = self.privilege(expiry_date=None, no_expiry_stated=1)
		self.assertEqual(p.validity_status, "No Expiry Stated")
		with self.assertRaises(frappe.ValidationError):
			self.privilege(conditions=[{"condition_type": "Legal Rule", "condition_text": "x", "source_reference": " "}])

	def test_maker_checker_and_rereview(self):
		p = self.privilege()
		p.submit_for_review()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("IQ Privilege", p.name).confirm()  # submitter cannot confirm
		as_user(LOGI)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("IQ Privilege", p.name).confirm()  # not a reviewer role
		as_user(COMP)
		frappe.get_doc("IQ Privilege", p.name).confirm("ok")
		doc = frappe.get_doc("IQ Privilege", p.name)
		self.assertEqual((doc.review_status, doc.reviewed_by), ("Confirmed", COMP))
		doc.review_status = "Draft"  # client cannot set review fields
		doc.save()
		self.assertEqual(frappe.db.get_value("IQ Privilege", p.name, "review_status"), "Confirmed")
		doc.reload()
		doc.expiry_date = add_days(today(), 300)  # substantive change
		doc.save()
		self.assertEqual(doc.review_status, "Draft")

	def test_shipment_conflict_exception(self):
		p = self.privilege(expiry_date=add_days(today(), 10))
		frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Kits", "transport_mode": "Sea", "origin": "A", "destination": "B",
			"planned_eta": add_days(today(), 20), "privilege": p.name}).insert()
		run_for_organization(ORG)
		e = frappe.get_doc("IQ Exception", {"organization": ORG, "exception_type": "Privilege Conflict"})
		self.assertIn("not confirmed", e.description)
		self.assertIn("after the recorded expiry", e.description)


class TestLC(CompCase):
	def test_status_deadlines_and_exception(self):
		lc = frappe.get_doc({"doctype": "IQ LC Case", "bank": "Bank", "currency": "eur", "amount": 1000,
			"latest_shipment_date": add_days(today(), 5), "expiry_date": add_days(today(), 30), "presentation_days": 21,
			"milestones": [{"event": "LC Issued", "event_date": add_days(today(), -2)}, {"event": "Submitted to Bank", "event_date": add_days(today(), -9)}]}).insert()
		self.assertEqual((lc.status, lc.currency), ("LC Issued", "EUR"))
		self.assertEqual(str(lc.next_deadline), add_days(today(), 5))
		lc.load_standard_checklist()
		lc.reload()
		self.assertTrue(len(lc.checklist) >= 5)
		run_for_organization(ORG)
		self.assertTrue(frappe.db.exists("IQ Exception", {"organization": ORG, "exception_type": "LC Deadline", "status": "Open"}))
		# shipping moves the deadline to document presentation (capped at expiry)
		frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Goods", "transport_mode": "Air", "origin": "A", "destination": "B",
			"planned_eta": today(), "actual_etd": add_days(today(), -1), "lc_case": lc.name}).insert()
		lc.reload()
		self.assertEqual(str(lc.presentation_deadline), add_days(today(), 20))
		with self.assertRaises(frappe.ValidationError):
			lc.append("milestones", {"event": "Payment Made", "event_date": add_days(today(), 3)})
			lc.save()  # future events are not allowed


class TestDiplomaticAffairs(CompCase):
	def persona(self, **kw):
		return frappe.get_doc({"doctype": "IQ Diplomatic Persona", "full_name": "Person A", "diplomatic_category": "Diplomatic Agent", **kw}).insert()

	def test_opt_in_and_org_type(self):
		as_user(OTHER_ADMIN)
		org = frappe.get_doc("IQ Organization", OTHER)
		org.enable_diplomatic_id = 1
		with self.assertRaises(frappe.ValidationError):
			org.save()  # commercial importer cannot enable
		with self.assertRaises(EntitlementError):
			frappe.get_doc({"doctype": "IQ Diplomatic Persona", "full_name": "X", "diplomatic_category": "Diplomatic Agent"}).insert()
		self.assertFalse(has_app_permission())

	def test_role_restricted_personal_data(self):
		as_user(PROT)
		p = self.persona()
		self.assertTrue(has_app_permission())
		as_user(LOGI)
		self.assertFalse(has_app_permission())
		self.assertFalse(frappe.has_permission("IQ Diplomatic Persona", "read", doc=p.name))
		with self.assertRaises(frappe.PermissionError):
			dip_api.get_data()

	def test_renewal_workflow_and_restricted_exceptions(self):
		as_user(PROT)
		p = self.persona(passport_expiry=add_days(today(), 100), assignment_end_date=add_days(today(), 30))
		d = frappe.get_doc({"doctype": "IQ Diplomatic ID", "persona": p.name, "employee_name": "x", "expiry_date": add_days(today(), 20)}).insert()
		self.assertEqual((d.employee_name, d.id_status), ("Person A", "Renewal Due"))
		run_for_organization(ORG)
		types = set(frappe.get_all("IQ Exception", filters={"organization": ORG, "restricted": 1}, pluck="exception_type"))
		self.assertTrue({"Diplomatic ID Renewal", "Passport Expiry", "Departure Close-out"} <= types)
		as_user(VIEWER)  # restricted exceptions are hidden from other roles
		self.assertEqual(frappe.get_list("IQ Exception", filters={"restricted": 1}), [])
		as_user(PROT)
		d.load_standard_requirements()
		d.reload()
		d.renewal_status = "Preparing Documents"
		d.save()
		d.renewal_status = "Internal Review Complete"
		with self.assertRaises(frappe.ValidationError):
			d.save()  # documents not received
		d.reload()
		for r in d.requirements:
			r.received = 1
		d.renewal_status = "Internal Review Complete"
		d.save()
		d.renewal_status, d.submission_reference, d.submission_date, d.next_follow_up = "Submitted", "SUB-1", today(), add_days(today(), 7)
		d.save()
		d.renewal_status, d.approval_date = "Approved", today()
		d.save()
		d.renewal_status, d.collected_on, d.new_expiry_date = "Collected", today(), add_days(today(), 365)
		d.save()
		self.assertEqual(str(d.expiry_date), add_days(today(), 365))
		self.assertEqual(str(d.previous_expiry_date), add_days(today(), 20))
		d.renewal_status = "Submitted"
		with self.assertRaises(frappe.ValidationError):
			d.save()  # cannot move backwards

	def test_personal_privilege_quota(self):
		as_user(PROT)
		p = self.persona()
		pp = frappe.get_doc({"doctype": "IQ Personal Privilege", "persona": p.name, "privilege_type": "Vehicle Duty-Free Import",
			"authority": "A", "reference_no": "R", "effective_date": add_days(today(), -10), "no_expiry_stated": 1,
			"entitlement": "One vehicle", "quota_value": 1, "quota_unit": "vehicle", "source_document": self.src,
			"utilisations": [{"use_date": today(), "description": "Car", "value_used": 1}]}).insert()
		self.assertEqual((pp.used_value, pp.remaining_value, pp.quota_used_pct), (1, 0, 100))
		pp.append("utilisations", {"use_date": today(), "description": "Second car", "value_used": 1})
		with self.assertRaises(frappe.ValidationError):
			pp.save()
		self.assertEqual(frappe.db.get_value("IQ Diplomatic Persona", p.name, "active_privileges"), 1)


class TestPortals(CompCase):
	def setUp(self):
		super().setUp()
		for e in (SUP_USER, SUP2_USER, TRN_USER):
			website_user(e)
		self.sup = frappe.get_doc({"doctype": "IQ Supplier", "supplier_name": "Sup One"}).insert().name
		self.sup2 = frappe.get_doc({"doctype": "IQ Supplier", "supplier_name": "Sup Two"}).insert().name
		self.trn = frappe.get_doc({"doctype": "IQ Transitor", "transitor_name": "Agent One"}).insert().name
		for user, ptype, link in ((SUP_USER, "Supplier", self.sup), (SUP2_USER, "Supplier", self.sup2), (TRN_USER, "Transitor", self.trn)):
			frappe.get_doc({"doctype": "IQ Portal User", "user": user, "portal_type": ptype,
				"supplier": link if ptype == "Supplier" else None, "transitor": link if ptype == "Transitor" else None}).insert()
		self.po = frappe.get_doc({"doctype": "IQ Purchase Order", "po_number": "PO-9", "supplier": self.sup, "status": "Draft"}).insert().name
		self.ship = frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Cargo", "transport_mode": "Sea", "origin": "A",
			"destination": "B", "planned_eta": add_days(today(), 10), "supplier": self.sup, "transitor": self.trn,
			"documents": [{"document_type": "Packing List", "required": 1}]}).insert().name

	def test_portal_users_get_no_desk_access(self):
		self.assertIn("IQ Supplier Portal", frappe.get_roles(SUP_USER))
		self.assertEqual(frappe.db.get_value("User", SUP_USER, "user_type"), "Website User")
		as_user(SUP_USER)
		self.assertFalse(frappe.has_permission("IQ Shipment", "read"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("IQ Purchase Order")
		as_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):  # staff cannot also be portal users
			frappe.get_doc({"doctype": "IQ Portal User", "user": COMP, "portal_type": "Transitor", "transitor": self.trn}).insert()

	def test_supplier_scope_and_actions(self):
		as_user(SUP_USER)
		data = portal.get_portal_data()
		self.assertEqual([s.name for s in data["shipments"]], [self.ship])
		self.assertEqual([p.name for p in data["purchase_orders"]], [self.po])
		portal.confirm_purchase_order(self.po, add_days(today(), 7))
		self.assertEqual(frappe.db.get_value("IQ Purchase Order", self.po, "status"), "Confirmed")
		portal.update_shipment(self.ship, {"actual_etd": today(), "awb_bl_number": "BL-77"})
		with self.assertRaises(frappe.PermissionError):
			portal.update_shipment(self.ship, {"planned_eta": today()})  # not a supplier field
		with self.assertRaises(frappe.PermissionError):
			portal.set_milestone(self.ship, "Customs Released", today())  # transitor milestone
		content = "data:text/csv;base64," + base64.b64encode(b"item,qty\nORS,10\n").decode()
		portal.upload_document(self.ship, "Packing List", "pl.csv", content)
		self.assertEqual(frappe.db.get_value("IQ Shipment", self.ship, "missing_documents"), 0)
		with self.assertRaises(frappe.ValidationError):
			portal.upload_document(self.ship, "Packing List", "evil.exe", content)
		comments = frappe.get_all("Comment", filters={"reference_name": self.ship, "comment_type": "Info"}, pluck="content")
		self.assertTrue(any("Supplier portal" in c for c in comments))
		as_user(SUP2_USER)  # another supplier sees nothing of this
		self.assertEqual(portal.get_portal_data()["shipments"], [])
		with self.assertRaises(frappe.PermissionError):
			portal.get_shipment(self.ship)
		with self.assertRaises(frappe.PermissionError):
			portal.confirm_purchase_order(self.po)

	def test_transitor_actions_and_cost_submission(self):
		frappe.get_doc({"doctype": "IQ Exchange Rate", "from_currency": "USD", "rate": 100, "rate_date": add_days(today(), -5), "source": "Commercial Bank"}).insert()
		as_user(TRN_USER)
		portal.set_milestone(self.ship, "Customs Declaration Lodged", today())
		portal.update_shipment(self.ship, {"status": "Customs Clearance", "free_time_start": today()})
		with self.assertRaises(frappe.ValidationError):
			portal.update_shipment(self.ship, {"status": "Delivered"})
		content = base64.b64encode(b"invoice").decode()
		name = portal.submit_cost(self.ship, "Customs Clearance", "USD", 250, "INV-1", today(), "inv.csv", content)
		line = frappe.get_doc("IQ Cost Line", name)
		self.assertEqual((line.cost_status, line.vendor, line.amount_base), ("Estimate", "Agent One", 25000))
		as_user(ADMIN)
		frappe.db.set_value("IQ Portal User", {"user": TRN_USER}, "is_active", 0)
		frappe.get_doc("IQ Portal User", {"user": TRN_USER}).save()
		self.assertNotIn("IQ Transitor Portal", frappe.get_roles(TRN_USER))
		as_user(TRN_USER)
		with self.assertRaises(frappe.PermissionError):
			portal.get_portal_data()

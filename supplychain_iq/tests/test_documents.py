import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, today

from supplychain_iq.intake import documents
from supplychain_iq.tests.test_compliance import purge
from supplychain_iq.tests.utils import as_user, ensure_org

ORG = "_Test IQ Docs Org"
ADMIN = "iq.docs.admin@test.example"


def make_pdf(lines: list[str]) -> bytes:
	"""Minimal one-page PDF with a real text layer (for extraction tests)."""
	text_ops = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join(
		"(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for line in lines
	) + " ET"
	objs = [
		"<< /Type /Catalog /Pages 2 0 R >>",
		"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
		f"<< /Length {len(text_ops)} >>\nstream\n{text_ops}\nendstream",
		"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
	]
	out, offsets = b"%PDF-1.4\n", []
	for i, o in enumerate(objs, start=1):
		offsets.append(len(out))
		out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
	xref = len(out)
	out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
	out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
	out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
	return out


def attach(name, content):
	f = frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 1})
	f.flags.ignore_permissions = True
	f.insert()
	return f.file_url


class TestIdentifiers(UnitTestCase):
	def test_check_digits(self):
		self.assertTrue(documents.iso6346_valid("CSQU3054383"))
		self.assertFalse(documents.iso6346_valid("CSQU3054384"))
		self.assertTrue(documents.awb_valid("176-12345675"))
		self.assertFalse(documents.awb_valid("176-12345676"))

	def test_awb_extraction_only_trusts_valid_numbers(self):
		fields = documents.extract("Air Waybill", ["AIR WAYBILL\nAWB No: 176-1234 5675\nExecuted on: 2026-11-02\nPort of Loading: Brussels\n"])
		awb = next(f for f in fields if f["field_key"] == "awb_bl_number")
		self.assertEqual((awb["value"], awb["confidence"]), ("176-12345675", "High"))


class TestExtraction(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_org(ORG, package="IQ Enterprise", users=[(ADMIN, "Org Admin")])

	def setUp(self):
		for n in frappe.get_all("IQ Document Extraction", filters={"organization": ORG}, pluck="name"):
			frappe.delete_doc("IQ Document Extraction", n, force=True, ignore_permissions=True)
		purge(ORG)
		as_user(ADMIN)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_pdf_invoice_confirm_and_apply(self):
		sh = frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Kits", "transport_mode": "Sea", "origin": "A", "destination": "B",
			"planned_eta": add_days(today(), 10), "documents": [{"document_type": "Commercial Invoice", "required": 1}]}).insert()
		url = attach("invoice.pdf", make_pdf(["COMMERCIAL INVOICE", "Invoice No: INV-77", "Invoice Date: 03/11/2026",
			"Port of Loading: Mumbai", "Terms: CIF Djibouti", "Grand Total: USD 12,500.00"]))
		x = frappe.get_doc({"doctype": "IQ Document Extraction", "document_type": "Commercial Invoice", "source_file": url, "shipment": sh.name}).insert()
		self.assertGreaterEqual(x.extract(), 4)
		x.reload()
		values = {f.field_key: f.value for f in x.fields}
		self.assertEqual((values["invoice_number"], values["cargo_value"], values["currency"], values["incoterm"]), ("INV-77", "12500.00", "USD", "CIF"))
		with self.assertRaises(frappe.ValidationError):
			x.apply()  # nothing confirmed yet
		for f in x.fields:
			f.confirmed = 1 if f.field_key in ("cargo_value", "currency", "incoterm") else 0
		x.save()
		x.apply()
		sh.reload()
		self.assertEqual((sh.cargo_value, sh.currency, sh.incoterm, sh.origin), (12500, "USD", "CIF", "A"))  # unconfirmed origin untouched
		self.assertEqual(sh.missing_documents, 0)
		x.reload()
		self.assertEqual(x.status, "Applied")
		x.fields[0].value = "changed"
		with self.assertRaises(frappe.ValidationError):
			x.save()  # closed

	def test_scanned_pdf_and_privilege_draft(self):
		url = attach("scan.pdf", make_pdf([]))
		x = frappe.get_doc({"doctype": "IQ Document Extraction", "document_type": "Bill of Lading", "source_file": url}).insert()
		self.assertEqual(x.extract(), 0)
		url = attach("approval.txt", b"Our Ref: MOF/DF/2026/118\nDate of issue: 01/09/2026\nValid until: 31/12/2026\n")
		x = frappe.get_doc({"doctype": "IQ Document Extraction", "document_type": "Duty-Free Privilege Approval", "source_file": url}).insert()
		x.extract()
		x.reload()
		for f in x.fields:
			f.confirmed = 1
		x.save()
		name = x.apply()
		p = frappe.get_doc("IQ Privilege", name)
		self.assertEqual((p.reference_no, str(p.expiry_date), p.review_status), ("MOF/DF/2026/118", "2026-12-31", "Draft"))

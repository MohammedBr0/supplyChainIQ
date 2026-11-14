from datetime import date

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, today

from supplychain_iq.intake.dates import DateParseError, ethiopian_to_gregorian, parse_date
from supplychain_iq.intake.mapping import detect_mapping, missing_required
from supplychain_iq.tests.utils import as_user, attach_csv, ensure_org, purge_org_records

ORG = "_Test IQ Intake Org"
USER = "iq.intake.wh@test.example"


class TestDates(UnitTestCase):
	def test_ethiopian_new_year(self):
		self.assertEqual(ethiopian_to_gregorian(2017, 1, 1), date(2024, 9, 11))
		self.assertEqual(ethiopian_to_gregorian(2016, 1, 1), date(2023, 9, 12))
		self.assertEqual(ethiopian_to_gregorian(2015, 13, 6), date(2023, 9, 11))

	def test_ethiopian_invalid_pagume(self):
		with self.assertRaises(DateParseError):
			ethiopian_to_gregorian(2016, 13, 6)

	def test_formats(self):
		self.assertEqual(parse_date("2026-12-31"), date(2026, 12, 31))
		self.assertEqual(parse_date("03/04/2026"), date(2026, 4, 3))  # day-first
		self.assertEqual(parse_date("31.12.2026"), date(2026, 12, 31))
		self.assertEqual(parse_date(46000), date(2025, 12, 9))  # Excel serial
		self.assertEqual(parse_date("01/01/2017", "Ethiopian"), date(2024, 9, 11))
		self.assertIsNone(parse_date(""))
		with self.assertRaises(DateParseError):
			parse_date("next tuesday")


class TestMapping(UnitTestCase):
	def test_exact_and_fuzzy(self):
		mapping, _notes, fuzzy = detect_mapping(["SKU", "Store", "Qty on hand", "Expiry", "Colour"], "Existing Stock")
		self.assertEqual(mapping["SKU"], "item_code")
		self.assertEqual(mapping["Store"], "warehouse")
		self.assertEqual(mapping["Qty on hand"], "quantity")
		self.assertEqual(mapping["Expiry"], "expiry_date")
		self.assertIsNone(mapping["Colour"])
		self.assertEqual(fuzzy, ["Qty on hand"])
		self.assertEqual(missing_required(mapping, "Existing Stock"), [])

	def test_missing_required(self):
		mapping, _n, _f = detect_mapping(["Item", "Qty"], "Existing Stock")
		self.assertEqual(missing_required(mapping, "Existing Stock"), ["warehouse"])


class TestStockImport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_org(ORG, users=[(USER, "Warehouse Officer")])

	def setUp(self):
		purge_org_records(ORG)
		as_user(USER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _batch(self, csv_text, **kw):
		url = attach_csv("stock.csv", csv_text)
		return frappe.get_doc({"doctype": "IQ Import Batch", "import_type": "Existing Stock", "source_file": url, **kw}).insert()

	def test_errors_block_import(self):
		csv_text = (
			"Item Code,Warehouse,Quantity,UOM,Batch No,Expiry Date\n"
			"A1,Main,10,EA,B1,2030-01-01\n"
			"A2,Main,-5,EA,B1,2030-01-01\n"
			"A1,Main,3,EA,B1,2030-01-01\n"
			"A3,Main,abc,EA,,not a date\n"
		)
		b = self._batch(csv_text, create_missing_masters=1)
		b.validate_file()
		b.reload()
		self.assertEqual(b.status, "Has Errors")
		self.assertEqual(b.total_rows, 4)
		self.assertEqual(b.error_rows, 3)
		msgs = {r.row_number: r.messages for r in b.rows}
		self.assertIn("negative", msgs[3])
		self.assertIn("duplicate of row 2", msgs[4])
		self.assertIn("not a number", msgs[5])
		with self.assertRaises(frappe.ValidationError):
			b.confirm_import()
		self.assertFalse(frappe.db.exists("IQ Stock Balance", {"organization": ORG}))

	def test_unknown_masters_without_create_flag(self):
		b = self._batch("Item Code,Warehouse,Quantity,UOM\nX1,Nowhere,5,EA\n")
		b.validate_file()
		b.reload()
		self.assertEqual(b.status, "Has Errors")
		self.assertIn("not found", b.rows[0].messages)

	def test_valid_import_creates_and_updates(self):
		exp = add_days(today(), 30)
		csv_text = (
			"Item Code,Item Name,UOM,Warehouse,Quantity,Batch No,Expiry Date,AMC\n"
			f"M1,Med one,pcs,Central,100,LOT1,{exp},50\n"
			"M2,Med two,EA,Central,0,,,\n"
		)
		b = self._batch(csv_text, create_missing_masters=1)
		b.validate_file()
		b.reload()
		self.assertEqual(b.status, "Validated", b.validation_summary)
		self.assertEqual(b.warning_rows, 2)  # master creation warnings
		self.assertFalse(frappe.db.exists("IQ Stock Balance", {"organization": ORG}))  # staged only
		res = b.confirm_import()
		self.assertEqual(res, {"created": 2, "updated": 0})
		b.reload()
		self.assertEqual(b.status, "Imported")
		self.assertEqual(b.imported_by, USER)

		item = frappe.db.get_value("IQ Item", {"organization": ORG, "item_code": "M1"}, ["name", "uom"], as_dict=True)
		self.assertEqual(item.uom, "EA")  # pcs normalized
		bal = frappe.get_doc("IQ Stock Balance", {"organization": ORG, "item": item.name})
		self.assertEqual(bal.stock_cover_months, 2.0)
		self.assertTrue(bal.cover_available)
		self.assertEqual(bal.stock_status, "Expiring Soon")
		self.assertEqual(bal.source_import, b.name)
		m2 = frappe.get_doc("IQ Stock Balance", {"organization": ORG, "item": frappe.db.get_value("IQ Item", {"organization": ORG, "item_code": "M2"})})
		self.assertFalse(m2.cover_available)  # no consumption -> no cover invented
		self.assertEqual(m2.stock_status, "Out of Stock")

		# re-importing the same item/warehouse/batch updates instead of duplicating
		b2 = self._batch("Item Code,Warehouse,Quantity,Batch No,AMC\nM1,Central,40,LOT1,20\n")
		b2.validate_file()
		self.assertEqual(b2.confirm_import(), {"created": 0, "updated": 1})
		self.assertEqual(frappe.db.get_value("IQ Stock Balance", bal.name, "quantity"), 40)

		# imported batches are immutable
		b.reload()
		b.date_calendar = "Ethiopian"
		with self.assertRaises(frappe.ValidationError):
			b.save()

	def test_fuzzy_mapping_needs_confirmation(self):
		b = self._batch("Item Code,Warehouse,Qty on hand,UOM\nF1,Central,5,EA\n", create_missing_masters=1)
		b.validate_file()
		b.reload()
		self.assertEqual(b.status, "Validated")
		with self.assertRaises(frappe.ValidationError):
			b.confirm_import()
		b.reload()
		b.mapping_confirmed = 1
		b.save()
		b.confirm_import()
		self.assertTrue(frappe.db.exists("IQ Stock Balance", {"organization": ORG}))

	def test_status_cannot_be_forced_by_client(self):
		b = self._batch("Item Code,Warehouse,Quantity\nZ,Central,1\n")
		b.status = "Validated"
		b.save()
		self.assertEqual(b.status, "Draft")

	def test_ethiopian_calendar_dates(self):
		b = self._batch("Item Code,Warehouse,Quantity,UOM,Expiry Date\nE1,Central,5,EA,01/01/2025\n", create_missing_masters=1, date_calendar="Ethiopian")
		b.validate_file()
		b.confirm_import()
		exp = frappe.db.get_value("IQ Stock Balance", {"organization": ORG}, "expiry_date")
		self.assertEqual(str(exp), "2032-09-11")


class TestShipmentImport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_org(ORG, users=[(USER, "Org Admin")])

	def setUp(self):
		purge_org_records(ORG)
		as_user(USER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_import_and_update_by_awb(self):
		csv_text = (
			"Commodity,AWB/BL Number,Supplier,Mode,Origin,Destination,ETD,ETA,Currency,Incoterm,Status\n"
			"Kits,BL-1,New Supplier,ocean,Mumbai,Addis,2030-01-01,2030-02-01,usd,CIF,in transit\n"
			"Vaccines,AWB-2,New Supplier,Air,Brussels,Addis,2030-01-05,2030-01-04,EUR,XYZ,Booked\n"
		)
		url = attach_csv("ship.csv", csv_text)
		b = frappe.get_doc({"doctype": "IQ Import Batch", "import_type": "Inbound Shipments", "source_file": url, "create_missing_masters": 1}).insert()
		b.validate_file()
		b.reload()
		self.assertEqual(b.status, "Has Errors")  # row 3: ETA before ETD
		self.assertIn("before planned_etd", b.rows[1].messages)

		url = attach_csv("ship2.csv", "Commodity,AWB,Mode,Origin,Destination,ETA,Status\nKits,BL-1,Sea,Mumbai,Addis,2030-02-01,In Transit\n")
		b = frappe.get_doc({"doctype": "IQ Import Batch", "import_type": "Inbound Shipments", "source_file": url}).insert()
		b.validate_file()
		self.assertEqual(b.confirm_import(), {"created": 1, "updated": 0})
		url = attach_csv("ship3.csv", "Commodity,AWB,Mode,Origin,Destination,ETA,Status\nKits,BL-1,Sea,Mumbai,Addis,2030-02-03,At Port\n")
		b = frappe.get_doc({"doctype": "IQ Import Batch", "import_type": "Inbound Shipments", "source_file": url}).insert()
		b.validate_file()
		self.assertEqual(b.confirm_import(), {"created": 0, "updated": 1})
		sh = frappe.get_doc("IQ Shipment", {"organization": ORG, "awb_bl_number": "BL-1"})
		self.assertEqual(str(sh.planned_eta), "2030-02-03")
		self.assertEqual(sh.status, "At Port")

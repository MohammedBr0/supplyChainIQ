from datetime import date

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, add_to_date, flt, now_datetime, today

from supplychain_iq.api.dashboard import get_dashboard_data
from supplychain_iq.intelligence import calculations as calc
from supplychain_iq.intelligence.exceptions import run_for_organization
from supplychain_iq.tests.utils import as_user, attach_csv, ensure_org, purge_org_records

ORG = "_Test IQ Ops Org"
OTHER = "_Test IQ Ops Other"
WH_USER = "iq.ops.wh@test.example"
QA_USER = "iq.ops.qa@test.example"
ADMIN_USER = "iq.ops.admin@test.example"
OTHER_USER = "iq.ops.other@test.example"
OPS_DOCTYPES = ("IQ Delivery", "IQ Temperature Log", "IQ Stock Ledger Entry")


class TestFefo(UnitTestCase):
	def test_earliest_expiry_first_and_undated_last(self):
		batches = [
			{"batch_no": "LATE", "quantity": 10, "expiry_date": date(2027, 6, 1)},
			{"batch_no": "NONE", "quantity": 10, "expiry_date": None},
			{"batch_no": "SOON", "quantity": 5, "expiry_date": date(2026, 12, 1)},
		]
		out = calc.fefo_allocate(batches, 18)
		self.assertEqual([(a["batch_no"], a["quantity"]) for a in out], [("SOON", 5), ("LATE", 10), ("NONE", 3)])

	def test_insufficient(self):
		with self.assertRaises(calc.InsufficientStock):
			calc.fefo_allocate([{"batch_no": "A", "quantity": 2, "expiry_date": None}], 3)

	def test_qa_hold_status_wins(self):
		self.assertEqual(calc.stock_status(10, 5, 400, 1, 90, "Quarantined"), "QA Hold")


def purge_ops(org):
	frappe.set_user("Administrator")
	for name in frappe.get_all("IQ Stock Movement", filters={"organization": org, "docstatus": 1}, pluck="name"):
		frappe.db.set_value("IQ Stock Movement", name, "docstatus", 2)
	for dt in ("IQ Stock Movement", *OPS_DOCTYPES):
		for name in frappe.get_all(dt, filters={"organization": org}, pluck="name"):
			frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
	purge_org_records(org)


class OpsCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_org(ORG, package="IQ Enterprise", users=[(WH_USER, "Warehouse Officer"), (QA_USER, "QA Officer"), (ADMIN_USER, "Org Admin")])
		ensure_org(OTHER, package="IQ Enterprise", users=[(OTHER_USER, "Org Admin")])

	def setUp(self):
		purge_ops(ORG)
		purge_ops(OTHER)
		as_user(WH_USER)
		self.central = frappe.get_doc({"doctype": "IQ Warehouse", "warehouse_name": "Central"}).insert().name
		self.region = frappe.get_doc({"doctype": "IQ Warehouse", "warehouse_name": "Region"}).insert().name
		self.cold = frappe.get_doc({"doctype": "IQ Warehouse", "warehouse_name": "Cold room", "warehouse_type": "Cold Store",
			"temperature_controlled": 1, "min_temperature": 2, "max_temperature": 8}).insert().name
		self.ors = frappe.get_doc({"doctype": "IQ Item", "item_code": "ORS", "item_name": "ORS", "uom": "EA"}).insert().name
		self.vac = frappe.get_doc({"doctype": "IQ Item", "item_code": "VAC", "item_name": "Vaccine", "uom": "VIAL",
			"requires_cold_chain": 1, "min_temperature": 2, "max_temperature": 8}).insert().name

	def tearDown(self):
		frappe.set_user("Administrator")

	def move(self, mtype, rows, submit=True, **kw):
		mv = frappe.get_doc({"doctype": "IQ Stock Movement", "movement_type": mtype, "posting_date": today(), "items": rows, **kw})
		mv.insert()
		if submit:
			mv.submit()
		return mv

	def qty(self, item, warehouse, batch):
		return flt(frappe.db.get_value("IQ Stock Balance", {"organization": ORG, "item": item, "warehouse": warehouse, "batch_no": batch}, "quantity"))

	def receive_ors(self):
		return self.move("Receipt", [
			{"item": self.ors, "batch_no": "LATE", "expiry_date": add_days(today(), 400), "quantity": 100},
			{"item": self.ors, "batch_no": "SOON", "expiry_date": add_days(today(), 60), "quantity": 30},
		], to_warehouse=self.central)


class TestStockMovements(OpsCase):
	def test_receipt_posts_balances_and_ledger(self):
		mv = self.receive_ors()
		self.assertEqual(self.qty(self.ors, self.central, "LATE"), 100)
		sle = frappe.get_all("IQ Stock Ledger Entry", filters={"reference_name": mv.name}, fields=["qty_change", "balance_after", "entry_type"])
		self.assertEqual(sorted(e.qty_change for e in sle), [30, 100])
		self.assertTrue(all(e.entry_type == "Receipt" for e in sle))

	def test_issue_allocates_fefo_and_skips_expired_and_held(self):
		self.receive_ors()
		self.move("Receipt", [{"item": self.ors, "batch_no": "OLD", "expiry_date": add_days(today(), 1), "quantity": 50}], to_warehouse=self.central)
		frappe.db.set_value("IQ Stock Balance", {"organization": ORG, "batch_no": "OLD"}, "expiry_date", add_days(today(), -1))
		mv = self.move("Issue", [{"item": self.ors, "quantity": 40}], from_warehouse=self.central)
		self.assertEqual([(r.batch_no, r.quantity) for r in mv.items], [("SOON", 30), ("LATE", 10)])
		self.assertIn("FEFO", mv.allocation_note)
		self.assertEqual(self.qty(self.ors, self.central, "SOON"), 0)
		self.assertEqual(self.qty(self.ors, self.central, "OLD"), 50)  # expired stock untouched
		with self.assertRaises(frappe.ValidationError):
			self.move("Issue", [{"item": self.ors, "quantity": 91}], from_warehouse=self.central)  # 90 issuable left

	def test_cancel_reverses_and_blocks_if_consumed(self):
		rec = self.receive_ors()
		mv = self.move("Issue", [{"item": self.ors, "quantity": 20}], from_warehouse=self.central)
		mv.cancel()
		self.assertEqual(self.qty(self.ors, self.central, "SOON"), 30)
		self.assertTrue(frappe.db.get_value("IQ Stock Ledger Entry", {"reference_name": mv.name, "entry_type": "Issue"}, "is_cancelled"))
		self.move("Issue", [{"item": self.ors, "quantity": 120}], from_warehouse=self.central)
		with self.assertRaises(frappe.ValidationError):
			rec.cancel()  # would make stock negative

	def test_transfer_keeps_batch_expiry(self):
		self.receive_ors()
		self.move("Transfer", [{"item": self.ors, "quantity": 35}], from_warehouse=self.central, to_warehouse=self.region)
		self.assertEqual(self.qty(self.ors, self.region, "SOON"), 30)
		self.assertEqual(self.qty(self.ors, self.region, "LATE"), 5)
		exp = frappe.db.get_value("IQ Stock Balance", {"organization": ORG, "warehouse": self.region, "batch_no": "SOON"}, "expiry_date")
		self.assertEqual(str(exp), add_days(today(), 60))

	def test_emptied_batch_is_not_a_stock_out(self):
		self.receive_ors()
		frappe.db.set_value("IQ Stock Balance", {"organization": ORG, "item": self.ors}, "avg_monthly_consumption", 20)
		self.move("Issue", [{"item": self.ors, "quantity": 30}], from_warehouse=self.central)  # empties SOON only
		run_for_organization(ORG)
		self.assertFalse(frappe.db.exists("IQ Exception", {"organization": ORG, "exception_type": "Stock Out"}))
		self.move("Issue", [{"item": self.ors, "quantity": 100}], from_warehouse=self.central)  # now nothing left
		run_for_organization(ORG)
		self.assertEqual(frappe.db.count("IQ Exception", {"organization": ORG, "exception_type": "Stock Out", "status": "Open"}), 1)

	def test_direct_quantity_edit_blocked_after_ledger(self):
		self.receive_ors()
		bal = frappe.get_doc("IQ Stock Balance", {"organization": ORG, "batch_no": "LATE"})
		bal.quantity = 999
		with self.assertRaises(frappe.ValidationError):
			bal.save()

	def test_adjustments_need_reason(self):
		with self.assertRaises(frappe.ValidationError):
			self.move("Adjustment In", [{"item": self.ors, "quantity": 5}], to_warehouse=self.central)
		self.move("Adjustment In", [{"item": self.ors, "quantity": 5}], to_warehouse=self.central, reason="Count correction")
		self.assertEqual(self.qty(self.ors, self.central, None), 5)

	def test_receipt_marks_shipment_received_and_flags_discrepancy(self):
		as_user(ADMIN_USER)
		sh = frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "ORS", "transport_mode": "Road", "status": "In Transit",
			"origin": "Djibouti", "destination": "Addis", "planned_eta": today(), "quantity": 100, "uom": "EA"}).insert()
		as_user(WH_USER)
		self.move("Receipt", [{"item": self.ors, "batch_no": "B1", "quantity": 90}], to_warehouse=self.central, shipment=sh.name)
		sh.reload()
		self.assertEqual(sh.status, "Delivered")
		self.assertEqual(sh.received_quantity, 90)
		self.assertTrue(any(m.milestone == "Goods Received" and m.actual_date for m in sh.milestones))
		run_for_organization(ORG)
		self.assertTrue(frappe.db.exists("IQ Exception", {"organization": ORG, "exception_type": "Receipt Discrepancy", "status": "Open"}))

	def test_other_org_warehouse_rejected(self):
		as_user(OTHER_USER)
		other_wh = frappe.get_doc({"doctype": "IQ Warehouse", "warehouse_name": "Theirs"}).insert().name
		as_user(WH_USER)
		with self.assertRaises(frappe.PermissionError):
			self.move("Receipt", [{"item": self.ors, "quantity": 1}], to_warehouse=other_wh)
		self.assertEqual(frappe.get_list("IQ Stock Ledger Entry", filters={"warehouse": other_wh}), [])


class TestDeliveries(OpsCase):
	def make_delivery(self, planned=None, qty=50):
		return frappe.get_doc({"doctype": "IQ Delivery", "recipient": "Health centre", "destination": "Adama",
			"from_warehouse": self.central, "planned_delivery_date": planned or add_days(today(), 2),
			"items": [{"item": self.ors, "quantity": qty}]}).insert()

	def test_dispatch_confirm_and_shortfall(self):
		self.receive_ors()
		d = self.make_delivery()
		self.assertEqual(d.status, "Draft")
		d.dispatch()
		d.reload()
		self.assertEqual(d.status, "Dispatched")
		self.assertIn("SOON x 30", d.items[0].batches)
		self.assertEqual(self.qty(self.ors, self.central, "SOON"), 0)
		with self.assertRaises(frappe.ValidationError):
			d.confirm_delivery()  # proof of delivery missing
		d.reload()
		d.delivered_on, d.received_by = today(), "Pharmacist"
		d.proof_of_delivery = attach_csv("pod.csv", "signed")
		d.items[0].delivered_qty = 45
		d.save()
		self.assertEqual(d.confirm_delivery(), "Partially Delivered")
		self.assertTrue(frappe.db.get_value("IQ Delivery", d.name, "on_time"))
		run_for_organization(ORG)
		exc = frappe.get_doc("IQ Exception", {"organization": ORG, "exception_type": "Delivery Shortfall"})
		# dismissing with notes stops it being raised again
		as_user(ADMIN_USER)
		exc.status, exc.resolution_notes = "Dismissed", "5 units returned, recorded"
		exc.save()
		run_for_organization(ORG)
		self.assertEqual(frappe.db.count("IQ Exception", {"organization": ORG, "exception_type": "Delivery Shortfall"}), 1)

	def test_status_not_settable_by_client_and_cancel_returns_stock(self):
		self.receive_ors()
		d = self.make_delivery(planned=add_days(today(), -3))
		d.status = "Delivered"
		d.save()
		self.assertEqual(d.status, "Draft")
		run_for_organization(ORG)
		self.assertTrue(frappe.db.exists("IQ Exception", {"organization": ORG, "exception_type": "Delivery Overdue"}))
		d.dispatch()
		d.reload()
		d.cancel_delivery()
		self.assertEqual(self.qty(self.ors, self.central, "SOON"), 30)
		self.assertEqual(frappe.db.get_value("IQ Delivery", d.name, "status"), "Cancelled")


class TestColdChain(OpsCase):
	def reading(self, temp, **kw):
		return frappe.get_doc({"doctype": "IQ Temperature Log", "location_type": "Warehouse", "warehouse": self.cold,
			"reading_time": now_datetime(), "temperature": temp, "logger_id": "L1", **kw}).insert()

	def test_excursion_quarantines_and_only_qa_releases(self):
		self.move("Receipt", [{"item": self.vac, "batch_no": "V1", "expiry_date": add_days(today(), 300), "quantity": 100}], to_warehouse=self.cold)
		self.move("Receipt", [{"item": self.ors, "batch_no": "O1", "quantity": 10}], to_warehouse=self.cold)  # not cold-chain
		ok = self.reading(5)
		self.assertFalse(ok.is_excursion)
		bad = self.reading(9.5)
		self.assertTrue(bad.is_excursion)
		self.assertEqual(bad.deviation, 1.5)
		self.assertEqual(frappe.db.get_value("IQ Temperature Log", bad.name, "quarantined_lines"), 1)
		bal = frappe.get_doc("IQ Stock Balance", {"organization": ORG, "batch_no": "V1"})
		self.assertEqual(bal.qa_status, "Quarantined")
		self.assertEqual(bal.stock_status, "QA Hold")
		self.assertEqual(frappe.db.get_value("IQ Stock Balance", {"organization": ORG, "batch_no": "O1"}, "qa_status"), "Released")

		with self.assertRaises(frappe.ValidationError):
			self.move("Issue", [{"item": self.vac, "quantity": 1}], from_warehouse=self.cold)
		run_for_organization(ORG)
		self.assertTrue(frappe.db.exists("IQ Exception", {"organization": ORG, "exception_type": "QA Hold", "status": "Open"}))

		# the client cannot release by editing the field
		bal.qa_status = "Released"
		bal.save()
		self.assertEqual(frappe.db.get_value("IQ Stock Balance", bal.name, "qa_status"), "Quarantined")
		# a warehouse officer cannot record a QA decision
		with self.assertRaises(frappe.PermissionError):
			bal.set_qa_decision("Released", "looks fine")
		as_user(QA_USER)
		bal = frappe.get_doc("IQ Stock Balance", bal.name)
		with self.assertRaises(frappe.ValidationError):
			bal.set_qa_decision("Released", "")
		bal.set_qa_decision("Released", "Stability data allows 48h at <=10C; excursion 6h")
		self.assertEqual(frappe.db.get_value("IQ Stock Balance", bal.name, "qa_decided_by"), QA_USER)
		as_user(WH_USER)
		self.move("Issue", [{"item": self.vac, "quantity": 1}], from_warehouse=self.cold)
		res = run_for_organization(ORG)
		self.assertFalse(frappe.db.exists("IQ Exception", {"organization": ORG, "exception_type": "QA Hold", "status": "Open"}))

	def test_readings_are_immutable_and_need_a_range(self):
		r = self.reading(4)
		r.temperature = 3
		with self.assertRaises(frappe.ValidationError):
			r.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "IQ Temperature Log", "location_type": "Warehouse", "warehouse": self.central,
				"reading_time": now_datetime(), "temperature": 4}).insert()

	def test_shipment_excursion_holds_stock_on_receipt(self):
		as_user(ADMIN_USER)
		sh = frappe.get_doc({"doctype": "IQ Shipment", "shipment_title": "Vaccines", "transport_mode": "Air", "status": "In Transit",
			"origin": "Brussels", "destination": "Addis", "planned_eta": today()}).insert()
		as_user(WH_USER)
		frappe.get_doc({"doctype": "IQ Temperature Log", "location_type": "Shipment", "shipment": sh.name, "item": self.vac,
			"reading_time": add_to_date(now_datetime(), hours=-5), "temperature": 12}).insert()
		run_for_organization(ORG)
		self.assertTrue(frappe.db.exists("IQ Exception", {"organization": ORG, "exception_type": "Temperature Excursion", "status": "Open"}))
		self.move("Receipt", [{"item": self.vac, "batch_no": "V2", "quantity": 20}, {"item": self.ors, "batch_no": "O2", "quantity": 5}],
			to_warehouse=self.cold, shipment=sh.name)
		self.assertEqual(frappe.db.get_value("IQ Stock Balance", {"organization": ORG, "batch_no": "V2"}, "qa_status"), "Quarantined")
		self.assertEqual(frappe.db.get_value("IQ Stock Balance", {"organization": ORG, "batch_no": "O2"}, "qa_status"), "Released")

	def test_temperature_import(self):
		csv_text = ("Logger,Timestamp,Temp (C),Cold Room\n"
			f"L9,{today()} 08:00,4.5,Cold room\n"
			f"L9,{today()} 09:00,abc,Cold room\n")
		url = attach_csv("temps.csv", csv_text)
		b = frappe.get_doc({"doctype": "IQ Import Batch", "import_type": "Temperature Readings", "source_file": url}).insert()
		b.validate_file()
		b.reload()
		self.assertEqual(b.status, "Has Errors")
		url = attach_csv("temps2.csv", f"Logger,Timestamp,Temperature,Warehouse\nL9,{today()} 08:00,4.5,Cold room\nL9,{today()} 09:00,8.4,Cold room\n")
		b = frappe.get_doc({"doctype": "IQ Import Batch", "import_type": "Temperature Readings", "source_file": url}).insert()
		b.validate_file()
		self.assertEqual(b.confirm_import(), {"created": 2, "updated": 0})
		self.assertEqual(frappe.db.count("IQ Temperature Log", {"organization": ORG, "is_excursion": 1, "source_import": b.name}), 1)

	def test_dashboard_operations_section(self):
		self.receive_ors()
		frappe.get_doc({"doctype": "IQ Delivery", "recipient": "X", "destination": "Y", "from_warehouse": self.central,
			"planned_delivery_date": add_days(today(), -1), "items": [{"item": self.ors, "quantity": 1}]}).insert()
		self.reading(4)
		ops = get_dashboard_data()["operations"]
		self.assertEqual(ops["movements_30d"], {"Receipt": 1})
		self.assertEqual(ops["deliveries"]["overdue"], 1)
		self.assertEqual(ops["readings_7d"], 1)
		self.assertEqual(ops["qa_hold"], [])

from datetime import date

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, today

from supplychain_iq.api.dashboard import get_dashboard_data
from supplychain_iq.entitlements import EntitlementError
from supplychain_iq.intelligence import calculations as calc
from supplychain_iq.intelligence.exceptions import run_for_organization
from supplychain_iq.tests.utils import as_user, ensure_org, ensure_package, purge_org_records

ORG = "_Test IQ Cost Org"
OTHER = "_Test IQ Cost Other"
USER = "iq.cost.admin@test.example"
OTHER_USER = "iq.cost.other@test.example"
ESSENTIAL_ONLY = "_Test No Costs Package"


class TestCostCalculations(UnitTestCase):
	def test_actuals_replace_estimates_per_category(self):
		lines = [
			{"cost_category": "Freight", "cost_status": "Estimate", "amount_base": 1000},
			{"cost_category": "Freight", "cost_status": "Actual", "amount_base": 1250},
			{"cost_category": "Insurance", "cost_status": "Estimate", "amount_base": 100},
		]
		s = calc.landed_cost(lines)
		self.assertEqual(s["by_category"], {"Freight": 1250, "Insurance": 100})
		self.assertEqual(s["total"], 1350)
		self.assertEqual(s["estimate"], 1100)
		self.assertEqual(s["actual"], 1250)
		self.assertEqual(s["overrun_pct"], 25.0)  # only Freight has both

	def test_no_overrun_without_matching_estimate(self):
		s = calc.landed_cost([{"cost_category": "Storage", "cost_status": "Actual", "amount_base": 50}])
		self.assertIsNone(s["overrun_pct"])

	def test_per_unit(self):
		self.assertEqual(calc.per_unit(1000, 4), 250)
		self.assertIsNone(calc.per_unit(1000, 0))

	def test_demurrage(self):
		t = date(2026, 11, 14)
		d = calc.demurrage(date(2026, 11, 1), 7, 100, None, t)
		self.assertEqual(d["free_time_ends"], date(2026, 11, 8))
		self.assertEqual(d["days"], 6)
		self.assertEqual(d["exposure"], 600)
		stopped = calc.demurrage(date(2026, 11, 1), 7, 100, date(2026, 11, 10), t)
		self.assertEqual(stopped["days"], 2)
		self.assertIsNone(stopped["days_left"])
		self.assertEqual(calc.demurrage(None, 7, 100, None, t)["days"], 0)

	def test_supplier_performance(self):
		rows = [
			{"planned_eta": date(2026, 1, 10), "actual_eta": date(2026, 1, 9), "actual_etd": date(2025, 12, 20), "purchase_order": "PO1"},
			{"planned_eta": date(2026, 2, 10), "actual_eta": date(2026, 2, 16), "actual_etd": date(2026, 1, 20), "purchase_order": None},
			{"planned_eta": date(2026, 3, 10), "actual_eta": None, "actual_etd": None, "purchase_order": None},
		]
		p = calc.supplier_performance(rows, {"PO1": date(2025, 12, 1)})
		self.assertEqual(p["shipments_measured"], 2)
		self.assertEqual(p["on_time_rate"], 50.0)
		self.assertEqual(p["avg_delay_days"], 3.0)
		self.assertEqual(p["avg_transit_days"], 23.5)
		self.assertEqual(p["avg_po_lead_time_days"], 19.0)


def _shipment(**kw):
	return frappe.get_doc({
		"doctype": "IQ Shipment", "shipment_title": "Costed cargo", "transport_mode": "Sea", "status": "In Transit",
		"origin": "Djibouti", "destination": "Addis Ababa", "planned_eta": add_days(today(), 10), **kw,
	}).insert()


def _cost(shipment, **kw):
	return frappe.get_doc({
		"doctype": "IQ Cost Line", "shipment": shipment, "cost_category": "Freight", "cost_status": "Estimate",
		"currency": "USD", "amount": 100, "cost_date": today(), **kw,
	}).insert()


class TestCostIntelligence(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_org(ORG, package="IQ Enterprise", users=[(USER, "Org Admin")])
		ensure_org(OTHER, package="IQ Enterprise", users=[(OTHER_USER, "Org Admin")])
		frappe.db.set_value("IQ Organization", ORG, "base_currency", "ETB")

	def setUp(self):
		for org in (ORG, OTHER):
			purge_org_records(org)
			for dt in ("IQ Cost Line", "IQ Exchange Rate"):
				for n in frappe.get_all(dt, filters={"organization": org}, pluck="name"):
					frappe.delete_doc(dt, n, force=True, ignore_permissions=True)
		as_user(USER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _rate(self, cur="USD", rate=150.0, days=-30):
		return frappe.get_doc({
			"doctype": "IQ Exchange Rate", "from_currency": cur, "rate": rate,
			"rate_date": add_days(today(), days), "source": "Commercial Bank",
		}).insert()

	def test_rate_resolution_and_landed_cost_rollup(self):
		self._rate(rate=150, days=-30)
		latest = self._rate(rate=155, days=-2)
		self._rate(rate=999, days=5)  # future rate must not be used
		sh = _shipment(quantity=10, uom="CARTON")
		est = _cost(sh.name, amount=1000)
		self.assertEqual(est.exchange_rate, 155)
		self.assertEqual(est.rate_basis, "Exchange Rate Record")
		self.assertEqual(est.exchange_rate_record, latest.name)
		self.assertEqual(est.amount_base, 155000)
		_cost(sh.name, cost_status="Actual", amount=1200)
		_cost(sh.name, cost_category="Customs Clearance", currency="etb", amount=20000)

		sh.reload()
		self.assertEqual(sh.base_currency, "ETB")
		self.assertEqual(sh.landed_cost_total, 186000 + 20000)  # actual freight replaces estimate
		self.assertEqual(sh.landed_cost_estimate, 155000 + 20000)
		self.assertEqual(sh.landed_cost_actual, 186000)
		self.assertEqual(sh.landed_cost_per_unit, 20600)
		self.assertEqual(sh.cost_lines_count, 3)

		# deleting a line rolls the totals back
		frappe.delete_doc("IQ Cost Line", est.name)
		sh.reload()
		self.assertEqual(sh.cost_lines_count, 2)
		self.assertEqual(sh.landed_cost_estimate, 20000)

	def test_missing_rate_and_manual_rate(self):
		sh = _shipment()
		with self.assertRaises(frappe.ValidationError):
			_cost(sh.name, currency="GBP")
		with self.assertRaises(frappe.ValidationError):
			_cost(sh.name, currency="GBP", manual_exchange_rate=190)  # note required
		line = _cost(sh.name, currency="GBP", manual_exchange_rate=190, manual_rate_note="Bank advice 123")
		self.assertEqual(line.rate_basis, "Manual")
		self.assertEqual(line.amount_base, 19000)

	def test_cost_line_cannot_use_other_org_shipment_or_rate(self):
		as_user(OTHER_USER)
		other_ship = _shipment()
		self._rate(rate=1)
		as_user(USER)
		with self.assertRaises(frappe.PermissionError):
			_cost(other_ship.name, currency="ETB")
		# the other org's USD rate is never used for this org
		sh = _shipment()
		with self.assertRaises(frappe.ValidationError):
			_cost(sh.name)
		self.assertEqual(frappe.get_list("IQ Exchange Rate", pluck="name"), [])

	def test_demurrage_and_cost_exceptions(self):
		self._rate(rate=100)
		sh = _shipment(
			status="At Port", free_time_start=add_days(today(), -10), free_time_days=7,
			demurrage_rate_per_day=200, demurrage_currency="usd",
		)
		self.assertEqual(sh.demurrage_days, 3)
		self.assertEqual(sh.demurrage_exposure, 600)
		self.assertEqual(sh.demurrage_currency, "USD")
		_cost(sh.name, amount=1000)
		_cost(sh.name, cost_status="Actual", amount=1300)  # 30% over
		run_for_organization(ORG)
		types = {e.exception_type: e for e in frappe.get_all("IQ Exception", filters={"organization": ORG}, fields=["exception_type", "severity", "description"])}
		self.assertIn("Demurrage Exposure", types)
		self.assertEqual(types["Demurrage Exposure"].severity, "High")
		self.assertIn("Cost Overrun", types)
		self.assertIn("30.0%", frappe.get_value("IQ Exception", {"organization": ORG, "exception_type": "Cost Overrun"}, "title"))

		# releasing the cargo stops demurrage accruing and clears the exception
		sh.reload()
		sh.append("milestones", {"milestone": "Customs Released", "planned_date": add_days(today(), -1), "actual_date": add_days(today(), -1)})
		sh.status = "Released"
		sh.save()
		self.assertEqual(sh.demurrage_days, 2)
		res = run_for_organization(ORG)
		self.assertGreaterEqual(res["resolved"], 1)
		self.assertEqual(frappe.db.get_value("IQ Exception", {"organization": ORG, "exception_type": "Demurrage Exposure"}, "status"), "Resolved")

	def test_supplier_performance_updates_on_delivery(self):
		sup = frappe.get_doc({"doctype": "IQ Supplier", "supplier_name": "Perf Supplier"}).insert()
		sh = _shipment(supplier=sup.name, planned_eta=add_days(today(), -5), actual_etd=add_days(today(), -30))
		sh.actual_eta = add_days(today(), -2)
		sh.status = "Delivered"
		sh.save()
		sup.reload()
		self.assertEqual(sup.shipments_measured, 1)
		self.assertEqual(sup.on_time_rate, 0)
		self.assertEqual(sup.avg_delay_days, 3)
		self.assertEqual(sup.avg_transit_days, 28)
		# calculated fields cannot be overwritten by the client
		sup.on_time_rate = 100
		sup.save()
		self.assertEqual(frappe.db.get_value("IQ Supplier", sup.name, "on_time_rate"), 0)

	def test_dashboard_cost_section(self):
		self._rate(rate=10)
		sh = _shipment(status="At Port", free_time_start=add_days(today(), -2), free_time_days=5, demurrage_rate_per_day=50, demurrage_currency="USD")
		_cost(sh.name, amount=100, cost_status="Actual")
		data = get_dashboard_data()
		c = data["costs"]
		self.assertEqual(c["base_currency"], "ETB")
		self.assertEqual(c["landed_cost_total"], 1000)
		self.assertEqual(c["by_category"], {"Freight": 1000})
		self.assertEqual(c["demurrage"][0]["days_left"], 3)
		self.assertIn("suppliers", data)


class TestCostEntitlement(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_package(ESSENTIAL_ONLY, ["Shipment Control Tower", "Unified Dashboard"])
		ensure_org(ORG, package=ESSENTIAL_ONLY, users=[(USER, "Org Admin")])

	@classmethod
	def tearDownClass(cls):
		ensure_org(ORG, package="IQ Enterprise", users=[(USER, "Org Admin")])
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_cost_lines_need_cost_intelligence(self):
		purge_org_records(ORG)
		as_user(USER)
		sh = _shipment()
		with self.assertRaises(EntitlementError):
			_cost(sh.name, currency="ETB")
		data = get_dashboard_data()
		self.assertNotIn("costs", data)
		self.assertNotIn("suppliers", data)

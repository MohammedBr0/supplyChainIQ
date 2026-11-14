# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from supplychain_iq.intelligence import stock

IMMUTABLE = ("reading_time", "temperature", "location_type", "warehouse", "shipment", "item", "batch_no", "logger_id")


class IQTemperatureLog(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if before and any(self.get(f) != before.get(f) for f in IMMUTABLE):
			frappe.throw(_("Temperature readings cannot be edited. Record a new reading instead."))
		if self.location_type == "Warehouse":
			if not self.warehouse:
				frappe.throw(_("Warehouse is required."))
			self.shipment = None
		else:
			if not self.shipment:
				frappe.throw(_("Shipment is required."))
			self.warehouse = None
		self.batch_no = (self.batch_no or "").strip() or None
		self.set_range()
		low, high = flt(self.min_allowed), flt(self.max_allowed)
		t = flt(self.temperature)
		self.is_excursion = 1 if (t < low or t > high) else 0
		self.deviation = round(t - high, 2) if t > high else (round(t - low, 2) if t < low else 0)

	def set_range(self):
		if self.item:
			item = frappe.db.get_value("IQ Item", self.item, ["requires_cold_chain", "min_temperature", "max_temperature", "item_code"], as_dict=True)
			if item and item.requires_cold_chain:
				self.min_allowed, self.max_allowed, self.range_source = item.min_temperature, item.max_temperature, f"Item {item.item_code}"
				return
		if self.warehouse:
			wh = frappe.db.get_value("IQ Warehouse", self.warehouse, ["temperature_controlled", "min_temperature", "max_temperature", "warehouse_name"], as_dict=True)
			if wh and wh.temperature_controlled:
				self.min_allowed, self.max_allowed, self.range_source = wh.min_temperature, wh.max_temperature, f"Warehouse {wh.warehouse_name}"
				return
		frappe.throw(
			_("No allowed temperature range: choose a cold-chain item (with min/max) or a temperature-controlled warehouse."),
			title=_("Temperature range missing"),
		)

	def after_insert(self):
		if not self.is_excursion or self.location_type != "Warehouse":
			return
		filters = {"organization": self.organization, "warehouse": self.warehouse, "qa_status": "Released", "quantity": [">", 0]}
		if self.item:
			filters["item"] = self.item
		if self.batch_no:
			filters["batch_no"] = self.batch_no
		cold_items = set(frappe.get_all("IQ Item", filters={"organization": self.organization, "requires_cold_chain": 1}, pluck="name"))
		lines = [b.name for b in frappe.get_all("IQ Stock Balance", filters=filters, fields=["name", "item"]) if b.item in cold_items]
		reason = (
			f"Temperature excursion {self.temperature}°C at {str(self.reading_time)[:16]} "
			f"(allowed {self.min_allowed}..{self.max_allowed}°C, logger {self.logger_id or '-'}, reading {self.name}). QA review required."
		)
		count = stock.place_on_hold(lines, reason)
		self.db_set("quarantined_lines", count, update_modified=False)

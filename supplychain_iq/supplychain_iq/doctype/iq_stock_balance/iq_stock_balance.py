# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from supplychain_iq.intelligence import calculations as calc


class IQStockBalance(Document):
	def validate(self):
		if self.quantity is not None and self.quantity < 0:
			frappe.throw(_("Quantity cannot be negative."))
		if self.avg_monthly_consumption and self.avg_monthly_consumption < 0:
			frappe.throw(_("Average monthly consumption cannot be negative."))
		self.batch_no = (self.batch_no or "").strip() or None
		self.validate_unique()
		self.update_calculated_fields()

	def validate_unique(self):
		filters = {
			"organization": self.organization,
			"item": self.item,
			"warehouse": self.warehouse,
			"batch_no": self.batch_no or ["is", "not set"],
			"name": ["!=", self.name or ""],
		}
		if frappe.db.exists("IQ Stock Balance", filters):
			frappe.throw(_("A stock balance already exists for this item, warehouse and batch."))

	def update_calculated_fields(self):
		org = frappe.db.get_value(
			"IQ Organization", self.organization, ["low_stock_cover_months", "expiry_warning_days"], as_dict=True
		)
		cover = calc.stock_cover_months(self.quantity, self.avg_monthly_consumption)
		# Float columns cannot hold NULL, so "unknown" is tracked separately
		self.cover_available = 0 if cover is None else 1
		self.stock_cover_months = cover or 0
		self.days_to_expiry = calc.days_to_expiry(
			getdate(self.expiry_date) if self.expiry_date else None, getdate(today())
		)
		self.stock_status = calc.stock_status(
			self.quantity or 0,
			cover,
			self.days_to_expiry,
			org.low_stock_cover_months if org else 1,
			org.expiry_warning_days if org else 90,
		)

# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime, today

from supplychain_iq.intelligence import calculations as calc

QA_FIELDS = ("qa_status", "qa_hold_reason", "qa_decision_notes", "qa_decided_by", "qa_decided_on")
QA_DECIDERS = {"IQ QA Officer", "IQ Org Admin", "System Manager"}


class IQStockBalance(Document):
	def validate(self):
		self.guard_server_fields()
		if self.quantity is not None and self.quantity < 0:
			frappe.throw(_("Quantity cannot be negative."))
		if self.avg_monthly_consumption and self.avg_monthly_consumption < 0:
			frappe.throw(_("Average monthly consumption cannot be negative."))
		self.batch_no = (self.batch_no or "").strip() or None
		self.validate_unique()
		self.update_calculated_fields()

	def guard_server_fields(self):
		before = self.get_doc_before_save()
		if not self.flags.iq_qa_change:
			for f in QA_FIELDS:  # only set by QA decisions and cold-chain holds
				self.set(f, before.get(f) if before else (None if f != "qa_status" else "Released"))
		if (
			before
			and not self.flags.iq_from_ledger
			and before.quantity != self.quantity
			and frappe.db.exists("IQ Stock Ledger Entry", {"stock_balance": self.name})
		):
			frappe.throw(
				_("This stock line is managed by stock movements. Use an Adjustment movement to change the quantity."),
				title=_("Use a stock movement"),
			)

	@frappe.whitelist()
	def set_qa_decision(self, decision: str, notes: str):
		"""Record a QA disposition. The only way quarantined stock is released."""
		self.check_permission("read")
		if not QA_DECIDERS.intersection(frappe.get_roles()):
			frappe.throw(_("Only a QA Officer or Org Admin can record QA decisions."), frappe.PermissionError)
		if decision not in ("Released", "Rejected"):
			frappe.throw(_("Decision must be Released or Rejected."))
		if self.qa_status != "Quarantined":
			frappe.throw(_("Only quarantined stock can receive a QA decision (current status: {0}).").format(self.qa_status))
		if not (notes or "").strip():
			frappe.throw(_("QA decision notes are required (evidence reviewed, stability data, etc.)."))
		self.qa_status = decision
		self.qa_decision_notes = notes.strip()
		self.qa_decided_by = frappe.session.user
		self.qa_decided_on = now_datetime()
		self.flags.iq_qa_change = True
		self.flags.ignore_permissions = True
		self.save()
		return self.qa_status

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
			self.qa_status,
		)

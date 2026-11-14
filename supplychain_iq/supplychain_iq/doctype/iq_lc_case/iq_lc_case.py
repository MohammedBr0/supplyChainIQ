# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, today

from supplychain_iq.intelligence.costs import normalize_currency

# a starting point only: requirements depend on the bank, transaction and current regulation
STANDARD_CHECKLIST = (
	"Proforma invoice from the supplier",
	"Signed purchase order / contract",
	"LC application form (bank's format)",
	"Foreign-exchange request per the bank's current procedure",
	"Import permit / licence, where applicable",
	"Insurance cover note or certificate",
	"Business licence / TIN copy (bank KYC)",
)
DONE_EVENTS = ("Payment Made", "Closed", "Cancelled")


class IQLCCase(Document):
	def validate(self):
		self.currency = normalize_currency(self.currency)
		if not self.amount or self.amount <= 0:
			frappe.throw(_("Amount must be greater than zero."))
		if self.purchase_order and not self.supplier:
			self.supplier = frappe.db.get_value("IQ Purchase Order", self.purchase_order, "supplier")
		if self.latest_shipment_date and self.expiry_date and getdate(self.expiry_date) < getdate(self.latest_shipment_date):
			frappe.throw(_("LC expiry cannot be before the latest shipment date."))
		for m in self.milestones:
			if getdate(m.event_date) > getdate(today()):
				frappe.throw(_("Milestone {0}: only record events that have happened.").format(m.idx))
		self.milestones.sort(key=lambda m: (getdate(m.event_date), m.idx))
		for i, m in enumerate(self.milestones, start=1):
			m.idx = i
		self.status = self.milestones[-1].event if self.milestones else "Preparing"
		if self.status in ("Discrepancy Resolved", "Amendment"):
			self.status = "LC Issued" if self.status == "Amendment" else "Documents Presented"
		required = [c for c in self.checklist if c.required]
		for c in self.checklist:
			if c.document and not c.completed:
				c.completed = 1
		self.checklist_progress = round(100.0 * sum(1 for c in required if c.completed) / len(required), 0) if required else 0
		self.update_deadlines()

	def shipped_on(self):
		dates = []
		if not self.is_new():
			dates += [getdate(d) for d in frappe.get_all("IQ Shipment", filters={"lc_case": self.name, "actual_etd": ["is", "set"]}, pluck="actual_etd")]
		dates += [getdate(m.event_date) for m in self.milestones if m.event == "Goods Shipped"]
		return min(dates) if dates else None

	def update_deadlines(self):
		shipped = self.shipped_on()
		self.presentation_deadline = None
		if shipped and self.presentation_days:
			deadline = add_days(shipped, self.presentation_days)
			if self.expiry_date and getdate(deadline) > getdate(self.expiry_date):
				deadline = self.expiry_date
			self.presentation_deadline = deadline
		events = {m.event for m in self.milestones}
		candidates = []
		if self.status not in DONE_EVENTS:
			if self.latest_shipment_date and not shipped:
				candidates.append(getdate(self.latest_shipment_date))
			if self.presentation_deadline and "Documents Presented" not in events:
				candidates.append(getdate(self.presentation_deadline))
			if self.expiry_date:
				candidates.append(getdate(self.expiry_date))
		self.next_deadline = min(candidates) if candidates else None

	@frappe.whitelist()
	def load_standard_checklist(self):
		self.check_permission("write")
		have = {c.requirement for c in self.checklist}
		for r in STANDARD_CHECKLIST:
			if r not in have:
				self.append("checklist", {"requirement": r, "required": 1})
		self.save()


def refresh_for_shipment(shipment_doc):
	"""Recalculate deadlines when a linked shipment's departure changes."""
	if shipment_doc.lc_case and frappe.db.exists("IQ LC Case", shipment_doc.lc_case):
		lc = frappe.get_doc("IQ LC Case", shipment_doc.lc_case)
		lc.update_deadlines()
		frappe.db.set_value("IQ LC Case", lc.name, {"presentation_deadline": lc.presentation_deadline, "next_deadline": lc.next_deadline}, update_modified=False)

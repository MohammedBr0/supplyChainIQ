# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from supplychain_iq.entitlements import has_module
from supplychain_iq.intelligence import calculations as calc


class IQShipment(Document):
	def validate(self):
		self.validate_dates()
		self.validate_legs()
		self.validate_purchase_order()
		self.update_calculated_fields()

	def validate_dates(self):
		for start, end in (("planned_etd", "planned_eta"), ("actual_etd", "actual_eta")):
			if self.get(start) and self.get(end) and getdate(self.get(end)) < getdate(self.get(start)):
				frappe.throw(_("{0} cannot be before {1}.").format(
					_(self.meta.get_label(end)), _(self.meta.get_label(start))
				))
		if self.currency:
			self.currency = self.currency.strip().upper()

	def validate_legs(self):
		if len(self.legs) > 1 and not has_module(self.organization, "Multimodal Corridor"):
			frappe.throw(_("Shipments with more than one transport leg require the Multimodal Corridor module."))
		self.legs.sort(key=lambda leg: leg.sequence or 0)
		seqs = [leg.sequence for leg in self.legs]
		if len(seqs) != len(set(seqs)):
			frappe.throw(_("Transport leg sequence numbers must be unique."))
		for idx, leg in enumerate(self.legs, start=1):
			leg.idx = idx
			if leg.actual_arrival:
				leg.status = "Completed"
			elif leg.actual_departure:
				leg.status = "In Progress"
		if len(self.legs) > 1:
			self.transport_mode = "Multimodal"

	def validate_purchase_order(self):
		if self.purchase_order:
			if not has_module(self.organization, "Procurement Intelligence"):
				frappe.throw(_("Linking a registered PO requires the Procurement Intelligence module. Use PO Reference (text) instead."))
			po_supplier = frappe.db.get_value("IQ Purchase Order", self.purchase_order, "supplier")
			if not self.supplier:
				self.supplier = po_supplier

	def update_calculated_fields(self):
		t = getdate(today())
		self.delay_days = calc.shipment_delay_days(
			getdate(self.planned_eta) if self.planned_eta else None,
			getdate(self.actual_eta) if self.actual_eta else None,
			self.status,
			t,
		)
		self.is_delayed = 1 if self.delay_days > 0 else 0
		for m in self.milestones:
			m.status = calc.milestone_status(
				getdate(m.planned_date) if m.planned_date else None,
				getdate(m.actual_date) if m.actual_date else None,
				m.status,
				t,
			)
		for d in self.documents:
			if d.attachment and not d.received:
				d.received = 1
		self.missing_documents = sum(1 for d in self.documents if d.required and not d.received)

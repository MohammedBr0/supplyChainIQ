# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from supplychain_iq.intelligence import costs


class IQCostLine(Document):
	def validate(self):
		self.currency = costs.normalize_currency(self.currency)
		self.base_currency = costs.base_currency(self.organization)
		if self.manual_exchange_rate:
			if self.manual_exchange_rate <= 0:
				frappe.throw(_("Manual exchange rate must be greater than zero."))
			if self.currency == self.base_currency:
				frappe.throw(_("No exchange rate is needed for base-currency costs."))
			if not (self.manual_rate_note or "").strip():
				frappe.throw(_("Explain where the manual exchange rate comes from."))
			self.exchange_rate, self.rate_basis, self.exchange_rate_record = self.manual_exchange_rate, "Manual", None
		else:
			self.exchange_rate, self.rate_basis, self.exchange_rate_record = costs.resolve_rate(
				self.organization, self.currency, self.cost_date
			)
		self.amount_base = round((self.amount or 0) * self.exchange_rate, 2)

	def on_update(self):
		costs.update_shipment_costs(self.shipment)
		before = self.get_doc_before_save()
		if before and before.shipment != self.shipment:
			costs.update_shipment_costs(before.shipment)

	def on_trash(self):
		self.flags.iq_shipment = self.shipment

	def after_delete(self):
		costs.update_shipment_costs(self.flags.iq_shipment or self.shipment)

# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from supplychain_iq.intelligence.costs import base_currency, normalize_currency


class IQExchangeRate(Document):
	def validate(self):
		self.from_currency = normalize_currency(self.from_currency, _("From Currency"))
		self.to_currency = base_currency(self.organization)
		if self.from_currency == self.to_currency:
			frappe.throw(_("From Currency is already your base currency ({0}).").format(self.to_currency))
		if not self.rate or self.rate <= 0:
			frappe.throw(_("Rate must be greater than zero."))
		if frappe.db.exists(
			"IQ Exchange Rate",
			{
				"organization": self.organization,
				"from_currency": self.from_currency,
				"rate_date": self.rate_date,
				"name": ["!=", self.name or ""],
			},
		):
			frappe.throw(_("A {0} rate for {1} already exists.").format(self.from_currency, self.rate_date))

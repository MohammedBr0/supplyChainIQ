# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from supplychain_iq.intake.importer import normalize_uom


class IQItem(Document):
	def validate(self):
		self.item_code = (self.item_code or "").strip()
		self.uom = normalize_uom(self.uom)
		if frappe.db.exists(
			"IQ Item",
			{"organization": self.organization, "item_code": self.item_code, "name": ["!=", self.name or ""]},
		):
			frappe.throw(_("Item code {0} already exists in your organization.").format(frappe.bold(self.item_code)))
		if self.requires_cold_chain and self.min_temperature is not None and self.max_temperature is not None:
			if self.min_temperature > self.max_temperature:
				frappe.throw(_("Min temperature cannot be above max temperature."))

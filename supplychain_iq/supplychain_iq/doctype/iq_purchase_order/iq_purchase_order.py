# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class IQPurchaseOrder(Document):
	def validate(self):
		if self.currency:
			self.currency = self.currency.strip().upper()
		if self.total_value and self.total_value < 0:
			frappe.throw(_("Total value cannot be negative."))
		if frappe.db.exists(
			"IQ Purchase Order",
			{"organization": self.organization, "po_number": self.po_number, "name": ["!=", self.name or ""]},
		):
			frappe.throw(_("PO {0} already exists in your organization.").format(frappe.bold(self.po_number)))

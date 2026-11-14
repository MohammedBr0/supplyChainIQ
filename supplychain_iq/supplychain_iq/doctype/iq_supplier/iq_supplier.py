# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class IQSupplier(Document):
	def validate(self):
		if frappe.db.exists(
			"IQ Supplier",
			{"organization": self.organization, "supplier_name": self.supplier_name, "name": ["!=", self.name or ""]},
		):
			frappe.throw(_("Supplier {0} already exists in your organization.").format(frappe.bold(self.supplier_name)))

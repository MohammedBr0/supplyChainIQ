# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class IQWarehouse(Document):
	def validate(self):
		if frappe.db.exists(
			"IQ Warehouse",
			{"organization": self.organization, "warehouse_name": self.warehouse_name, "name": ["!=", self.name or ""]},
		):
			frappe.throw(_("Warehouse {0} already exists in your organization.").format(frappe.bold(self.warehouse_name)))

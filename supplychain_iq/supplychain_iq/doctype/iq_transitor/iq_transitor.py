# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class IQTransitor(Document):
	def validate(self):
		if frappe.db.exists(
			"IQ Transitor",
			{"organization": self.organization, "transitor_name": self.transitor_name, "name": ["!=", self.name or ""]},
		):
			frappe.throw(_("Transitor {0} already exists in your organization.").format(frappe.bold(self.transitor_name)))

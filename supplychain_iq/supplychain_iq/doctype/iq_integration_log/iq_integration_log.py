# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe.model.document import Document


class IQIntegrationLog(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw("Integration logs are append-only.", frappe.PermissionError)

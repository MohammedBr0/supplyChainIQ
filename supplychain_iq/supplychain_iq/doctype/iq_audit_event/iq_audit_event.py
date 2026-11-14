# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe.model.document import Document


class IQAuditEvent(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw("Audit events are append-only.", frappe.PermissionError)
		if not self.flags.iq_audit_insert:
			frappe.throw("Audit events are written by the system only.", frappe.PermissionError)

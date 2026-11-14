# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class IQException(Document):
	def validate(self):
		if self.status in ("Resolved", "Dismissed") and not self.resolution_notes and not self.flags.iq_auto:
			frappe.throw(_("Add resolution notes before resolving or dismissing an exception."))
		if self.assigned_to and self.organization:
			from supplychain_iq.tenancy import get_user_organization

			if get_user_organization(self.assigned_to) != self.organization:
				frappe.throw(_("Exceptions can only be assigned to members of the same organization."))

# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


PERFORMANCE_FIELDS = (
	"shipments_measured", "on_time_shipments", "on_time_rate", "avg_delay_days",
	"avg_transit_days", "avg_po_lead_time_days", "performance_updated_on",
)


class IQSupplier(Document):
	def validate(self):
		before = self.get_doc_before_save()
		for f in PERFORMANCE_FIELDS:  # calculated by the server only
			self.set(f, before.get(f) if before else None)
		if frappe.db.exists(
			"IQ Supplier",
			{"organization": self.organization, "supplier_name": self.supplier_name, "name": ["!=", self.name or ""]},
		):
			frappe.throw(_("Supplier {0} already exists in your organization.").format(frappe.bold(self.supplier_name)))

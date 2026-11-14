# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from supplychain_iq.review import ReviewMixin


class IQPersonalPrivilege(ReviewMixin, Document):
	SUBSTANTIVE = ("persona", "privilege_type", "authority", "reference_no", "effective_date", "expiry_date",
		"no_expiry_stated", "entitlement", "quota_value", "quota_unit", "source_document", "conditions")
	REVIEWERS = {"IQ Protocol Officer", "IQ Compliance Officer", "IQ Org Admin", "System Manager"}
	REVIEWER_LABEL = "a Protocol Officer, Compliance Officer or Org Admin"
	WARNING_FIELD = "diplomatic_id_warning_days"

	def validate(self):
		if flt(self.quota_value) < 0:
			frappe.throw(_("Quota cannot be negative."))
		for u in self.utilisations:
			if flt(u.value_used) <= 0:
				frappe.throw(_("Utilisation row {0}: value must be greater than zero.").format(u.idx))
			if getdate(u.use_date) > getdate(today()):
				frappe.throw(_("Utilisation row {0}: record only uses that have happened.").format(u.idx))
			if getdate(u.use_date) < getdate(self.effective_date) or (self.expiry_date and getdate(u.use_date) > getdate(self.expiry_date)):
				frappe.throw(_("Utilisation row {0}: the date is outside the privilege's validity.").format(u.idx))
		self.used_value = round(sum(flt(u.value_used) for u in self.utilisations), 4)
		if flt(self.quota_value):
			self.remaining_value = round(flt(self.quota_value) - self.used_value, 4)
			self.quota_used_pct = round(100.0 * self.used_value / flt(self.quota_value), 1)
			if self.remaining_value < 0:
				frappe.throw(_("Utilisation ({0} {2}) exceeds the granted quota ({1} {2}).").format(self.used_value, self.quota_value, self.quota_unit or ""))
		else:
			self.remaining_value, self.quota_used_pct = 0, 0
		if self.utilisations and self.review_status != "Confirmed" and not self.flags.iq_review_change:
			before = self.get_doc_before_save()
			if not before or len(before.utilisations) < len(self.utilisations):
				frappe.msgprint(_("Recording use of a privilege that is not yet confirmed by review."), indicator="orange", alert=True)
		self.validate_review_and_validity()

	def on_update(self):
		from supplychain_iq.supplychain_iq.doctype.iq_diplomatic_persona.iq_diplomatic_persona import refresh_summary

		refresh_summary(self.persona)

# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from supplychain_iq.review import ReviewMixin


class IQPrivilege(ReviewMixin, Document):
	SUBSTANTIVE = ("authority", "reference_no", "jurisdiction", "beneficiary", "issue_date", "effective_date",
		"expiry_date", "no_expiry_stated", "scope", "source_document", "privilege_type")
	REVIEWERS = {"IQ Compliance Officer", "IQ Protocol Officer", "IQ Org Admin", "System Manager"}
	REVIEWER_LABEL = "a Compliance Officer, Protocol Officer or Org Admin"

	def validate(self):
		for c in self.conditions:
			if not (c.source_reference or "").strip():
				frappe.throw(_("Condition {0}: give the page/paragraph in the source document.").format(c.idx))
		self.validate_review_and_validity()

	def substantive_children(self, doc):
		return [(c.condition_type, c.condition_text, c.source_reference) for c in doc.conditions]

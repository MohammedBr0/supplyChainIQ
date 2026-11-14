# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

SERVER_FIELDS = ("review_status", "submitted_by", "reviewed_by", "last_reviewed_on")
SUBSTANTIVE = ("authority", "reference_no", "jurisdiction", "beneficiary", "issue_date", "effective_date",
	"expiry_date", "no_expiry_stated", "scope", "source_document", "privilege_type")
REVIEWERS = {"IQ Compliance Officer", "IQ Org Admin", "System Manager"}


class IQPrivilege(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if not self.flags.iq_review_change:
			for f in SERVER_FIELDS:
				self.set(f, before.get(f) if before else ("Draft" if f == "review_status" else None))
		if not self.expiry_date and not self.no_expiry_stated:
			frappe.throw(_("Enter the expiry date stated on the document, or tick 'No Expiry Stated' if the document gives none. IQ never assumes a validity period."))
		if self.expiry_date and self.no_expiry_stated:
			frappe.throw(_("Untick 'No Expiry Stated' when an expiry date is entered."))
		if self.expiry_date and getdate(self.expiry_date) < getdate(self.effective_date):
			frappe.throw(_("Expiry date cannot be before the effective date."))
		for c in self.conditions:
			if not (c.source_reference or "").strip():
				frappe.throw(_("Condition {0}: give the page/paragraph in the source document.").format(c.idx))
		if before and not self.flags.iq_review_change and before.review_status in ("Confirmed", "Under Review"):
			changed = any(self.get(f) != before.get(f) for f in SUBSTANTIVE) or self._conditions(self) != self._conditions(before)
			if changed:
				self.review_status = "Draft"
				self.reviewed_by = None
				self.add_comment("Info", _("Substantive change after review: returned to Draft for re-review."))
		self.update_validity()

	@staticmethod
	def _conditions(doc):
		return [(c.condition_type, c.condition_text, c.source_reference) for c in doc.conditions]

	def update_validity(self):
		t = getdate(today())
		warn = frappe.db.get_value("IQ Organization", self.organization, "privilege_warning_days") or 30
		if getdate(self.effective_date) > t:
			self.validity_status, self.days_remaining = "Not Yet Effective", None
		elif self.no_expiry_stated:
			self.validity_status, self.days_remaining = "No Expiry Stated", None
		else:
			self.days_remaining = (getdate(self.expiry_date) - t).days
			self.validity_status = "Expired" if self.days_remaining < 0 else ("Expiring Soon" if self.days_remaining <= warn else "Valid")

	def _set(self, status, **values):
		self.review_status = status
		self.update(values)
		self.flags.iq_review_change = True
		self.save()
		self.flags.iq_review_change = False

	@frappe.whitelist()
	def submit_for_review(self):
		self.check_permission("write")
		if self.review_status not in ("Draft", "Needs Legal Review"):
			frappe.throw(_("Only draft records can be submitted for review."))
		self._set("Under Review", submitted_by=frappe.session.user)

	@frappe.whitelist()
	def confirm(self, notes: str | None = None):
		self._require_reviewer()
		if self.review_status != "Under Review":
			frappe.throw(_("Only records under review can be confirmed."))
		if self.submitted_by == frappe.session.user:
			frappe.throw(_("A different person must review: the submitter cannot confirm their own record."), frappe.PermissionError)
		self._set("Confirmed", reviewed_by=frappe.session.user, last_reviewed_on=today(), review_notes=self._notes(notes))

	@frappe.whitelist()
	def flag_legal_review(self, notes: str):
		self._require_reviewer()
		if not (notes or "").strip():
			frappe.throw(_("Explain what needs legal or compliance review."))
		self._set("Needs Legal Review", reviewed_by=frappe.session.user, last_reviewed_on=today(), review_notes=self._notes(notes))

	@frappe.whitelist()
	def revoke(self, notes: str):
		self._require_reviewer()
		if not (notes or "").strip():
			frappe.throw(_("Record why the privilege is revoked or withdrawn."))
		self._set("Revoked", reviewed_by=frappe.session.user, last_reviewed_on=today(), review_notes=self._notes(notes))

	def _require_reviewer(self):
		self.check_permission("read")
		if not REVIEWERS.intersection(frappe.get_roles()):
			frappe.throw(_("Only a Compliance Officer or Org Admin can review privileges."), frappe.PermissionError)

	def _notes(self, notes):
		entry = f"{today()} {frappe.session.user}: {(notes or '').strip()}".strip()
		return "\n".join(filter(None, [self.review_notes, entry]))

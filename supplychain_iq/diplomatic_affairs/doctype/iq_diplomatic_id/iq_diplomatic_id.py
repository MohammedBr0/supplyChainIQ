# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

# a starting point only: confirm current requirements with the issuing authority
STANDARD_REQUIREMENTS = (
	"Passport copy (check remaining validity)",
	"Copy of the current ID card",
	"Recent passport-size photographs",
	"Organization's request / support letter",
	"Contract or assignment confirmation",
	"Completed application form",
)
ORDER = ("Not Started", "Preparing Documents", "Internal Review Complete", "Submitted",
	"Additional Information Requested", "Approved", "Collected")
# re-submission after an information request; a new cycle after collection
ALLOWED_BACK = {("Additional Information Requested", "Submitted"), ("Collected", "Preparing Documents")}
SERVER_FIELDS = ("internal_reviewed_by", "internal_reviewed_on", "previous_expiry_date", "id_status", "days_to_expiry")
CYCLE_FIELDS = ("internal_reviewed_by", "internal_reviewed_on", "submission_reference", "submission_date",
	"approval_date", "new_expiry_date", "collected_on")


class IQDiplomaticID(Document):
	def validate(self):
		before = self.get_doc_before_save()
		for f in SERVER_FIELDS:
			self.set(f, before.get(f) if before else None)
		if self.persona:
			p = frappe.db.get_value("IQ Diplomatic Persona", self.persona, ["full_name", "employee_id", "position"], as_dict=True)
			self.employee_name, self.employee_id, self.position = p.full_name, p.employee_id or self.employee_id, p.position or self.position
		old = before.renewal_status if before else "Not Started"
		if self.renewal_status != old:
			self.apply_transition(old)
		self.update_status()

	def apply_transition(self, old):
		new = self.renewal_status
		t = getdate(today())
		if ORDER.index(new) < ORDER.index(old) and (old, new) not in ALLOWED_BACK:
			frappe.throw(_("Cannot move the renewal back from {0} to {1}.").format(old, new))
		if new == "Preparing Documents" and old in ("Not Started", "Collected"):
			for f in CYCLE_FIELDS:  # start a fresh renewal cycle
				self.set(f, None)
			for r in self.requirements:
				r.received = 0
		elif new == "Internal Review Complete":
			missing = [r.requirement for r in self.requirements if r.required and not r.received]
			if not self.requirements or missing:
				frappe.throw(_("All required documents must be received before internal review: {0}").format(", ".join(missing) or _("no checklist yet")))
			self.internal_reviewed_by, self.internal_reviewed_on = frappe.session.user, t
		elif new == "Submitted":
			if not (self.internal_reviewed_on or (self.get_doc_before_save() and self.get_doc_before_save().internal_reviewed_on)):
				frappe.throw(_("Complete the internal review before recording a submission."))
			if not (self.submission_reference and self.submission_date):
				frappe.throw(_("Enter the submission reference and date your organization received."))
			if getdate(self.submission_date) > t:
				frappe.throw(_("Submission date cannot be in the future."))
			if not self.next_follow_up:
				frappe.throw(_("Set the next follow-up date."))
		elif new == "Additional Information Requested":
			if not (self.authority_notes or "").strip():
				frappe.throw(_("Record what additional information was requested."))
			if not self.next_follow_up:
				frappe.throw(_("Set the next follow-up date."))
		elif new == "Approved":
			if not self.approval_date:
				frappe.throw(_("Enter the approval date."))
		elif new == "Collected":
			if not (self.collected_on and self.new_expiry_date):
				frappe.throw(_("Enter the collection date and the expiry date of the renewed ID."))
			if self.expiry_date and getdate(self.new_expiry_date) <= getdate(self.expiry_date):
				frappe.throw(_("The renewed ID's expiry must be after the current expiry."))
			self.previous_expiry_date = self.expiry_date
			self.expiry_date = self.new_expiry_date

	def update_status(self):
		warn = frappe.db.get_value("IQ Organization", self.organization, "diplomatic_id_warning_days") or 60
		self.days_to_expiry = (getdate(self.expiry_date) - getdate(today())).days
		self.id_status = "Expired" if self.days_to_expiry < 0 else ("Renewal Due" if self.days_to_expiry <= warn else "Valid")

	def on_update(self):
		from supplychain_iq.diplomatic_affairs.doctype.iq_diplomatic_persona.iq_diplomatic_persona import refresh_summary

		refresh_summary(self.persona)

	@frappe.whitelist()
	def load_standard_requirements(self):
		self.check_permission("write")
		have = {r.requirement for r in self.requirements}
		for r in STANDARD_REQUIREMENTS:
			if r not in have:
				self.append("requirements", {"requirement": r, "required": 1})
		self.save()

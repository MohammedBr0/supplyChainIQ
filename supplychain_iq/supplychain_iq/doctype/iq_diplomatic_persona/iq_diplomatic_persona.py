# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

SUMMARY_FIELDS = ("active_ids", "active_privileges", "next_expiry", "dependants_count")


class IQDiplomaticPersona(Document):
	def validate(self):
		before = self.get_doc_before_save()
		for f in SUMMARY_FIELDS:  # calculated only
			self.set(f, before.get(f) if before else None)
		if self.diplomatic_category == "Dependant":
			if not self.principal:
				frappe.throw(_("Select the principal this dependant belongs to."))
			if self.principal == self.name:
				frappe.throw(_("A persona cannot be their own principal."))
			if frappe.db.get_value("IQ Diplomatic Persona", self.principal, "diplomatic_category") == "Dependant":
				frappe.throw(_("The principal must be a staff member, not another dependant."))
		else:
			self.principal = self.relationship = None
		if self.arrival_date and self.assignment_end_date and getdate(self.assignment_end_date) < getdate(self.arrival_date):
			frappe.throw(_("Assignment end date cannot be before the arrival date."))
		if self.persona_status == "Departed" and not self.departed_on:
			frappe.throw(_("Enter the departure date."))

	def on_update(self):
		refresh_summary(self.name)
		if self.principal:
			refresh_summary(self.principal)


def refresh_summary(persona: str | None):
	if not persona or not frappe.db.exists("IQ Diplomatic Persona", persona):
		return
	ids = frappe.get_all("IQ Diplomatic ID", filters={"persona": persona, "id_status": ["!=", "Expired"]}, pluck="expiry_date")
	privs = frappe.get_all(
		"IQ Personal Privilege",
		filters={"persona": persona, "review_status": ["!=", "Revoked"], "validity_status": ["not in", ["Expired"]]},
		pluck="expiry_date",
	)
	dates = [getdate(d) for d in ids + privs if d]
	frappe.db.set_value(
		"IQ Diplomatic Persona",
		persona,
		{
			"active_ids": len(ids),
			"active_privileges": len(privs),
			"next_expiry": min(dates) if dates else None,
			"dependants_count": frappe.db.count("IQ Diplomatic Persona", {"principal": persona, "persona_status": ["!=", "Departed"]}),
		},
		update_modified=False,
	)

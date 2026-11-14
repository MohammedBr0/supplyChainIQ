# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from supplychain_iq import tenancy
from supplychain_iq.documents_store import DIPLOMATIC


class IQDocument(Document):
	def validate(self):
		before = self.get_doc_before_save()
		self.restricted = 1 if self.section == DIPLOMATIC else 0
		if self.restricted:
			from supplychain_iq.entitlements import require_module

			require_module(self.organization, "Diplomatic Affairs")
			if not tenancy.can_see_restricted() and not self.flags.ignore_permissions:
				frappe.throw(_("Only Protocol Officers, HR Officers and Org Admins can file Diplomatic Affairs documents."), frappe.PermissionError)
		if before:
			self.uploaded_by, self.auto_filed = before.uploaded_by, before.auto_filed
		else:
			self.uploaded_by = frappe.session.user
			self.auto_filed = 1 if self.flags.ignore_permissions and self.auto_filed else 0
		if bool(self.reference_doctype) != bool(self.reference_name):
			frappe.throw(_("Choose both the linked record type and the record, or neither."))
		if self.reference_name:
			org = frappe.db.get_value(self.reference_doctype, self.reference_name, "organization") if frappe.get_meta(self.reference_doctype).has_field("organization") else None
			if not self.reference_doctype.startswith("IQ ") or (org and org != self.organization):
				frappe.throw(_("The linked record must be a SupplyChain IQ record of your organization."), frappe.PermissionError)
		if self.document_date and self.expiry_date and getdate(self.expiry_date) < getdate(self.document_date):
			frappe.throw(_("Expiry date cannot be before the document date."))
		self.update_validity()

	def update_validity(self):
		if not self.expiry_date:
			self.validity_status = "No Expiry"
			return
		days = (getdate(self.expiry_date) - getdate(today())).days
		warn = frappe.db.get_value("IQ Organization", self.organization, "privilege_warning_days") or 30
		self.validity_status = "Expired" if days < 0 else ("Expiring Soon" if days <= warn else "Valid")

	def after_insert(self):
		self.attach_file()

	def attach_file(self):
		"""Tie the stored file to this document so Frappe's file permissions follow the document's."""
		name = frappe.db.get_value("File", {"file_url": self.file, "attached_to_name": ["is", "not set"]})
		if name:
			frappe.db.set_value("File", name, {"attached_to_doctype": self.doctype, "attached_to_name": self.name, "is_private": 1}, update_modified=False)

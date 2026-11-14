# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from supplychain_iq.intake import importer

# changing any of these invalidates an earlier validation
INPUT_FIELDS = ("import_type", "source_file", "date_calendar", "create_missing_masters", "column_mapping")
RESULT_FIELDS = (
	"status", "total_rows", "valid_rows", "warning_rows", "error_rows", "validation_summary",
	"mapping_notes", "imported_by", "imported_on", "records_created", "records_updated",
)


class IQImportBatch(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if not before:
			if not self.flags.iq_allow_status_change:
				self.status = "Draft"
			return
		if before.status == "Imported" and not self.flags.iq_allow_status_change:
			if any(self.get(f) != before.get(f) for f in INPUT_FIELDS + RESULT_FIELDS):
				frappe.throw(_("An imported batch cannot be changed. Create a new import batch instead."))
		if self.flags.iq_validated or self.flags.iq_allow_status_change:
			return
		# result fields are only ever set by the server pipeline
		for f in RESULT_FIELDS:
			self.set(f, before.get(f))
		if any(self.get(f) != before.get(f) for f in INPUT_FIELDS):
			self.status = "Draft"
			self.set("rows", [])
			self.validation_summary = _("Inputs changed - validate again.")

	def on_update(self):
		# server-pipeline flags are single-use
		self.flags.iq_allow_status_change = False
		self.flags.iq_validated = False

	@frappe.whitelist()
	def validate_file(self):
		self.check_permission("write")
		if self.status == "Imported":
			frappe.throw(_("This batch has already been imported."))
		result = importer.run_validation(self)
		importer.apply_validation(self, result)
		self.flags.iq_validated = True
		self.save()
		return {"status": self.status, "fuzzy_columns": result["fuzzy"]}

	@frappe.whitelist()
	def confirm_import(self):
		self.check_permission("write")
		self.flags.iq_validated = True
		return importer.confirm_import(self)

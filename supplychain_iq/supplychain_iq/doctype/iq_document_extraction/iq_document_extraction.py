# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from supplychain_iq.intake import documents
from supplychain_iq.intake.importer import get_file_content

# extracted field -> shipment field (only confirmed fields are written)
SHIPMENT_MAP = {"awb_bl_number": "awb_bl_number", "actual_etd": "actual_etd", "incoterm": "incoterm",
	"cargo_value": "cargo_value", "currency": "currency", "origin": "origin", "destination": "destination"}
DOC_CHECKLIST = {"Commercial Invoice": "Commercial Invoice", "Packing List": "Packing List",
	"Bill of Lading": "Bill of Lading", "Air Waybill": "Air Waybill", "Duty-Free Privilege Approval": "Duty-Free Privilege Approval"}


class IQDocumentExtraction(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if not self.flags.iq_server_change:
			for f in ("status", "page_count", "applied_to", "applied_doctype", "extracted_text"):
				self.set(f, before.get(f) if before else ("Draft" if f == "status" else None))
		if before and before.status in ("Applied", "Rejected") and not self.flags.iq_server_change:
			frappe.throw(_("This extraction is closed ({0}). Start a new one.").format(before.status))
		if self.document_type != "Duty-Free Privilege Approval" and not self.shipment and self.status == "Extracted":
			frappe.msgprint(_("Select the shipment to apply the fields to."), indicator="orange", alert=True)

	def _server_save(self):
		self.flags.iq_server_change = True
		self.save()
		self.flags.iq_server_change = False

	@frappe.whitelist()
	def extract(self):
		self.check_permission("write")
		content, filename = get_file_content(self.source_file)
		try:
			pages = documents.read_pages(content, filename)
		except ValueError as e:
			frappe.throw(str(e))
		except Exception:
			frappe.throw(_("The PDF could not be read. It may be damaged or encrypted."))
		text = "\n\n".join(pages)
		self.page_count = len(pages)
		self.extracted_text = text[:20000]
		if not text.strip():
			self.set("fields", [])
			self.status = "Extracted"
			self._server_save()
			frappe.msgprint(_("No text layer found (scanned image). OCR is not available: enter the fields manually."), indicator="orange")
			return 0
		self.set("fields", documents.extract(self.document_type, pages))
		self.status = "Extracted"
		self._server_save()
		return len(self.fields)

	@frappe.whitelist()
	def apply(self):
		self.check_permission("write")
		if self.status != "Extracted":
			frappe.throw(_("Extract the document first."))
		confirmed = [f for f in self.fields if f.confirmed and (f.value or "").strip()]
		if not confirmed:
			frappe.throw(_("Tick 'confirmed' on the fields you checked against the document."))
		if self.document_type == "Duty-Free Privilege Approval":
			target = self._apply_privilege(confirmed)
		else:
			target = self._apply_shipment(confirmed)
		self.applied_doctype, self.applied_to = target.doctype, target.name
		self.status = "Applied"
		self._server_save()
		return target.name

	@frappe.whitelist()
	def reject(self):
		self.check_permission("write")
		self.status = "Rejected"
		self._server_save()

	def _apply_shipment(self, confirmed):
		if not self.shipment:
			frappe.throw(_("Select the shipment to apply the fields to."))
		sh = frappe.get_doc("IQ Shipment", self.shipment)
		sh.check_permission("write")
		applied = []
		for f in confirmed:
			target = SHIPMENT_MAP.get(f.field_key)
			if target:
				value = f.value.strip()
				if target == "actual_etd":
					value = getdate(value)
				elif target == "cargo_value":
					value = flt(value)
				elif target == "currency":
					value = value.upper()
				sh.set(target, value)
				applied.append(f"{f.label}: {f.value}")
			elif f.field_key in ("container", "vessel", "invoice_number", "packages", "gross_weight", "net_weight", "invoice_date"):
				applied.append(f"{f.label}: {f.value}")
		row = next((d for d in sh.documents if d.document_type == DOC_CHECKLIST[self.document_type] and not d.attachment), None)
		if not row:
			row = sh.append("documents", {"document_type": DOC_CHECKLIST[self.document_type], "required": 0})
		row.attachment, row.received = self.source_file, 1
		row.remarks = f"From extraction {self.name}"
		sh.save()
		sh.add_comment("Info", _("Confirmed fields applied from {0} ({1}): {2}").format(self.name, self.document_type, "; ".join(applied)))
		return sh

	def _apply_privilege(self, confirmed):
		"""Create a DRAFT privilege: it still needs scope, conditions and maker-checker review."""
		values = {f.field_key: f.value.strip() for f in confirmed}
		if not values.get("reference_no") or not values.get("effective_date"):
			frappe.throw(_("Confirm at least the authority reference and the effective date."))
		priv = frappe.get_doc({
			"doctype": "IQ Privilege", "organization": self.organization,
			"title": f"Privilege {values['reference_no']} (from document)", "privilege_type": "Duty-Free Privilege",
			"authority": values.get("authority") or _("To be completed"), "reference_no": values["reference_no"],
			"effective_date": getdate(values["effective_date"]),
			"expiry_date": getdate(values["expiry_date"]) if values.get("expiry_date") else None,
			"no_expiry_stated": 0 if values.get("expiry_date") else 1,
			"scope": _("To be completed from the source document."), "source_document": self.source_file, "confidence": "Low",
		})
		priv.insert()
		return priv

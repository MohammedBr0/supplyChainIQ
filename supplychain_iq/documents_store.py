"""Document storage: one library, filed by section, linked to the record it belongs to.

Documents attached on records (shipment checklist, privileges, LC cases,
customs payments, deliveries, diplomatic records) are filed here automatically,
so each section shows everything of that kind in one place.
"""

import frappe

DIPLOMATIC = "Diplomatic Affairs"


def file_document(doc, file_url, section, document_type, title=None, expiry_date=None, document_date=None):
	"""File an attachment of `doc` in the library (once per record + file)."""
	if not file_url or not doc.get("organization"):
		return None
	existing = frappe.db.get_value(
		"IQ Document", {"organization": doc.organization, "file": file_url, "reference_doctype": doc.doctype, "reference_name": doc.name}
	)
	if existing:
		if expiry_date and str(frappe.db.get_value("IQ Document", existing, "expiry_date") or "") != str(expiry_date):
			d = frappe.get_doc("IQ Document", existing)
			d.expiry_date = expiry_date
			d.flags.ignore_permissions = True
			d.save()
		return existing
	d = frappe.get_doc({
		"doctype": "IQ Document", "organization": doc.organization, "title": (title or f"{document_type} - {doc.name}")[:140],
		"section": section, "document_type": document_type, "file": file_url, "reference_doctype": doc.doctype,
		"reference_name": doc.name, "expiry_date": expiry_date, "document_date": document_date, "auto_filed": 1,
	})
	d.flags.ignore_permissions = True
	d.insert()
	return d.name


def sync(doc, method=None):
	"""doc_events on_update for record types that carry attachments."""
	dt = doc.doctype
	if dt == "IQ Shipment":
		for row in doc.documents:
			section = "Customs" if row.document_type in ("Customs Declaration", "Import Permit") else (
				"Compliance & Privileges" if row.document_type == "Duty-Free Privilege Approval" else "Shipping")
			file_document(doc, row.attachment, section, row.document_type, f"{row.document_type} - {doc.shipment_title}")
	elif dt == "IQ Privilege":
		file_document(doc, doc.source_document, "Compliance & Privileges", doc.privilege_type, doc.title, doc.expiry_date, doc.issue_date)
	elif dt == "IQ LC Case":
		file_document(doc, doc.proforma_document, "Finance & LC", "Proforma Invoice", f"Proforma - LC {doc.lc_number or doc.name}")
		for row in doc.checklist:
			file_document(doc, row.document, "Finance & LC", row.requirement, f"{row.requirement} - LC {doc.lc_number or doc.name}")
	elif dt == "IQ Cost Line":
		file_document(doc, doc.source_document, "Finance & LC", f"{doc.cost_category} invoice", f"{doc.cost_category} invoice - {doc.shipment}", document_date=doc.cost_date)
	elif dt == "IQ Delivery":
		file_document(doc, doc.proof_of_delivery, "Warehouse & Quality", "Proof of Delivery", f"Proof of delivery - {doc.recipient}", document_date=doc.delivered_on)
	elif dt == "IQ Personal Privilege":
		file_document(doc, doc.source_document, DIPLOMATIC, doc.privilege_type, f"{doc.privilege_type} - {doc.full_name}", doc.expiry_date)
	elif dt == "IQ Diplomatic ID":
		for row in doc.requirements:
			file_document(doc, row.document, DIPLOMATIC, row.requirement, f"{row.requirement} - {doc.employee_name}")


SYNCED = ("IQ Shipment", "IQ Privilege", "IQ LC Case", "IQ Cost Line", "IQ Delivery", "IQ Personal Privilege", "IQ Diplomatic ID")


# ---------------------------------------------------------------- permissions


def document_pqc(user=None, doctype=None):
	from supplychain_iq import tenancy

	cond = tenancy.get_permission_query_conditions(user, "IQ Document")
	if cond and not tenancy.can_see_restricted(user):
		cond += " and coalesce(`tabIQ Document`.`restricted`, 0) = 0"
	return cond


@frappe.whitelist()
def section_summary():
	"""Counts per section for the current user (respects tenant and restricted rules)."""
	rows = frappe.get_list("IQ Document", fields=["section", "validity_status"], limit_page_length=0)
	out = {}
	for r in rows:
		s = out.setdefault(r.section, {"total": 0, "expiring": 0, "expired": 0})
		s["total"] += 1
		if r.validity_status == "Expiring Soon":
			s["expiring"] += 1
		elif r.validity_status == "Expired":
			s["expired"] += 1
	return out

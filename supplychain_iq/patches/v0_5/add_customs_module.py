"""Customs Management module for the default Professional/Enterprise packages."""

import frappe


def execute():
	for package in ("IQ Professional", "IQ Enterprise"):
		if not frappe.db.exists("IQ Package", package):
			continue
		doc = frappe.get_doc("IQ Package", package)
		if "Customs Management" not in {m.module for m in doc.modules}:
			doc.append("modules", {"module": "Customs Management"})
			doc.flags.ignore_permissions = True
			doc.save()

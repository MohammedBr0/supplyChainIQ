"""ERP Integration module for the default Enterprise package; integration role."""

import frappe

from supplychain_iq.setup.install import create_roles


def execute():
	create_roles()
	if frappe.db.exists("IQ Package", "IQ Enterprise"):
		doc = frappe.get_doc("IQ Package", "IQ Enterprise")
		if "ERP Integration" not in {m.module for m in doc.modules}:
			doc.append("modules", {"module": "ERP Integration"})
			doc.flags.ignore_permissions = True
			doc.save()

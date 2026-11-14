"""Stage 6: grant warehouse, distribution and cold-chain modules to the default
Professional/Enterprise packages, and create the QA Officer role."""

import frappe

from supplychain_iq.setup.install import create_roles

STAGE6 = ("Warehouse & Batch Control", "Distribution & Delivery", "Cold Chain Intelligence")


def execute():
	create_roles()
	for package in ("IQ Professional", "IQ Enterprise"):
		if not frappe.db.exists("IQ Package", package):
			continue
		doc = frappe.get_doc("IQ Package", package)
		have = {m.module for m in doc.modules}
		missing = [m for m in STAGE6 if m not in have]
		for m in missing:
			doc.append("modules", {"module": m})
		if missing:
			doc.flags.ignore_permissions = True
			doc.save()

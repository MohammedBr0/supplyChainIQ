"""Stage 4: grant Cost and Supplier Intelligence to the default Professional/Enterprise packages.

Only touches the seeded default packages, and only adds modules they lack.
"""

import frappe

STAGE4 = ("Cost Intelligence", "Supplier Intelligence")


def execute():
	frappe.reload_doc("supplychain_iq", "doctype", "iq_package_module")
	for package in ("IQ Professional", "IQ Enterprise"):
		if not frappe.db.exists("IQ Package", package):
			continue
		doc = frappe.get_doc("IQ Package", package)
		have = {m.module for m in doc.modules}
		missing = [m for m in STAGE4 if m not in have]
		for m in missing:
			doc.append("modules", {"module": m})
		if missing:
			doc.flags.ignore_permissions = True
			doc.save()

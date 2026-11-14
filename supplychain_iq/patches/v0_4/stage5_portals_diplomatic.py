"""Stage 5, partner portals and the Diplomatic Affairs app: roles and default packages."""

import frappe

from supplychain_iq.setup.install import create_roles, set_dashboard_as_home

NEW_MODULES = ("Regulatory & Privileges", "LC & Import Finance", "Diplomatic Affairs", "Partner Portals")


def execute():
	create_roles()
	set_dashboard_as_home()
	for package in ("IQ Professional", "IQ Enterprise"):
		if not frappe.db.exists("IQ Package", package):
			continue
		doc = frappe.get_doc("IQ Package", package)
		have = {m.module for m in doc.modules}
		# the interim WIP module name, if it was ever stored
		doc.set("modules", [m for m in doc.modules if m.module != "Diplomatic ID Renewal"])
		missing = [m for m in NEW_MODULES if m not in have]
		for m in missing:
			doc.append("modules", {"module": m})
		doc.flags.ignore_permissions = True
		doc.save()

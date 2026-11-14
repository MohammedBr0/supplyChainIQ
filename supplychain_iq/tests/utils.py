"""Synthetic fixtures for SupplyChain IQ tests."""

import frappe

from supplychain_iq import tenancy
from supplychain_iq.setup.install import after_install


def ensure_org(name, package="IQ Professional", users=(), status="Active"):
	"""Create (or reset) an organization with the given (email, iq_role) users."""
	after_install()
	frappe.set_user("Administrator")
	for email, _role in users:
		if not frappe.db.exists("User", email):
			frappe.get_doc({
				"doctype": "User", "email": email, "first_name": email.split("@")[0],
				"send_welcome_email": 0, "user_type": "System User",
			}).insert(ignore_permissions=True)
	if frappe.db.exists("IQ Organization", name):
		org = frappe.get_doc("IQ Organization", name)
		org.package = package
		org.subscription_status = status
		org.set("members", [{"user": e, "iq_role": r} for e, r in users])
		org.save()
	else:
		org = frappe.get_doc({
			"doctype": "IQ Organization", "organization_name": name, "package": package,
			"subscription_status": status,
			"members": [{"user": e, "iq_role": r} for e, r in users],
		}).insert()
	tenancy.clear_cache()
	return org


def ensure_package(name, modules, **limits):
	frappe.set_user("Administrator")
	if frappe.db.exists("IQ Package", name):
		frappe.delete_doc("IQ Package", name, force=True)
	doc = frappe.get_doc({"doctype": "IQ Package", "package_name": name, "is_active": 1, **limits})
	for m in modules:
		doc.append("modules", {"module": m})
	doc.insert()
	tenancy.clear_cache()
	return doc


def purge_org_records(org):
	frappe.set_user("Administrator")
	for dt in ("IQ Exception", "IQ Cost Line", "IQ Exchange Rate", "IQ Stock Balance", "IQ Shipment", "IQ Import Batch", "IQ Purchase Order", "IQ Item", "IQ Warehouse", "IQ Supplier"):
		for name in frappe.get_all(dt, filters={"organization": org}, pluck="name"):
			frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
	tenancy.clear_cache()


def attach_csv(filename, text):
	f = frappe.get_doc({
		"doctype": "File", "file_name": filename, "content": text.encode(), "is_private": 1,
	})
	f.flags.ignore_permissions = True
	f.insert()
	return f.file_url


def as_user(user):
	frappe.set_user(user)
	tenancy.clear_cache()

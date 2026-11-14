"""Landing route for "/": sends each user to their app."""

import frappe

no_cache = 1


def get_context(context):
	user = frappe.session.user
	if user == "Guest":
		target = "/login?redirect-to=/iq-home"
	elif frappe.db.exists("IQ Portal User", {"user": user, "is_active": 1}):
		target = "/iq-portal"
	elif "IQ Protocol Officer" in frappe.get_roles() and not {"IQ Org Admin", "IQ Logistics Officer", "IQ Warehouse Officer"} & set(frappe.get_roles()):
		target = "/desk/iq-diplomatic"
	else:
		target = "/desk/iq-dashboard"
	frappe.local.flags.redirect_location = target
	raise frappe.Redirect

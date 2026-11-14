"""Partner portal for suppliers and transitors."""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/iq-portal"
		raise frappe.Redirect
	from supplychain_iq.api.portal import context as portal_context

	try:
		ctx = portal_context()
	except frappe.PermissionError as e:
		context.error = str(e) or _("Your login is not linked to a partner portal.")
		ctx = None
	context.no_breadcrumbs = True
	context.show_sidebar = False
	context.title = _("SupplyChain IQ Partner Portal")
	context.iqp = ctx
	return context

"""Who may use the Diplomatic Affairs app."""

import frappe

from supplychain_iq import tenancy
from supplychain_iq.entitlements import has_module

APP_ROLES = {"IQ Protocol Officer", "IQ HR Officer", "IQ Org Admin"}
MODULE = "Diplomatic Affairs"


def has_app_permission() -> bool:
	"""Shown on the apps screen only to authorised staff of organizations that enabled it."""
	if tenancy.is_platform_admin():
		return True
	if not APP_ROLES.intersection(frappe.get_roles()):
		return False
	org = tenancy.get_user_organization()
	return bool(org and has_module(org, MODULE))

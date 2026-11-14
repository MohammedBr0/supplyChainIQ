"""Organization-level tenant isolation.

Every tenant-scoped DocType carries an ``organization`` field. For any user who
is not a platform administrator this module:

* filters list/report queries to the user's organization
  (``permission_query_conditions`` hook),
* denies document-level access to records of other organizations
  (``has_permission`` hook),
* stamps new records with the user's organization and refuses saves into a
  different organization (``validate`` doc event),
* refuses links to records that belong to a different organization.

Platform administrators (Administrator and System Manager) see all
organizations. Everything here runs server-side, so the client UI cannot bypass
it.
"""

import frappe
from frappe import _

TENANT_DOCTYPES = (
	"IQ Supplier",
	"IQ Purchase Order",
	"IQ Shipment",
	"IQ Warehouse",
	"IQ Item",
	"IQ Stock Balance",
	"IQ Import Batch",
	"IQ Exception",
	"IQ Cost Line",
	"IQ Exchange Rate",
	"IQ Stock Movement",
	"IQ Stock Ledger Entry",
	"IQ Delivery",
	"IQ Temperature Log",
)

PLATFORM_ROLES = {"System Manager"}


def is_platform_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(PLATFORM_ROLES.intersection(frappe.get_roles(user)))


def get_user_organization(user: str | None = None) -> str | None:
	"""Return the organization the user belongs to (None if not a member).

	A user belongs to at most one organization (enforced in IQ Organization).
	"""
	user = user or frappe.session.user
	cache = _local_cache("iq_user_org")
	if user not in cache:
		cache[user] = frappe.db.get_value(
			"IQ Organization User", {"user": user, "parenttype": "IQ Organization"}, "parent"
		)
	return cache[user]


def _local_cache(key: str) -> dict:
	"""Per-request cache (frappe.local is reset for every request/job)."""
	cache = getattr(frappe.local, key, None)
	if cache is None:
		cache = {}
		setattr(frappe.local, key, cache)
	return cache


def clear_cache():
	frappe.local.iq_user_org = {}
	frappe.local.iq_entitlements = {}


def require_organization(user: str | None = None) -> str:
	org = get_user_organization(user)
	if not org:
		frappe.throw(_("Your user is not a member of any SupplyChain IQ organization."), frappe.PermissionError)
	return org


# ---------------------------------------------------------------- hooks


def get_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	user = user or frappe.session.user
	if is_platform_admin(user):
		return ""
	org = get_user_organization(user)
	if not org:
		return "1=0"
	return f"`tab{doctype}`.`organization` = {frappe.db.escape(org)}"


def _make_pqc(doctype):
	def pqc(user=None, doctype=doctype):
		return get_permission_query_conditions(user, doctype)

	return pqc


# one named function per DocType so hooks.py can reference them by path
supplier_pqc = _make_pqc("IQ Supplier")
purchase_order_pqc = _make_pqc("IQ Purchase Order")
shipment_pqc = _make_pqc("IQ Shipment")
warehouse_pqc = _make_pqc("IQ Warehouse")
item_pqc = _make_pqc("IQ Item")
stock_balance_pqc = _make_pqc("IQ Stock Balance")
import_batch_pqc = _make_pqc("IQ Import Batch")
exception_pqc = _make_pqc("IQ Exception")
cost_line_pqc = _make_pqc("IQ Cost Line")
exchange_rate_pqc = _make_pqc("IQ Exchange Rate")
stock_movement_pqc = _make_pqc("IQ Stock Movement")
stock_ledger_pqc = _make_pqc("IQ Stock Ledger Entry")
delivery_pqc = _make_pqc("IQ Delivery")
temperature_log_pqc = _make_pqc("IQ Temperature Log")


def has_permission(doc, ptype=None, user=None, debug=False) -> bool:
	"""Deny access to another organization's records.

	Frappe treats any falsy return as a denial, so always return a bool.
	"""
	user = user or frappe.session.user
	if is_platform_admin(user):
		return True
	org = get_user_organization(user)
	if not org:
		return False
	doc_org = doc.get("organization")
	if not doc_org:
		# a new, unsaved record: validate() stamps the organization
		return ptype == "create" or doc.is_new()
	if doc_org != org:
		return False
	from supplychain_iq.entitlements import doctype_entitled

	return doctype_entitled(doc.doctype, org)


def organization_has_permission(doc, ptype=None, user=None, debug=False) -> bool:
	user = user or frappe.session.user
	if is_platform_admin(user):
		return True
	return doc.name == get_user_organization(user)


def organization_pqc(user=None, doctype=None) -> str:
	user = user or frappe.session.user
	if is_platform_admin(user):
		return ""
	org = get_user_organization(user)
	if not org:
		return "1=0"
	return f"`tabIQ Organization`.`name` = {frappe.db.escape(org)}"


# ---------------------------------------------------------------- doc events


def validate_tenant_document(doc, method=None):
	"""Stamp and verify the organization of a tenant document and its links."""
	user = frappe.session.user
	admin = is_platform_admin(user)
	if not doc.get("organization"):
		if admin:
			frappe.throw(_("Organization is required."))
		doc.organization = require_organization(user)
	elif not admin and doc.organization != get_user_organization(user):
		frappe.throw(_("You cannot create or change records for another organization."), frappe.PermissionError)

	validate_links_same_organization(doc)

	from supplychain_iq.entitlements import enforce_entitlement

	enforce_entitlement(doc)


def validate_links_same_organization(doc):
	"""Refuse Link values that point to another organization's record."""
	meta = frappe.get_meta(doc.doctype)
	for df in meta.get_link_fields():
		if df.options not in TENANT_DOCTYPES:
			continue
		value = doc.get(df.fieldname)
		if not value:
			continue
		linked_org = frappe.db.get_value(df.options, value, "organization")
		if linked_org and linked_org != doc.organization:
			frappe.throw(
				_("{0} {1} belongs to a different organization.").format(_(df.label), frappe.bold(value)),
				frappe.PermissionError,
			)

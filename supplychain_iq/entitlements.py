"""Package entitlements and usage limits.

The module catalogue (MODULES) is separate from package configuration: a
package (IQ Package) is a commercial collection of module entitlements and
limits that product staff edit in the UI, without code changes.
"""

import frappe
from frappe import _

MODULES = (
	"Shipment Control Tower",
	"Multimodal Corridor",
	"Procurement Intelligence",
	"Inventory Intelligence",
	"Data Intake",
	"Exception Management",
	"Unified Dashboard",
	"Cost Intelligence",
	"Supplier Intelligence",
	"Warehouse & Batch Control",
	"Distribution & Delivery",
	"Cold Chain Intelligence",
	"Regulatory & Privileges",
	"LC & Import Finance",
	"Diplomatic Affairs",
	"Partner Portals",
	"Customs Management",
)

# Optional features an Org Admin must also switch on, and the organization types allowed to
DIPLOMATIC_ID_ORG_TYPES = ("NGO / INGO / UN-related", "International Organization")

# DocType -> module that must be entitled. DocTypes not listed are core
# (e.g. IQ Supplier is needed by every package that registers shipments).
DOCTYPE_MODULE = {
	"IQ Shipment": "Shipment Control Tower",
	"IQ Purchase Order": "Procurement Intelligence",
	"IQ Warehouse": "Inventory Intelligence",
	"IQ Item": "Inventory Intelligence",
	"IQ Stock Balance": "Inventory Intelligence",
	"IQ Import Batch": "Data Intake",
	"IQ Exception": "Exception Management",
	"IQ Cost Line": "Cost Intelligence",
	"IQ Exchange Rate": "Cost Intelligence",
	"IQ Stock Movement": "Warehouse & Batch Control",
	"IQ Stock Ledger Entry": "Warehouse & Batch Control",
	"IQ Delivery": "Distribution & Delivery",
	"IQ Temperature Log": "Cold Chain Intelligence",
	"IQ Privilege": "Regulatory & Privileges",
	"IQ LC Case": "LC & Import Finance",
	"IQ Diplomatic ID": "Diplomatic Affairs",
	"IQ Diplomatic Persona": "Diplomatic Affairs",
	"IQ Personal Privilege": "Diplomatic Affairs",
	"IQ Portal User": "Partner Portals",
	"IQ Customs Case": "Customs Management",
}

IMPORT_TYPE_MODULE = {
	"Existing Stock": "Inventory Intelligence",
	"Inbound Shipments": "Shipment Control Tower",
	"Temperature Readings": "Cold Chain Intelligence",
}


class EntitlementError(frappe.ValidationError):
	pass


class UsageLimitError(frappe.ValidationError):
	pass


def get_entitlements(org: str) -> dict:
	from supplychain_iq.tenancy import _local_cache

	cache = _local_cache("iq_entitlements")
	if org not in cache:
		org_doc = frappe.db.get_value(
			"IQ Organization", org, ["package", "subscription_status", "enable_diplomatic_id", "organization_type"], as_dict=True
		) or frappe._dict()
		package = (
			frappe.db.get_value(
				"IQ Package",
				org_doc.package,
				["name", "is_active", "max_users", "max_shipments", "max_warehouses", "max_import_rows"],
				as_dict=True,
			)
			if org_doc.package
			else None
		) or frappe._dict()
		modules = set(
			frappe.get_all("IQ Package Module", filters={"parent": package.name or ""}, pluck="module")
		)
		active = org_doc.subscription_status in ("Trial", "Active") and bool(package.is_active)
		if not (org_doc.enable_diplomatic_id and org_doc.organization_type in DIPLOMATIC_ID_ORG_TYPES):
			modules.discard("Diplomatic Affairs")  # in the package but not switched on by the organization
		cache[org] = frappe._dict(
			package=package.name,
			active=active,
			modules=modules if active else set(),
			max_users=package.max_users or 0,
			max_shipments=package.max_shipments or 0,
			max_warehouses=package.max_warehouses or 0,
			max_import_rows=package.max_import_rows or 0,
		)
	return cache[org]


def has_module(org: str, module: str) -> bool:
	return module in get_entitlements(org).modules


def doctype_entitled(doctype: str, org: str) -> bool:
	module = DOCTYPE_MODULE.get(doctype)
	if not module:
		return get_entitlements(org).active
	return has_module(org, module)


def require_module(org: str, module: str):
	if not has_module(org, module):
		hint = (
			_(" An Org Admin must also enable it in the organization's Optional Features.")
			if module == "Diplomatic Affairs"
			else ""
		)
		frappe.throw(
			_("Your package does not include the {0} module, or the subscription is not active.").format(
				frappe.bold(module)
			)
			+ hint,
			EntitlementError,
		)


def enforce_entitlement(doc):
	org = doc.organization
	ent = get_entitlements(org)
	if not ent.active:
		frappe.throw(_("Organization {0} has no active subscription.").format(org), EntitlementError)
	module = DOCTYPE_MODULE.get(doc.doctype)
	if module:
		require_module(org, module)
	if doc.doctype == "IQ Import Batch":
		require_module(org, IMPORT_TYPE_MODULE[doc.import_type])
	if doc.is_new():
		check_usage_limit(doc.doctype, org)


def check_usage_limit(doctype: str, org: str, adding: int = 1):
	ent = get_entitlements(org)
	if doctype == "IQ Shipment" and ent.max_shipments:
		current = frappe.db.count(
			"IQ Shipment",
			{"organization": org, "status": ["not in", ["Closed", "Cancelled"]]},
		)
		if current + adding > ent.max_shipments:
			frappe.throw(
				_("Usage limit reached: your package allows {0} active shipments.").format(ent.max_shipments),
				UsageLimitError,
			)
	if doctype == "IQ Warehouse" and ent.max_warehouses:
		current = frappe.db.count("IQ Warehouse", {"organization": org})
		if current + adding > ent.max_warehouses:
			frappe.throw(
				_("Usage limit reached: your package allows {0} warehouses.").format(ent.max_warehouses),
				UsageLimitError,
			)


def check_user_limit(org: str, member_count: int):
	ent = get_entitlements(org)
	if ent.max_users and member_count > ent.max_users:
		frappe.throw(
			_("Usage limit reached: your package allows {0} users.").format(ent.max_users),
			UsageLimitError,
		)

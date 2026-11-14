"""Install hooks: roles and default package definitions (editable afterwards)."""

import frappe

IQ_ROLES = ("IQ Org Admin", "IQ Logistics Officer", "IQ Warehouse Officer", "IQ Viewer")

# Starting point only; pricing is deliberately not stored here.
DEFAULT_PACKAGES = {
	"IQ Essential": {
		"description": "Shipment register, basic inventory, file/manual intake, core dashboard and alerts.",
		"max_users": 5, "max_shipments": 100, "max_warehouses": 2, "max_import_rows": 2000,
		"modules": ["Shipment Control Tower", "Inventory Intelligence", "Data Intake", "Exception Management", "Unified Dashboard"],
	},
	"IQ Professional": {
		"description": "Essential plus procurement links and multimodal corridor management.",
		"max_users": 25, "max_shipments": 1000, "max_warehouses": 10, "max_import_rows": 10000,
		"modules": ["Shipment Control Tower", "Multimodal Corridor", "Procurement Intelligence", "Inventory Intelligence", "Data Intake", "Exception Management", "Unified Dashboard"],
	},
	"IQ Enterprise": {
		"description": "All modules, no usage limits.",
		"max_users": 0, "max_shipments": 0, "max_warehouses": 0, "max_import_rows": 0,
		"deployment_options": "SaaS or On-Premise",
		"modules": ["Shipment Control Tower", "Multimodal Corridor", "Procurement Intelligence", "Inventory Intelligence", "Data Intake", "Exception Management", "Unified Dashboard"],
	},
}


DASHBOARD_ROUTE = "desk/iq-dashboard"


def after_install():
	create_roles()
	create_default_packages()
	set_dashboard_as_home()


def after_migrate():
	create_roles()
	set_dashboard_as_home()


def create_roles():
	for role in IQ_ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def set_dashboard_as_home():
	"""Make the unified dashboard the landing page after login."""
	for role in (*IQ_ROLES, "System Manager"):
		if frappe.db.exists("Role", role) and frappe.db.get_value("Role", role, "home_page") != DASHBOARD_ROUTE:
			frappe.db.set_value("Role", role, "home_page", DASHBOARD_ROUTE)
	if frappe.db.get_single_value("System Settings", "default_app") != "supplychain_iq":
		frappe.db.set_single_value("System Settings", "default_app", "supplychain_iq")
	frappe.cache.delete_key("home_page")


def create_default_packages():
	for name, spec in DEFAULT_PACKAGES.items():
		if frappe.db.exists("IQ Package", name):
			continue
		spec = dict(spec)
		modules = spec.pop("modules")
		doc = frappe.get_doc({"doctype": "IQ Package", "package_name": name, "is_active": 1, **spec})
		for m in modules:
			doc.append("modules", {"module": m})
		doc.insert(ignore_permissions=True)

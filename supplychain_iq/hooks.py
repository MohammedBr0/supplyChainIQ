app_name = "supplychain_iq"
app_title = "SupplyChain IQ"
app_publisher = "SupplyChain IQ"
app_description = "End-to-end supply-chain intelligence layer"
app_email = "dev@supplychainiq.invalid"
app_license = "Proprietary"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "supplychain_iq",
# 		"logo": "/assets/supplychain_iq/logo.png",
# 		"title": "SupplyChain IQ",
# 		"route": "/supplychain_iq",
# 		"has_permission": "supplychain_iq.api.permission.has_app_permission",
# 	}
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `supplychain_iq/dock/supplychain_iq/supplychain_iq.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/supplychain_iq/css/supplychain_iq.css"
# app_include_js = "/assets/supplychain_iq/js/supplychain_iq.js"

# include js, css files in header of web template
# web_include_css = "/assets/supplychain_iq/css/supplychain_iq.css"
# web_include_js = "/assets/supplychain_iq/js/supplychain_iq.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "supplychain_iq/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_kanban_js = {"doctype" : "public/js/doctype_kanban.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "supplychain_iq/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "supplychain_iq.utils.jinja_methods",
# 	"filters": "supplychain_iq.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "supplychain_iq.install.before_install"
# after_install = "supplychain_iq.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "supplychain_iq.uninstall.before_uninstall"
# after_uninstall = "supplychain_iq.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "supplychain_iq.utils.before_app_install"
# after_app_install = "supplychain_iq.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "supplychain_iq.utils.before_app_uninstall"
# after_app_uninstall = "supplychain_iq.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "supplychain_iq.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "supplychain_iq.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "supplychain_iq.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["supplychain_iq.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"supplychain_iq.tasks.all"
# 	],
# 	"daily": [
# 		"supplychain_iq.tasks.daily"
# 	],
# 	"hourly": [
# 		"supplychain_iq.tasks.hourly"
# 	],
# 	"weekly": [
# 		"supplychain_iq.tasks.weekly"
# 	],
# 	"monthly": [
# 		"supplychain_iq.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "supplychain_iq.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "supplychain_iq.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "supplychain_iq.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "supplychain_iq.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["supplychain_iq.utils.before_request"]
# after_request = ["supplychain_iq.utils.after_request"]

# Job Events
# ----------
# before_job = ["supplychain_iq.utils.before_job"]
# after_job = ["supplychain_iq.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"supplychain_iq.auth.validate"
# ]

# on_social_login = "supplychain_iq.auth.on_social_login"

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []



# ------------------------------------------------------------------ SupplyChain IQ

add_to_apps_screen = [
	{
		"name": "supplychain_iq",
		"logo": "/assets/supplychain_iq/images/iq-logo.svg",
		"title": "SupplyChain IQ",
		"route": "/desk/iq-dashboard",
	}
]

app_home = "/desk/iq-dashboard"

# The unified dashboard is the main route: site root, login and the apps screen land on it.
website_redirects = [
	{"source": r"/", "target": "/desk/iq-dashboard", "redirect_http_status": 302},
]

after_install = "supplychain_iq.setup.install.after_install"
after_migrate = "supplychain_iq.setup.install.after_migrate"

_TENANT = {
	"IQ Supplier": "supplier_pqc",
	"IQ Purchase Order": "purchase_order_pqc",
	"IQ Shipment": "shipment_pqc",
	"IQ Warehouse": "warehouse_pqc",
	"IQ Item": "item_pqc",
	"IQ Stock Balance": "stock_balance_pqc",
	"IQ Import Batch": "import_batch_pqc",
	"IQ Exception": "exception_pqc",
}

permission_query_conditions = {dt: f"supplychain_iq.tenancy.{fn}" for dt, fn in _TENANT.items()}
permission_query_conditions["IQ Organization"] = "supplychain_iq.tenancy.organization_pqc"

has_permission = {dt: "supplychain_iq.tenancy.has_permission" for dt in _TENANT}
has_permission["IQ Organization"] = "supplychain_iq.tenancy.organization_has_permission"

doc_events = {dt: {"validate": "supplychain_iq.tenancy.validate_tenant_document"} for dt in _TENANT}

scheduler_events = {
	"daily": ["supplychain_iq.intelligence.exceptions.run_all_organizations"],
}

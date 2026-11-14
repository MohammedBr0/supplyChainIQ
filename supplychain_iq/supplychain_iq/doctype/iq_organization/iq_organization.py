# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from supplychain_iq import tenancy

# commercial fields only platform staff may change
PLATFORM_FIELDS = ("package", "subscription_status", "deployment", "organization_name")

IQ_ROLE_MAP = {
	"Org Admin": "IQ Org Admin",
	"Logistics Officer": "IQ Logistics Officer",
	"Warehouse Officer": "IQ Warehouse Officer",
	"QA Officer": "IQ QA Officer",
	"Compliance Officer": "IQ Compliance Officer",
	"HR Officer": "IQ HR Officer",
	"Protocol Officer": "IQ Protocol Officer",
	"Viewer": "IQ Viewer",
}
ALL_IQ_ROLES = set(IQ_ROLE_MAP.values())


class IQOrganization(Document):
	def validate(self):
		admin = tenancy.is_platform_admin()
		before = self.get_doc_before_save()
		if not admin:
			if self.is_new():
				frappe.throw(_("Only platform administrators can create organizations."), frappe.PermissionError)
			for f in PLATFORM_FIELDS:
				if self.get(f) != before.get(f):
					frappe.throw(_("Only platform administrators can change {0}.").format(_(self.meta.get_label(f))), frappe.PermissionError)
		if self.enable_diplomatic_id:
			from supplychain_iq.entitlements import DIPLOMATIC_ID_ORG_TYPES

			if self.organization_type not in DIPLOMATIC_ID_ORG_TYPES:
				frappe.throw(
					_("The Diplomatic Affairs app can only be enabled for NGO / INGO / UN-related and international organizations.")
				)
		if self.base_currency:
			self.base_currency = self.base_currency.strip().upper()
		self.validate_members()
		tenancy.clear_cache()

	def validate_members(self):
		users = [m.user for m in self.members]
		if len(users) != len(set(users)):
			frappe.throw(_("A user can only be listed once."))
		for user in users:
			other = frappe.db.get_value(
				"IQ Organization User",
				{"user": user, "parenttype": "IQ Organization", "parent": ["!=", self.name or ""]},
				"parent",
			)
			if other:
				frappe.throw(_("User {0} already belongs to organization {1}.").format(user, other))
			if frappe.db.exists("IQ Portal User", {"user": user}):
				frappe.throw(_("User {0} is a partner portal user and cannot also be a staff member.").format(user))
		if self.package:
			check_user_limit_for(self.package, len(users))

	def on_update(self):
		self.sync_user_roles()
		tenancy.clear_cache()

	def sync_user_roles(self):
		"""Give each member exactly the Frappe role matching their IQ role."""
		before = self.get_doc_before_save()
		removed = {m.user for m in (before.members if before else [])} - {m.user for m in self.members}
		for m in self.members:
			user = frappe.get_doc("User", m.user)
			wanted = IQ_ROLE_MAP[m.iq_role]
			current = {r.role for r in user.roles}
			if wanted in current and not (current & ALL_IQ_ROLES - {wanted}):
				continue
			user.flags.ignore_permissions = True
			user.remove_roles(*(ALL_IQ_ROLES - {wanted}))
			user.add_roles(wanted)
		for u in removed:
			if frappe.db.exists("User", u):
				user = frappe.get_doc("User", u)
				user.flags.ignore_permissions = True
				user.remove_roles(*ALL_IQ_ROLES)


def check_user_limit_for(package, count):
	max_users = frappe.db.get_value("IQ Package", package, "max_users") or 0
	if max_users and count > max_users:
		from supplychain_iq.entitlements import UsageLimitError

		frappe.throw(_("Usage limit reached: package {0} allows {1} users.").format(package, max_users), UsageLimitError)

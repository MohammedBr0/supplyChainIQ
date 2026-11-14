# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from supplychain_iq import tenancy

PORTAL_ROLE = {"Supplier": "IQ Supplier Portal", "Transitor": "IQ Transitor Portal"}
ALL_PORTAL_ROLES = set(PORTAL_ROLE.values())
SAFE_ROLES = ALL_PORTAL_ROLES | {"All", "Guest"}


class IQPortalUser(Document):
	def validate(self):
		if self.portal_type == "Supplier":
			if not self.supplier:
				frappe.throw(_("Select the supplier this login belongs to."))
			self.transitor = None
		else:
			if not self.transitor:
				frappe.throw(_("Select the transitor this login belongs to."))
			self.supplier = None
		if self.user in ("Administrator", "Guest"):
			frappe.throw(_("This user cannot be a portal user."))
		if frappe.db.exists("IQ Portal User", {"user": self.user, "name": ["!=", self.name or ""]}):
			frappe.throw(_("{0} is already linked to a partner portal.").format(self.user))
		if frappe.db.exists("IQ Organization User", {"user": self.user, "parenttype": "IQ Organization"}):
			frappe.throw(_("{0} is a staff member of an organization and cannot be a portal user.").format(self.user))
		other_roles = set(frappe.get_roles(self.user)) - SAFE_ROLES
		if other_roles:
			frappe.throw(_("{0} has internal roles ({1}); use a separate login for portal access.").format(self.user, ", ".join(sorted(other_roles))))

	def after_insert(self):
		"""Invite the partner: email with a set-password link when mail is configured, else tell the admins."""
		from supplychain_iq import notify

		if notify.email_enabled() and self.is_active:
			try:
				frappe.get_doc("User", self.user).send_welcome_mail_to_user()
			except Exception:
				frappe.log_error(title="IQ portal invitation email failed")
		else:
			notify.send(notify.members(self.organization), f"Portal access created for {self.user}", self,
				"No outgoing email account is configured: share the portal address (/iq-portal) and a password with the partner yourself.")

	def on_update(self):
		self.sync_roles()
		tenancy.clear_cache()

	def on_trash(self):
		self.is_active = 0
		self.sync_roles()

	def sync_roles(self):
		user = frappe.get_doc("User", self.user)
		user.flags.ignore_permissions = True
		wanted = PORTAL_ROLE[self.portal_type] if self.is_active else None
		remove = ALL_PORTAL_ROLES - {wanted}
		if remove & {r.role for r in user.roles}:
			user.remove_roles(*remove)
		if wanted and wanted not in {r.role for r in user.roles}:
			user.add_roles(wanted)

"""Diplomatic Affairs app dashboard data (personal data: restricted roles only)."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from supplychain_iq import tenancy
from supplychain_iq.diplomatic_affairs.access import APP_ROLES, MODULE
from supplychain_iq.entitlements import has_module, require_module

DIPLOMATIC_EXCEPTIONS = ("Diplomatic ID Renewal", "Renewal Follow-up", "Personal Privilege Expiry", "Privilege Quota",
	"Passport Expiry", "Departure Close-out")


def _org(organization=None):
	if tenancy.is_platform_admin():
		org = organization or tenancy.get_user_organization() or frappe.db.get_value(
			"IQ Organization", {"enable_diplomatic_id": 1}, "name", order_by="creation asc"
		)
		if not org:
			frappe.throw(_("No organization has the Diplomatic Affairs app enabled."))
		return org
	if not APP_ROLES.intersection(frappe.get_roles()):
		frappe.throw(_("The Diplomatic Affairs app is limited to Protocol Officers, HR Officers and Org Admins."), frappe.PermissionError)
	return tenancy.require_organization()


@frappe.whitelist()
def get_organizations():
	if tenancy.is_platform_admin():
		return frappe.get_all("IQ Organization", filters={"enable_diplomatic_id": 1}, pluck="name", order_by="name")
	return [_org()]


@frappe.whitelist()
def get_data(organization: str | None = None):
	org = _org(organization)
	require_module(org, MODULE)
	t = getdate(today())
	f = {"organization": org}
	personas = frappe.get_all(
		"IQ Diplomatic Persona", filters=f,
		fields=["name", "full_name", "diplomatic_category", "persona_status", "assignment_end_date", "passport_expiry",
			"active_ids", "active_privileges", "next_expiry", "position"],
	)
	active = [p for p in personas if p.persona_status != "Departed"]
	ids = frappe.get_all(
		"IQ Diplomatic ID", filters=f,
		fields=["name", "employee_name", "persona", "id_type", "expiry_date", "id_status", "renewal_status", "next_follow_up", "days_to_expiry"],
		order_by="expiry_date asc",
	)
	departed = {p.name for p in personas if p.persona_status == "Departed"}
	ids = [i for i in ids if i.persona not in departed]
	privs = frappe.get_all(
		"IQ Personal Privilege", filters=f,
		fields=["name", "full_name", "persona", "privilege_type", "expiry_date", "validity_status", "review_status",
			"quota_value", "quota_unit", "used_value", "quota_used_pct"],
		order_by="expiry_date asc",
	)
	privs = [p for p in privs if p.persona not in departed]
	data = {
		"organization": org,
		"as_of": str(t),
		"personas": {
			"active": len(active),
			"by_category": _count(active, "diplomatic_category"),
			"departing_60d": sorted(
				[p for p in active if p.assignment_end_date and 0 <= (getdate(p.assignment_end_date) - t).days <= 60],
				key=lambda p: p.assignment_end_date,
			),
			"passport_180d": [p for p in active if p.passport_expiry and (getdate(p.passport_expiry) - t).days <= 180],
		},
		"ids": {
			"total": len(ids),
			"by_status": _count(ids, "id_status"),
			"in_renewal": [i for i in ids if i.renewal_status not in ("Not Started", "Collected")],
			"due": [i for i in ids if i.id_status in ("Renewal Due", "Expired") and i.renewal_status in ("Not Started", "Collected")],
			"follow_up_overdue": [i for i in ids if i.next_follow_up and getdate(i.next_follow_up) < t and i.renewal_status in ("Submitted", "Additional Information Requested")],
		},
		"privileges": {
			"total": len(privs),
			"by_type": _count(privs, "privilege_type"),
			"pending_review": [p for p in privs if p.review_status in ("Draft", "Under Review", "Needs Legal Review")],
			"expiring": [p for p in privs if p.validity_status in ("Expiring Soon", "Expired") and p.review_status != "Revoked"],
			"quota_high": [p for p in privs if p.quota_value and (p.quota_used_pct or 0) >= 75],
		},
		"exceptions": frappe.get_all(
			"IQ Exception",
			filters={**f, "status": ["in", ["Open", "In Progress"]], "exception_type": ["in", DIPLOMATIC_EXCEPTIONS]},
			fields=["name", "title", "severity", "due_date", "reference_doctype", "reference_name"],
			order_by="due_date asc",
			limit=15,
		),
	}
	if has_module(org, "Regulatory & Privileges"):
		org_privs = frappe.get_all(
			"IQ Privilege", filters={**f, "review_status": ["!=", "Revoked"]},
			fields=["name", "title", "privilege_type", "validity_status", "review_status", "expiry_date"],
			order_by="expiry_date asc",
		)
		data["org_privileges"] = {"by_validity": _count(org_privs, "validity_status"), "list": org_privs[:10]}
	return data


def _count(rows, field):
	out = {}
	for r in rows:
		k = r.get(field) or "Not set"
		out[k] = out.get(k, 0) + 1
	return out

"""Append-only audit trail for SupplyChain IQ records.

Every create / change / delete / submit / cancel of an IQ DocType writes an
IQ Audit Event (who, when, IP, what changed). Events cannot be edited or
deleted through the application. Child-table changes are summarised per table.
"""

import frappe
from frappe.utils import cstr, now_datetime

SKIP = {"IQ Audit Event", "IQ Integration Log", "IQ Stock Ledger Entry"}
IGNORED_FIELDS = {"modified", "modified_by", "creation", "owner", "idx", "_user_tags", "_comments", "_assign", "_liked_by", "_seen"}
MAX_SUMMARY = 3000


def _tracked(doc) -> bool:
	return doc.doctype.startswith("IQ ") and doc.doctype not in SKIP and not doc.meta.istable and not frappe.flags.in_install


def _org(doc):
	if doc.doctype == "IQ Organization":
		return doc.name
	return doc.get("organization")


def _short(value):
	text = cstr(value)
	return text if len(text) <= 80 else text[:77] + "..."


def changes(doc) -> str:
	before = doc.get_doc_before_save()
	if not before:
		return ""
	parts = []
	for df in doc.meta.fields:
		f = df.fieldname
		if f in IGNORED_FIELDS or df.fieldtype in ("Section Break", "Column Break", "Tab Break", "HTML", "Button"):
			continue
		if df.fieldtype in ("Table", "Table MultiSelect"):
			old = [r.as_dict(no_default_fields=True) for r in before.get(f) or []]
			new = [r.as_dict(no_default_fields=True) for r in doc.get(f) or []]
			if old != new:
				parts.append(f"{df.label or f}: {len(old)} -> {len(new)} row(s) (changed)")
			continue
		if df.fieldtype in ("Password",):
			continue
		old, new = before.get(f), doc.get(f)
		if cstr(old) != cstr(new) and not (old in (None, "", 0) and new in (None, "", 0)):
			parts.append(f"{df.label or f}: {_short(old) or '-'} -> {_short(new) or '-'}")
	return "\n".join(parts)


def record(doc, action, summary=""):
	ev = frappe.get_doc({
		"doctype": "IQ Audit Event",
		"organization": _org(doc),
		"event_time": now_datetime(),
		"user": frappe.session.user,
		"action": action,
		"reference_doctype": doc.doctype,
		"reference_name": doc.name,
		"ip_address": getattr(frappe.local, "request_ip", None),
		"summary": (summary or "")[:MAX_SUMMARY],
	})
	ev.flags.ignore_permissions = True
	ev.flags.iq_audit_insert = True
	ev.insert(ignore_links=True)


# ---------------------------------------------------------------- doc event handlers (hooks.py "*")


def after_insert(doc, method=None):
	if _tracked(doc):
		record(doc, "Create")


def on_update(doc, method=None):
	if _tracked(doc) and not doc.flags.get("iq_audit_skip") and doc.get_doc_before_save():
		summary = changes(doc)
		if summary:
			record(doc, "Update", summary)


def on_submit(doc, method=None):
	if _tracked(doc):
		record(doc, "Submit")


def on_cancel(doc, method=None):
	if _tracked(doc):
		record(doc, "Cancel")


def on_trash(doc, method=None):
	if doc.doctype == "IQ Audit Event" and not frappe.flags.iq_audit_purge:
		frappe.throw("Audit events cannot be deleted.", frappe.PermissionError)
	if _tracked(doc):
		record(doc, "Delete", f"Deleted {doc.doctype} {doc.name}")


def portal_action(doc, text):
	record(doc, "Portal", text)


def integration_action(doc, text):
	record(doc, "Integration", text)


# ---------------------------------------------------------------- permissions for the log doctypes


def _org_condition(doctype, user):
	from supplychain_iq import tenancy

	user = user or frappe.session.user
	if tenancy.is_platform_admin(user):
		return ""
	org = tenancy.get_user_organization(user)
	if not org or "IQ Org Admin" not in frappe.get_roles(user):
		return "1=0"
	return f"`tab{doctype}`.`organization` = {frappe.db.escape(org)}"


def audit_pqc(user=None, doctype=None):
	return _org_condition("IQ Audit Event", user)


def integration_log_pqc(user=None, doctype=None):
	return _org_condition("IQ Integration Log", user)


def log_has_permission(doc, ptype=None, user=None, debug=False):
	from supplychain_iq import tenancy

	user = user or frappe.session.user
	if tenancy.is_platform_admin(user):
		return ptype in (None, "read", "report", "export", "print")
	return (
		ptype in (None, "read", "report", "export", "print")
		and "IQ Org Admin" in frappe.get_roles(user)
		and doc.get("organization") == tenancy.get_user_organization(user)
	)

"""In-app (and, when configured, email) notifications for organization members.

In-app notifications always work (Notification Log, the bell icon). Email is
sent only when the site has an enabled outgoing Email Account, so a fresh
deployment never fails because mail is not set up.
"""

import frappe
from frappe.utils import get_url_to_form

# which IQ roles care about which exception types (Org Admins always do)
EXCEPTION_ROLES = {
	"Shipment Delay": ("Logistics Officer",), "Overdue Milestone": ("Logistics Officer",),
	"Missing Document": ("Logistics Officer",), "Demurrage Exposure": ("Logistics Officer",),
	"Cost Overrun": ("Logistics Officer",), "Customs Delay": ("Logistics Officer",), "Duties Unpaid": ("Logistics Officer",),
	"LC Deadline": ("Logistics Officer", "Compliance Officer"),
	"Privilege Expiry": ("Compliance Officer",), "Privilege Conflict": ("Compliance Officer", "Logistics Officer"),
	"Stock Out": ("Warehouse Officer",), "Low Stock": ("Warehouse Officer",), "Expiry Risk": ("Warehouse Officer",),
	"Expired Stock": ("Warehouse Officer", "QA Officer"), "Receipt Discrepancy": ("Warehouse Officer", "Logistics Officer"),
	"Delivery Overdue": ("Warehouse Officer",), "Delivery Shortfall": ("Warehouse Officer",),
	"QA Hold": ("QA Officer",), "Temperature Excursion": ("QA Officer", "Logistics Officer"),
}
RESTRICTED_ROLES = ("Protocol Officer", "HR Officer")


def members(org: str, iq_roles=()) -> list[str]:
	"""Active members of the organization with any of the IQ roles, plus Org Admins."""
	roles = set(iq_roles) | {"Org Admin"}
	users = frappe.get_all(
		"IQ Organization User", filters={"parent": org, "parenttype": "IQ Organization", "iq_role": ["in", list(roles)]}, pluck="user"
	)
	return [u for u in dict.fromkeys(users) if frappe.db.get_value("User", u, "enabled")]


def email_enabled() -> bool:
	return bool(frappe.db.exists("Email Account", {"enable_outgoing": 1}))


def send(users, subject: str, doc=None, message: str | None = None):
	users = [u for u in dict.fromkeys(users or []) if u and u not in ("Administrator", "Guest")]
	if not users:
		return 0
	for user in users:
		log = frappe.get_doc({
			"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": subject[:140],
			"email_content": message or subject, "document_type": doc.doctype if doc else None,
			"document_name": doc.name if doc else None, "from_user": frappe.session.user,
		})
		log.flags.ignore_permissions = True
		log.insert(ignore_links=True)
	if email_enabled():
		link = f'<p><a href="{get_url_to_form(doc.doctype, doc.name)}">{frappe.utils.escape_html(doc.name)}</a></p>' if doc else ""
		try:
			frappe.sendmail(recipients=users, subject=subject[:140], message=(message or subject) + link,
				reference_doctype=doc.doctype if doc else None, reference_name=doc.name if doc else None)
		except Exception:
			frappe.log_error(title="IQ notification email failed")
	return len(users)


def exception_created(exc):
	if exc.severity not in ("High", "Critical"):
		return 0
	if not frappe.db.get_value("IQ Organization", exc.organization, "notify_high_exceptions"):
		return 0
	roles = RESTRICTED_ROLES if exc.restricted else EXCEPTION_ROLES.get(exc.exception_type, ())
	recipients = members(exc.organization, roles)
	if exc.assigned_to:
		recipients.append(exc.assigned_to)
	return send(recipients, f"[{exc.severity}] {exc.title}", exc, exc.description)


def exception_assigned(exc):
	return send([exc.assigned_to], f"Assigned to you: {exc.title}", exc, exc.description)


def portal_activity(doc, text):
	org = doc.get("organization")
	if not org or not frappe.db.get_value("IQ Organization", org, "notify_portal_activity"):
		return 0
	return send(members(org, ("Logistics Officer",)), f"Partner update on {doc.name}", doc, text)

"""Rule-based exception detection.

Each rule is deterministic and records the values that triggered it. Open
exceptions are de-duplicated by a fingerprint and auto-resolved when the
triggering condition clears. Runs daily for all active organizations and on
demand from the dashboard.
"""

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from supplychain_iq.entitlements import get_entitlements, has_module
from supplychain_iq.intelligence import calculations as calc

OPEN_STATUSES = ("Open", "In Progress")
SHIPMENT_OPEN = ("Planned", "Booked", "In Transit", "At Port", "Customs Clearance", "Released")


def run_all_organizations():
	for org in frappe.get_all("IQ Organization", filters={"subscription_status": ["in", ["Trial", "Active"]]}, pluck="name"):
		try:
			run_for_organization(org)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"IQ exception checks failed for {org}")


def run_for_organization(org: str) -> dict:
	if not has_module(org, "Exception Management"):
		return {"skipped": "Exception Management not in package"}
	settings = frappe.db.get_value(
		"IQ Organization",
		org,
		["expiry_warning_days", "low_stock_cover_months", "delay_high_days", "delay_critical_days"],
		as_dict=True,
	)
	t = getdate(today())
	findings = {}
	if has_module(org, "Shipment Control Tower"):
		findings.update(shipment_findings(org, settings, t))
	if has_module(org, "Inventory Intelligence"):
		findings.update(stock_findings(org, settings, t))
	return sync_exceptions(org, findings)


def _finding(etype, severity, title, doctype, name, description, due=None):
	return {
		"exception_type": etype,
		"severity": severity,
		"title": title[:140],
		"reference_doctype": doctype,
		"reference_name": name,
		"description": description,
		"due_date": due,
	}


def shipment_findings(org, s, t):
	out = {}
	shipments = frappe.get_all(
		"IQ Shipment",
		filters={"organization": org, "status": ["in", SHIPMENT_OPEN]},
		fields=["name", "shipment_title", "status", "planned_eta", "actual_eta", "awb_bl_number"],
	)
	for sh in shipments:
		delay = calc.shipment_delay_days(sh.planned_eta, sh.actual_eta, sh.status, t)
		if delay > 0 and not sh.actual_eta:
			sev = calc.delay_severity(delay, s.delay_high_days or 14, s.delay_critical_days or 30)
			out[f"delay:{sh.name}"] = _finding(
				"Shipment Delay", sev,
				f"{sh.shipment_title}: {delay} days past planned ETA",
				"IQ Shipment", sh.name,
				f"Planned ETA {sh.planned_eta}; status '{sh.status}'; no actual arrival recorded. AWB/BL: {sh.awb_bl_number or '-'}.",
				add_days(t, 2),
			)
		doc = frappe.get_doc("IQ Shipment", sh.name)
		for m in doc.milestones:
			st = calc.milestone_status(m.planned_date and getdate(m.planned_date), m.actual_date and getdate(m.actual_date), m.status, t)
			if st == "Overdue":
				out[f"milestone:{sh.name}:{m.name}"] = _finding(
					"Overdue Milestone", "Medium",
					f"{sh.shipment_title}: '{m.milestone}' overdue",
					"IQ Shipment", sh.name,
					f"Milestone '{m.milestone}' planned for {m.planned_date} has no actual date. Responsible: {m.responsible_party or 'not set'}.",
					add_days(t, 1),
				)
		eta = getdate(sh.planned_eta) if sh.planned_eta else None
		near = sh.status in ("At Port", "Customs Clearance") or (eta and (eta - t).days <= 7)
		if near:
			missing = [d.document_type for d in doc.documents if d.required and not d.received]
			if missing:
				out[f"docs:{sh.name}"] = _finding(
					"Missing Document", "High" if sh.status in ("At Port", "Customs Clearance") else "Medium",
					f"{sh.shipment_title}: {len(missing)} required document(s) missing",
					"IQ Shipment", sh.name,
					f"Missing: {', '.join(missing)}. Status '{sh.status}', planned ETA {sh.planned_eta}.",
					add_days(t, 1),
				)
	return out


def stock_findings(org, s, t):
	out = {}
	balances = frappe.get_all(
		"IQ Stock Balance",
		filters={"organization": org},
		fields=["name", "item", "item_name", "warehouse", "batch_no", "quantity", "avg_monthly_consumption", "expiry_date"],
	)
	low_threshold = s.low_stock_cover_months or 1
	warn_days = s.expiry_warning_days or 90
	for b in balances:
		label = f"{b.item_name or b.item} @ {b.warehouse}" + (f" (batch {b.batch_no})" if b.batch_no else "")
		cover = calc.stock_cover_months(b.quantity, b.avg_monthly_consumption)
		exp_days = calc.days_to_expiry(getdate(b.expiry_date) if b.expiry_date else None, t)
		if exp_days is not None and exp_days < 0:
			if (b.quantity or 0) > 0:
				out[f"expired:{b.name}"] = _finding(
					"Expired Stock", "High", f"{label}: expired stock on hand", "IQ Stock Balance", b.name,
					f"{b.quantity} units expired on {b.expiry_date}. Quarantine and decide disposition; IQ does not release or write off stock.",
					t,
				)
			continue
		if (b.quantity or 0) <= 0:
			if b.avg_monthly_consumption:
				out[f"stockout:{b.name}"] = _finding(
					"Stock Out", "High", f"{label}: out of stock", "IQ Stock Balance", b.name,
					f"Quantity 0 with average monthly consumption {b.avg_monthly_consumption}.", t,
				)
			continue
		if exp_days is not None and exp_days <= warn_days:
			out[f"expiry:{b.name}"] = _finding(
				"Expiry Risk", "High" if exp_days <= 30 else "Medium",
				f"{label}: expires in {exp_days} days", "IQ Stock Balance", b.name,
				f"{b.quantity} units expire on {b.expiry_date} (warning window {warn_days} days)."
				+ (f" At current consumption {cover} months of stock remain." if cover is not None else ""),
				add_days(t, min(exp_days, 14)),
			)
		if cover is not None and cover < low_threshold:
			out[f"low:{b.name}"] = _finding(
				"Low Stock", "Medium", f"{label}: {cover} months of stock cover", "IQ Stock Balance", b.name,
				f"Quantity {b.quantity} / average monthly consumption {b.avg_monthly_consumption} = {cover} months (threshold {low_threshold}).",
				add_days(t, 7),
			)
	return out


def sync_exceptions(org, findings: dict) -> dict:
	existing = frappe.get_all(
		"IQ Exception",
		filters={"organization": org, "auto_generated": 1, "status": ["in", OPEN_STATUSES]},
		fields=["name", "fingerprint", "severity", "title", "description"],
	)
	by_fp = {e.fingerprint: e for e in existing}
	created = updated = resolved = 0
	for fp, f in findings.items():
		if fp in by_fp:
			e = by_fp[fp]
			if (e.severity, e.title, e.description) != (f["severity"], f["title"], f["description"]):
				frappe.db.set_value("IQ Exception", e.name, {k: f[k] for k in ("severity", "title", "description")})
				updated += 1
			continue
		doc = frappe.get_doc({
			"doctype": "IQ Exception", "organization": org, "status": "Open", "fingerprint": fp,
			"auto_generated": 1, "detected_on": now_datetime(), **f,
		})
		doc.flags.ignore_permissions = True
		doc.insert()
		created += 1
	for fp, e in by_fp.items():
		if fp not in findings:
			doc = frappe.get_doc("IQ Exception", e.name)
			doc.status = "Resolved"
			doc.resolution_notes = (doc.resolution_notes or "") + f"\nCondition cleared - auto-resolved on {today()}."
			doc.flags.iq_auto = True
			doc.flags.ignore_permissions = True
			doc.save()
			resolved += 1
	return {"created": created, "updated": updated, "resolved": resolved, "open": len(findings)}

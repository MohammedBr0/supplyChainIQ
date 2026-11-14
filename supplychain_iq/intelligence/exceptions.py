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
from supplychain_iq.intelligence import costs

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
		["expiry_warning_days", "low_stock_cover_months", "delay_high_days", "delay_critical_days",
			"demurrage_warning_days", "cost_overrun_pct", "privilege_warning_days", "lc_warning_days",
			"diplomatic_id_warning_days"],
		as_dict=True,
	)
	t = getdate(today())
	findings = {}
	if has_module(org, "Shipment Control Tower"):
		findings.update(shipment_findings(org, settings, t))
	if has_module(org, "Cost Intelligence"):
		findings.update(cost_findings(org, settings, t))
	if has_module(org, "Inventory Intelligence"):
		findings.update(stock_findings(org, settings, t))
	if has_module(org, "Warehouse & Batch Control"):
		findings.update(receipt_findings(org, t))
	if has_module(org, "Distribution & Delivery"):
		findings.update(delivery_findings(org, t))
	if has_module(org, "Cold Chain Intelligence"):
		findings.update(cold_chain_findings(org, t))
	if has_module(org, "Regulatory & Privileges"):
		findings.update(privilege_findings(org, settings, t))
	if has_module(org, "LC & Import Finance"):
		findings.update(lc_findings(org, settings, t))
	if has_module(org, "Diplomatic Affairs"):
		findings.update(diplomatic_findings(org, settings, t))
	return sync_exceptions(org, findings)


def _finding(etype, severity, title, doctype, name, description, due=None, restricted=0):
	return {
		"restricted": restricted,
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
		dem = costs.shipment_demurrage(doc)
		if dem["free_time_ends"] and dem["days_left"] is not None:
			warn = s.demurrage_warning_days if s.demurrage_warning_days is not None else 3
			cur = doc.demurrage_currency or ""
			if dem["days"] > 0:
				out[f"demurrage:{sh.name}"] = _finding(
					"Demurrage Exposure", "High" if dem["days"] <= 7 else "Critical",
					f"{sh.shipment_title}: {dem['days']} chargeable demurrage days",
					"IQ Shipment", sh.name,
					f"Free time ({doc.free_time_days} days from {doc.free_time_start}) ended {dem['free_time_ends']}. "
					f"Exposure so far {dem['exposure']:,.2f} {cur} at {doc.demurrage_rate_per_day or 0:,.2f}/day; cargo not yet released.",
					t,
				)
			elif dem["days_left"] <= warn:
				out[f"demurrage:{sh.name}"] = _finding(
					"Demurrage Exposure", "Medium",
					f"{sh.shipment_title}: free time ends in {dem['days_left']} days",
					"IQ Shipment", sh.name,
					f"Free time ends {dem['free_time_ends']}; charges of {doc.demurrage_rate_per_day or 0:,.2f} {cur}/day start after that unless the cargo is released.",
					dem["free_time_ends"],
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


def cost_findings(org, s, t):
	out = {}
	threshold = s.cost_overrun_pct if s.cost_overrun_pct is not None else 10
	shipments = frappe.get_all(
		"IQ Shipment",
		filters={"organization": org, "status": ["!=", "Cancelled"], "cost_lines_count": [">", 0]},
		fields=["name", "shipment_title", "base_currency"],
	)
	for sh in shipments:
		summary = costs.shipment_cost_summary(sh.name)
		pct = summary["overrun_pct"]
		if pct is not None and pct > threshold:
			out[f"overrun:{sh.name}"] = _finding(
				"Cost Overrun", "High" if pct > 2 * threshold else "Medium",
				f"{sh.shipment_title}: actual costs {pct}% above estimate",
				"IQ Shipment", sh.name,
				f"Categories with both estimate and actual: estimated {summary['compared_estimate']:,.2f}, "
				f"actual {summary['compared_actual']:,.2f} {sh.base_currency or ''} (alert threshold {threshold}%).",
				add_days(t, 7),
			)
	return out


def receipt_findings(org, t):
	out = {}
	for sh in frappe.get_all(
		"IQ Shipment",
		filters={"organization": org, "status": ["in", ["Delivered", "Closed"]], "received_quantity": [">", 0], "quantity": [">", 0]},
		fields=["name", "shipment_title", "quantity", "received_quantity", "uom", "last_receipt"],
	):
		diff = round((sh.received_quantity or 0) - (sh.quantity or 0), 6)
		if diff:
			out[f"receipt:{sh.name}"] = _finding(
				"Receipt Discrepancy", "High" if abs(diff) / sh.quantity > 0.05 else "Medium",
				f"{sh.shipment_title}: received {sh.received_quantity:g} vs shipped {sh.quantity:g} {sh.uom or ''}",
				"IQ Shipment", sh.name,
				f"{'Short' if diff < 0 else 'Over'} by {abs(diff):g} {sh.uom or ''} (last receipt {sh.last_receipt}). "
				"Check packing list, damage records and carrier claims. Receipt quantities are summed across receipts in item units; confirm the units match the shipment UOM.",
				add_days(t, 5),
			)
	return out


def delivery_findings(org, t):
	out = {}
	for d in frappe.get_all(
		"IQ Delivery",
		filters={"organization": org, "status": ["in", ["Draft", "Dispatched", "Partially Delivered"]]},
		fields=["name", "recipient", "destination", "status", "planned_delivery_date", "dispatched_on"],
	):
		if d.status == "Partially Delivered":
			out[f"dlvshort:{d.name}"] = _finding(
				"Delivery Shortfall", "High", f"Short delivery to {d.recipient}", "IQ Delivery", d.name,
				f"Delivery to {d.recipient} ({d.destination}) was confirmed with less than the dispatched quantity. "
				"Record returned goods (Adjustment In) or a loss, then dismiss this exception with notes.",
				add_days(t, 3),
			)
			continue
		late = (t - getdate(d.planned_delivery_date)).days
		if late > 0:
			out[f"dlvlate:{d.name}"] = _finding(
				"Delivery Overdue", "High" if late > 3 else "Medium",
				f"Delivery to {d.recipient} {late} days overdue", "IQ Delivery", d.name,
				f"Planned {d.planned_delivery_date}; status '{d.status}'"
				+ (f", dispatched {d.dispatched_on}" if d.dispatched_on else ", not yet dispatched") + ".",
				t,
			)
	return out


def cold_chain_findings(org, t):
	out = {}
	since = add_days(t, -14)
	for r in frappe.get_all(
		"IQ Temperature Log",
		filters={"organization": org, "is_excursion": 1, "location_type": "Shipment", "reading_time": [">=", since]},
		fields=["name", "shipment", "temperature", "min_allowed", "max_allowed", "reading_time", "logger_id"],
		order_by="reading_time desc",
	):
		key = f"tempship:{r.shipment}"
		if key in out:
			continue
		received = frappe.db.get_value("IQ Shipment", r.shipment, "status") in ("Delivered", "Closed")
		if received:
			continue  # receipt already placed the cold-chain stock on QA hold
		out[key] = _finding(
			"Temperature Excursion", "Critical", f"Temperature excursion in transit: {r.temperature}°C", "IQ Shipment", r.shipment,
			f"Reading {r.name} at {r.reading_time} (logger {r.logger_id or '-'}) outside {r.min_allowed}..{r.max_allowed}°C. "
			"Cold-chain items will be placed on QA hold when this shipment is received.",
			t,
		)
	return out


OPEN_SHIPMENT = ("Planned", "Booked", "In Transit", "At Port", "Customs Clearance", "Released")


def privilege_findings(org, s, t):
	out = {}
	warn = s.privilege_warning_days or 30
	privs = {
		p.name: p
		for p in frappe.get_all(
			"IQ Privilege",
			filters={"organization": org, "review_status": ["!=", "Revoked"]},
			fields=["name", "title", "review_status", "effective_date", "expiry_date", "no_expiry_stated", "reference_no"],
		)
	}
	for p in privs.values():
		if p.review_status == "Confirmed" and p.expiry_date:
			days = (getdate(p.expiry_date) - t).days
			if days <= warn:
				out[f"privexp:{p.name}"] = _finding(
					"Privilege Expiry", "High" if days < 0 else ("High" if days <= 7 else "Medium"),
					f"{p.title}: {'expired' if days < 0 else f'expires in {days} days'}", "IQ Privilege", p.name,
					f"Authority reference {p.reference_no}; recorded expiry {p.expiry_date}. Plan renewal or confirm coverage for upcoming shipments.",
					add_days(getdate(p.expiry_date), -7) if days > 7 else t,
				)
	for sh in frappe.get_all(
		"IQ Shipment",
		filters={"organization": org, "privilege": ["is", "set"], "status": ["in", OPEN_SHIPMENT]},
		fields=["name", "shipment_title", "privilege", "planned_eta"],
	):
		p = privs.get(sh.privilege) or frappe.db.get_value(
			"IQ Privilege", sh.privilege, ["name", "title", "review_status", "effective_date", "expiry_date", "no_expiry_stated"], as_dict=True
		)
		problems = []
		if p.review_status != "Confirmed":
			problems.append(f"privilege is '{p.review_status}', not confirmed")
		eta = getdate(sh.planned_eta) if sh.planned_eta else None
		if eta and getdate(p.effective_date) > eta:
			problems.append(f"planned arrival {eta} is before the effective date {p.effective_date}")
		if eta and p.expiry_date and eta > getdate(p.expiry_date):
			problems.append(f"planned arrival {eta} is after the recorded expiry {p.expiry_date}")
		if problems:
			out[f"privconf:{sh.name}"] = _finding(
				"Privilege Conflict", "High", f"{sh.shipment_title}: possible privilege conflict", "IQ Shipment", sh.name,
				f"Linked to {p.title} ({sh.privilege}): " + "; ".join(problems) + ". This is a date/status check of your records, not a legal determination; confirm with your compliance team.",
				t,
			)
	return out


def lc_findings(org, s, t):
	out = {}
	warn = s.lc_warning_days or 14
	for lc in frappe.get_all(
		"IQ LC Case",
		filters={"organization": org, "status": ["not in", ["Payment Made", "Closed", "Cancelled"]]},
		fields=["name", "bank", "lc_number", "status", "latest_shipment_date", "expiry_date", "presentation_deadline", "next_deadline"],
	):
		doc = frappe.get_doc("IQ LC Case", lc.name)
		events = {m.event for m in doc.milestones}
		shipped = doc.shipped_on()
		checks = []
		if lc.latest_shipment_date and not shipped:
			checks.append(("shipment", "latest shipment date", getdate(lc.latest_shipment_date)))
		if lc.presentation_deadline and "Documents Presented" not in events:
			checks.append(("presentation", "document presentation deadline", getdate(lc.presentation_deadline)))
		if lc.expiry_date:
			checks.append(("expiry", "LC expiry", getdate(lc.expiry_date)))
		for key, label, when in checks:
			days = (when - t).days
			if days <= warn:
				out[f"lc:{key}:{lc.name}"] = _finding(
					"LC Deadline", "Critical" if days < 0 else ("High" if days <= 5 else "Medium"),
					f"LC {lc.lc_number or lc.name} ({lc.bank}): {label} {'passed' if days < 0 else f'in {days} days'}",
					"IQ LC Case", lc.name,
					f"{label.capitalize()} {when}; LC status '{lc.status}'. Confirm next steps and dates with the bank.",
					when if days >= 0 else t,
				)
				break  # one deadline exception per LC: the most urgent applicable
	return out


def diplomatic_findings(org, s, t):
	"""Personal-data exceptions: always restricted to diplomatic / HR roles."""
	out = {}
	warn = s.diplomatic_id_warning_days or 60
	for d in frappe.get_all(
		"IQ Diplomatic ID",
		filters={"organization": org},
		fields=["name", "employee_name", "id_type", "expiry_date", "renewal_status", "next_follow_up", "persona"],
	):
		if d.persona and frappe.db.get_value("IQ Diplomatic Persona", d.persona, "persona_status") == "Departed":
			continue
		days = (getdate(d.expiry_date) - t).days
		if days <= warn and d.renewal_status in ("Not Started", "Collected"):
			out[f"didrenew:{d.name}"] = _finding(
				"Diplomatic ID Renewal", "Critical" if days < 0 else ("High" if days <= 21 else "Medium"),
				f"{d.employee_name}: {d.id_type} {'expired' if days < 0 else f'expires in {days} days'}, renewal not started",
				"IQ Diplomatic ID", d.name, f"Expiry {d.expiry_date}. Start the renewal checklist.", t, restricted=1,
			)
		if d.renewal_status in ("Submitted", "Additional Information Requested") and d.next_follow_up and getdate(d.next_follow_up) < t:
			out[f"didfollow:{d.name}"] = _finding(
				"Renewal Follow-up", "Medium", f"{d.employee_name}: renewal follow-up overdue", "IQ Diplomatic ID", d.name,
				f"Follow-up was due {d.next_follow_up}; status '{d.renewal_status}'.", t, restricted=1,
			)
	personas = {
		p.name: p
		for p in frappe.get_all(
			"IQ Diplomatic Persona",
			filters={"organization": org, "persona_status": ["!=", "Departed"]},
			fields=["name", "full_name", "passport_expiry", "assignment_end_date", "active_ids", "active_privileges"],
		)
	}
	for p in personas.values():
		if p.passport_expiry:
			days = (getdate(p.passport_expiry) - t).days
			if days <= 180:
				out[f"passport:{p.name}"] = _finding(
					"Passport Expiry", "High" if days <= 60 else "Medium",
					f"{p.full_name}: passport {'expired' if days < 0 else f'expires in {days} days'}", "IQ Diplomatic Persona", p.name,
					f"Passport expiry {p.passport_expiry}. ID and privilege renewals usually depend on a valid passport.", t, restricted=1,
				)
		if p.assignment_end_date:
			days = (getdate(p.assignment_end_date) - t).days
			if days <= 60 and (p.active_ids or p.active_privileges):
				out[f"depart:{p.name}"] = _finding(
					"Departure Close-out", "High" if days <= 14 else "Medium",
					f"{p.full_name}: departure in {days} days with {p.active_ids or 0} ID(s) / {p.active_privileges or 0} privilege(s) open",
					"IQ Diplomatic Persona", p.name,
					f"Assignment ends {p.assignment_end_date}. Plan ID return and the close-out of personal privileges (e.g. vehicle and plate) under the applicable procedure.",
					add_days(getdate(p.assignment_end_date), -14), restricted=1,
				)
	for pp in frappe.get_all(
		"IQ Personal Privilege",
		filters={"organization": org, "review_status": "Confirmed"},
		fields=["name", "persona", "full_name", "privilege_type", "expiry_date", "quota_value", "quota_used_pct", "quota_unit", "used_value"],
	):
		if pp.persona not in personas:
			continue
		if pp.expiry_date:
			days = (getdate(pp.expiry_date) - t).days
			if days <= warn:
				out[f"ppexp:{pp.name}"] = _finding(
					"Personal Privilege Expiry", "High" if days <= 14 else "Medium",
					f"{pp.full_name}: {pp.privilege_type} {'expired' if days < 0 else f'expires in {days} days'}",
					"IQ Personal Privilege", pp.name, f"Recorded expiry {pp.expiry_date}.", t, restricted=1,
				)
		if pp.quota_value and (pp.quota_used_pct or 0) >= 90:
			out[f"ppquota:{pp.name}"] = _finding(
				"Privilege Quota", "Medium", f"{pp.full_name}: {pp.privilege_type} {pp.quota_used_pct}% used",
				"IQ Personal Privilege", pp.name,
				f"Used {pp.used_value} of {pp.quota_value} {pp.quota_unit or ''}.", t, restricted=1,
			)
	return out


def stock_findings(org, s, t):
	out = {}
	balances = frappe.get_all(
		"IQ Stock Balance",
		filters={"organization": org},
		fields=["name", "item", "item_name", "warehouse", "batch_no", "quantity", "avg_monthly_consumption", "expiry_date"],
	)
	# stock-out is judged per item and warehouse: an emptied batch is normal under FEFO
	on_hand = {}
	for b in balances:
		key = (b.item, b.warehouse)
		on_hand[key] = on_hand.get(key, 0) + (b.quantity or 0)
	low_threshold = s.low_stock_cover_months or 1
	warn_days = s.expiry_warning_days or 90
	for h in frappe.get_all(
		"IQ Stock Balance",
		filters={"organization": org, "qa_status": "Quarantined", "quantity": [">", 0]},
		fields=["name", "item", "item_name", "warehouse", "batch_no", "quantity", "qa_hold_reason"],
	):
		out[f"qahold:{h.name}"] = _finding(
			"QA Hold", "High", f"{h.item_name or h.item} @ {h.warehouse}" + (f" (batch {h.batch_no})" if h.batch_no else "") + ": awaiting QA decision",
			"IQ Stock Balance", h.name,
			f"{h.quantity} units quarantined. {h.qa_hold_reason or ''} Stock cannot be issued until a QA Officer records a decision.",
			add_days(t, 2),
		)
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
			key = (b.item, b.warehouse)
			if b.avg_monthly_consumption and on_hand[key] <= 0 and f"stockout:{key[0]}:{key[1]}" not in out:
				out[f"stockout:{key[0]}:{key[1]}"] = _finding(
					"Stock Out", "High", f"{b.item_name or b.item} @ {b.warehouse}: out of stock", "IQ Stock Balance", b.name,
					f"No stock of this item left in the warehouse (all batches at 0); average monthly consumption {b.avg_monthly_consumption}.", t,
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
	# a user dismissal means "acknowledged": do not raise the same condition again
	dismissed = set(
		frappe.get_all(
			"IQ Exception",
			filters={"organization": org, "auto_generated": 1, "status": "Dismissed", "fingerprint": ["in", list(findings) or [""]]},
			pluck="fingerprint",
		)
	)
	created = updated = resolved = 0
	for fp, f in findings.items():
		if fp in dismissed and fp not in by_fp:
			continue
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

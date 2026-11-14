"""Stock posting: the only code path that changes stock quantities once a
warehouse uses movements. Every change writes an IQ Stock Ledger Entry.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from supplychain_iq.entitlements import has_module
from supplychain_iq.intelligence import calculations as calc

HOLD_STATUSES = ("Quarantined", "Rejected")
WAREHOUSE_MODULE = "Warehouse & Batch Control"


def find_balance(org, item, warehouse, batch_no):
	filters = {"organization": org, "item": item, "warehouse": warehouse}
	filters["batch_no"] = batch_no if batch_no else ["is", "not set"]
	return frappe.db.get_value("IQ Stock Balance", filters)


def issuable_batches(org, item, warehouse, on_date) -> list[dict]:
	"""Batches that may be issued: released by QA, not expired, quantity > 0."""
	rows = frappe.get_all(
		"IQ Stock Balance",
		filters={"organization": org, "item": item, "warehouse": warehouse, "qa_status": "Released", "quantity": [">", 0]},
		fields=["name", "batch_no", "quantity", "expiry_date"],
	)
	on_date = getdate(on_date)
	return [
		{"batch_no": r.batch_no, "quantity": flt(r.quantity), "expiry_date": getdate(r.expiry_date) if r.expiry_date else None}
		for r in rows
		if not r.expiry_date or getdate(r.expiry_date) >= on_date
	]


def allocate(org, item, warehouse, quantity, on_date) -> list[dict]:
	try:
		return calc.fefo_allocate(issuable_batches(org, item, warehouse, on_date), flt(quantity))
	except calc.InsufficientStock as e:
		item_label = frappe.db.get_value("IQ Item", item, "item_code") or item
		wh_label = frappe.db.get_value("IQ Warehouse", warehouse, "warehouse_name") or warehouse
		frappe.throw(
			_("Not enough issuable stock of {0} in {1}: {2}. Expired and QA-held batches cannot be issued.").format(
				item_label, wh_label, str(e)
			),
			title=_("Insufficient stock"),
		)


def post(
	org, item, warehouse, batch_no, delta, posting_date, entry_type, ref_doctype, ref_name,
	expiry_date=None, qa_status=None, qa_hold_reason=None,
):
	"""Apply a quantity change to a stock balance and record it in the ledger."""
	delta = flt(delta, 6)
	name = find_balance(org, item, warehouse, batch_no)
	if name:
		bal = frappe.get_doc("IQ Stock Balance", name)
	else:
		if delta < 0:
			frappe.throw(_("No stock of batch {0} in this warehouse.").format(batch_no or _("(no batch)")))
		bal = frappe.get_doc({
			"doctype": "IQ Stock Balance", "organization": org, "item": item, "warehouse": warehouse,
			"batch_no": batch_no, "quantity": 0, "expiry_date": expiry_date,
		})
	new_qty = flt(flt(bal.quantity) + delta, 6)
	if new_qty < 0:
		frappe.throw(
			_("Stock of batch {0} would become negative ({1}).").format(batch_no or _("(no batch)"), new_qty),
			title=_("Insufficient stock"),
		)
	bal.quantity = new_qty
	if expiry_date and not bal.expiry_date:
		bal.expiry_date = expiry_date
	if qa_status in HOLD_STATUSES and (bal.qa_status or "Released") == "Released":
		bal.qa_status = qa_status
		bal.qa_hold_reason = qa_hold_reason
		bal.flags.iq_qa_change = True
	bal.flags.iq_from_ledger = True
	bal.flags.ignore_permissions = True
	bal.save() if not bal.is_new() else bal.insert()

	write_ledger(org, bal, delta, posting_date, entry_type, ref_doctype, ref_name)
	return bal


def write_ledger(org, bal, delta, posting_date, entry_type, ref_doctype=None, ref_name=None, is_cancelled=0):
	if not has_module(org, WAREHOUSE_MODULE):
		return None
	sle = frappe.get_doc({
		"doctype": "IQ Stock Ledger Entry", "organization": org, "posting_date": posting_date,
		"entry_type": entry_type, "item": bal.item, "warehouse": bal.warehouse, "batch_no": bal.batch_no,
		"qty_change": delta, "balance_after": bal.quantity, "stock_balance": bal.name,
		"reference_doctype": ref_doctype, "reference_name": ref_name, "is_cancelled": is_cancelled,
	})
	sle.flags.ignore_permissions = True
	sle.insert()
	return sle


def has_ledger(stock_balance: str) -> bool:
	return bool(frappe.db.exists("IQ Stock Ledger Entry", {"stock_balance": stock_balance}))


def reverse(ref_doctype, ref_name, posting_date):
	"""Reverse every ledger entry of a document (used on cancel)."""
	entries = frappe.get_all(
		"IQ Stock Ledger Entry",
		filters={"reference_doctype": ref_doctype, "reference_name": ref_name, "is_cancelled": 0},
		fields=["name", "organization", "item", "warehouse", "batch_no", "qty_change", "entry_type"],
		order_by="creation desc",
	)
	for e in entries:
		post(
			e.organization, e.item, e.warehouse, e.batch_no, -flt(e.qty_change), posting_date,
			f"Cancel {e.entry_type}", ref_doctype, ref_name,
		)
	frappe.db.set_value(
		"IQ Stock Ledger Entry", {"reference_doctype": ref_doctype, "reference_name": ref_name}, "is_cancelled", 1
	)


def place_on_hold(balance_names: list[str], reason: str) -> int:
	"""Quarantine released stock lines. Never releases anything."""
	count = 0
	for name in balance_names:
		bal = frappe.get_doc("IQ Stock Balance", name)
		if bal.qa_status != "Released":
			continue
		bal.qa_status = "Quarantined"
		bal.qa_hold_reason = reason
		bal.flags.iq_qa_change = True
		bal.flags.ignore_permissions = True
		bal.save()
		count += 1
	return count

# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from supplychain_iq.intelligence import stock

NEEDS_FROM = ("Issue", "Transfer", "Adjustment Out")
NEEDS_TO = ("Receipt", "Transfer", "Adjustment In", "Customer Return")
RETURN_HOLD = "Returned goods: inspect before reuse (customer return)."
ALLOCATED = ("Issue", "Transfer")  # FEFO, issuable stock only


class IQStockMovement(Document):
	def validate(self):
		self.validate_warehouses()
		for row in self.items:
			if flt(row.quantity) <= 0:
				frappe.throw(_("Row {0}: quantity must be greater than zero.").format(row.idx))
			row.batch_no = (row.batch_no or "").strip() or None
		if self.movement_type in ALLOCATED:
			self.allocate_batches()
		elif self.movement_type == "Adjustment Out":
			self.check_adjustment_out()
		self.total_quantity = sum(flt(r.quantity) for r in self.items)

	def validate_warehouses(self):
		t = self.movement_type
		if t in NEEDS_FROM and not self.from_warehouse:
			frappe.throw(_("From Warehouse is required for {0}.").format(t))
		if t in NEEDS_TO and not self.to_warehouse:
			frappe.throw(_("To Warehouse is required for {0}.").format(t))
		if t not in NEEDS_FROM:
			self.from_warehouse = None
		if t not in NEEDS_TO:
			self.to_warehouse = None
		if t == "Transfer" and self.from_warehouse == self.to_warehouse:
			frappe.throw(_("Transfer needs two different warehouses."))
		if (t.startswith("Adjustment") or t == "Customer Return") and not (self.reason or "").strip():
			frappe.throw(_("A reason is required for adjustments and returns."))
		if t == "Customer Return" and not self.delivery:
			frappe.throw(_("A customer return must reference the delivery it comes from."))
		if self.shipment and t != "Receipt":
			self.shipment = None
		if self.shipment and frappe.db.get_value("IQ Shipment", self.shipment, "status") == "Cancelled":
			frappe.throw(_("Cannot receive against a cancelled shipment."))

	def allocate_batches(self):
		"""Expand rows without a batch into FEFO batch rows; check rows with a batch."""
		rows, notes = [], []
		for row in self.items:
			if row.batch_no:
				available = {b["batch_no"]: b for b in stock.issuable_batches(self.organization, row.item, self.from_warehouse, self.posting_date)}
				b = available.get(row.batch_no)
				if not b:
					frappe.throw(_("Row {0}: batch {1} is not issuable (missing, expired or on QA hold).").format(row.idx, row.batch_no))
				if flt(row.quantity) > b["quantity"]:
					frappe.throw(_("Row {0}: only {1} available in batch {2}.").format(row.idx, b["quantity"], row.batch_no))
				row.expiry_date = b["expiry_date"]
				rows.append(row.as_dict())
				continue
			allocation = stock.allocate(self.organization, row.item, self.from_warehouse, row.quantity, self.posting_date)
			for a in allocation:
				rows.append({"item": row.item, "batch_no": a["batch_no"], "expiry_date": a["expiry_date"], "quantity": a["quantity"]})
			code = frappe.db.get_value("IQ Item", row.item, "item_code")
			notes.append(f"{code}: " + ", ".join(f"{a['batch_no'] or '(no batch)'} x {a['quantity']:g}" for a in allocation))
		if notes:
			self.set("items", [])
			for r in rows:
				self.append("items", {k: r.get(k) for k in ("item", "batch_no", "expiry_date", "quantity")})
			self.allocation_note = "Allocated by FEFO (first expiry, first out):\n" + "\n".join(notes)

	def check_adjustment_out(self):
		for row in self.items:
			name = stock.find_balance(self.organization, row.item, self.from_warehouse, row.batch_no)
			if not name:
				frappe.throw(_("Row {0}: no stock line for this item/batch in the warehouse.").format(row.idx))
			if flt(row.quantity) > flt(frappe.db.get_value("IQ Stock Balance", name, "quantity")):
				frappe.throw(_("Row {0}: quantity exceeds stock on hand.").format(row.idx))

	def before_submit(self):
		if self.movement_type in ALLOCATED:
			self.allocate_batches()  # stock may have changed since the draft was saved

	def on_submit(self):
		t, org, date = self.movement_type, self.organization, self.posting_date
		hold = self.receipt_hold_reason() if t == "Receipt" else None
		if t == "Customer Return":
			hold = RETURN_HOLD
		for row in self.items:
			src_doc = None
			if t in NEEDS_FROM:
				src = stock.find_balance(org, row.item, self.from_warehouse, row.batch_no)
				src_doc = frappe.db.get_value("IQ Stock Balance", src, ["qa_status", "qa_hold_reason", "expiry_date"], as_dict=True) if src else None
				stock.post(org, row.item, self.from_warehouse, row.batch_no, -flt(row.quantity), date, t, self.doctype, self.name)
			if t in NEEDS_TO:
				expiry = row.expiry_date or (src_doc.expiry_date if t == "Transfer" and src_doc else None)
				qa = (src_doc.qa_status, src_doc.qa_hold_reason) if t == "Transfer" and src_doc else (None, None)
				if hold and (t == "Customer Return" or self.is_cold_chain(row.item)):
					qa = ("Quarantined", hold)
				stock.post(
					org, row.item, self.to_warehouse, row.batch_no, flt(row.quantity), date, t, self.doctype, self.name,
					expiry_date=expiry, qa_status=qa[0], qa_hold_reason=qa[1],
				)
		if self.shipment:
			update_shipment_receipts(self.shipment, receipt=self)
		if t == "Customer Return":
			update_delivery_returns(self.delivery)

	def on_cancel(self):
		stock.reverse(self.doctype, self.name, self.posting_date)
		if self.shipment:
			update_shipment_receipts(self.shipment)
		if self.movement_type == "Customer Return":
			update_delivery_returns(self.delivery)

	def receipt_hold_reason(self):
		if not self.shipment:
			return None
		exc = frappe.get_all(
			"IQ Temperature Log",
			filters={"shipment": self.shipment, "is_excursion": 1},
			fields=["name", "temperature", "reading_time"],
			limit=1,
		)
		if exc:
			e = exc[0]
			return f"Received from shipment {self.shipment} with a temperature excursion ({e.temperature}°C at {str(e.reading_time)[:16]}, {e.name}). QA review required."
		return None

	@staticmethod
	def is_cold_chain(item):
		return bool(frappe.db.get_value("IQ Item", item, "requires_cold_chain"))


def received_by_line(shipment: str) -> dict:
	rows = frappe.db.sql(
		"""select i.item, coalesce(i.batch_no, '') as batch_no, sum(i.quantity) as qty from `tabIQ Stock Movement Item` i
		join `tabIQ Stock Movement` m on m.name = i.parent
		where m.shipment = %s and m.docstatus = 1 and m.movement_type = 'Receipt' group by i.item, coalesce(i.batch_no, '')""",
		(shipment,),
		as_dict=True,
	)
	return {(r.item, r.batch_no): flt(r.qty) for r in rows}


def update_delivery_returns(delivery: str):
	"""Roll submitted returns onto the delivery; close it once every unit is delivered or returned."""
	returned = frappe.db.sql(
		"""select i.item, sum(i.quantity) from `tabIQ Stock Movement Item` i
		join `tabIQ Stock Movement` m on m.name = i.parent
		where m.delivery = %s and m.docstatus = 1 and m.movement_type = 'Customer Return' group by i.item""",
		(delivery,),
	)
	by_item = {item: flt(q) for item, q in returned}
	doc = frappe.get_doc("IQ Delivery", delivery)
	for row in doc.items:
		row.returned_qty = by_item.pop(row.item, 0)
	accounted = all(flt(r.delivered_qty) + flt(r.returned_qty) >= flt(r.quantity) for r in doc.items)
	if doc.status == "Partially Delivered" and accounted:
		doc._set_status("Closed")
	elif doc.status == "Closed" and not accounted:
		doc._set_status("Partially Delivered")
	doc.flags.ignore_permissions = True
	doc.flags.iq_status_change = True
	doc.save()


def update_shipment_receipts(shipment: str, receipt=None):
	"""Roll submitted receipts up onto the shipment and mark it received."""
	received = frappe.db.sql(
		"""select coalesce(sum(i.quantity), 0) from `tabIQ Stock Movement Item` i
		join `tabIQ Stock Movement` m on m.name = i.parent
		where m.shipment = %s and m.docstatus = 1 and m.movement_type = 'Receipt'""",
		(shipment,),
	)[0][0]
	last = frappe.db.get_value(
		"IQ Stock Movement", {"shipment": shipment, "docstatus": 1, "movement_type": "Receipt"}, "name", order_by="posting_date desc"
	)
	frappe.db.set_value("IQ Shipment", shipment, {"received_quantity": flt(received), "last_receipt": last}, update_modified=False)
	by_line = received_by_line(shipment)
	for line in frappe.get_all("IQ Shipment Item", filters={"parent": shipment, "parenttype": "IQ Shipment"}, fields=["name", "item", "batch_no"], order_by="idx"):
		qty = by_line.pop((line.item, line.batch_no or ""), 0) if line.item else 0
		frappe.db.set_value("IQ Shipment Item", line.name, "received_qty", qty, update_modified=False)
	if receipt:
		doc = frappe.get_doc("IQ Shipment", shipment)
		milestone = next((m for m in doc.milestones if m.milestone == "Goods Received"), None)
		if not milestone:
			milestone = doc.append("milestones", {"milestone": "Goods Received", "planned_date": receipt.posting_date})
		if not milestone.actual_date:
			milestone.actual_date = receipt.posting_date
		if doc.status not in ("Delivered", "Closed"):
			doc.status = "Delivered"
			if not doc.actual_eta:
				doc.actual_eta = receipt.posting_date
		doc.flags.ignore_permissions = True
		doc.save()

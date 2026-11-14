# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime, today

SERVER_FIELDS = ("status", "dispatch_movement", "dispatched_on", "on_time")


class IQDelivery(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if not self.flags.iq_status_change:
			for f in SERVER_FIELDS:
				self.set(f, before.get(f) if before else ("Draft" if f == "status" else None))
		for row in self.items:
			if flt(row.quantity) <= 0:
				frappe.throw(_("Row {0}: quantity must be greater than zero.").format(row.idx))
			if flt(row.delivered_qty) < 0 or flt(row.delivered_qty) > flt(row.quantity):
				frappe.throw(_("Row {0}: delivered quantity must be between 0 and the dispatched quantity.").format(row.idx))
		if before and before.status != "Draft" and not self.flags.iq_status_change:
			old = [(r.item, flt(r.quantity)) for r in before.items]
			new = [(r.item, flt(r.quantity)) for r in self.items]
			if old != new:
				frappe.throw(_("Items cannot be changed after dispatch."))
			if self.from_warehouse != before.from_warehouse:
				frappe.throw(_("The warehouse cannot be changed after dispatch."))

	def on_update(self):
		self.flags.iq_status_change = False  # single-use

	def _set_status(self, status):
		self.status = status
		self.flags.iq_status_change = True

	@frappe.whitelist()
	def dispatch(self):
		"""Issue the goods from the warehouse (FEFO) and mark the delivery dispatched."""
		self.check_permission("write")
		if self.status != "Draft":
			frappe.throw(_("Only draft deliveries can be dispatched."))
		mv = frappe.get_doc({
			"doctype": "IQ Stock Movement", "organization": self.organization, "movement_type": "Issue",
			"posting_date": today(), "from_warehouse": self.from_warehouse, "delivery": self.name,
			"reason": f"Dispatch for delivery {self.name} to {self.recipient}",
			"items": [{"item": r.item, "quantity": r.quantity} for r in self.items],
		})
		mv.insert()
		mv.submit()
		batches = {}
		for r in mv.items:
			batches.setdefault(r.item, []).append(f"{r.batch_no or '(no batch)'} x {flt(r.quantity):g}")
		for row in self.items:
			row.batches = ", ".join(batches.get(row.item, []))
		self.dispatch_movement = mv.name
		self.dispatched_on = now_datetime()
		self._set_status("Dispatched")
		self.save()
		return mv.name

	@frappe.whitelist()
	def confirm_delivery(self):
		"""Record proof of delivery. Delivered quantities left at 0 on every row mean 'all delivered'."""
		self.check_permission("write")
		if self.status != "Dispatched":
			frappe.throw(_("Only dispatched deliveries can be confirmed."))
		missing = [label for label, v in ((_("Delivered On"), self.delivered_on), (_("Received By"), self.received_by), (_("Proof of Delivery"), self.proof_of_delivery)) if not v]
		if missing:
			frappe.throw(_("Before confirming, enter: {0}.").format(", ".join(missing)))
		if getdate(self.delivered_on) > getdate(today()):
			frappe.throw(_("Delivered On cannot be in the future."))
		if all(not flt(r.delivered_qty) for r in self.items):
			for r in self.items:
				r.delivered_qty = r.quantity
		short = any(flt(r.delivered_qty) < flt(r.quantity) for r in self.items)
		self.on_time = 1 if getdate(self.delivered_on) <= getdate(self.planned_delivery_date) else 0
		self._set_status("Partially Delivered" if short else "Delivered")
		self.save()
		return self.status

	@frappe.whitelist()
	def cancel_delivery(self):
		"""Cancel a draft, or a dispatched delivery whose goods came back (stock is returned)."""
		self.check_permission("write")
		if self.status not in ("Draft", "Dispatched"):
			frappe.throw(_("Delivered deliveries cannot be cancelled; record a return with an Adjustment In."))
		if self.dispatch_movement:
			mv = frappe.get_doc("IQ Stock Movement", self.dispatch_movement)
			if mv.docstatus == 1:
				mv.cancel()
		self._set_status("Cancelled")
		self.save()

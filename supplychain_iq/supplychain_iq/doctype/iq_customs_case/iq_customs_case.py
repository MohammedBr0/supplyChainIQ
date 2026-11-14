# Copyright (c) 2026, SupplyChain IQ
# See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

from supplychain_iq.entitlements import has_module
from supplychain_iq.intelligence.costs import normalize_currency

DATE_ORDER = ("lodged_date", "assessed_date", "inspection_date", "payment_date", "release_date")


class IQCustomsCase(Document):
	def validate(self):
		self.currency = normalize_currency(self.currency) or "ETB"
		if self.procedure == "Duty-Free (Privilege)" and not self.privilege:
			self.privilege = frappe.db.get_value("IQ Shipment", self.shipment, "privilege")
		if not self.declarant:
			self.declarant = frappe.db.get_value("IQ Shipment", self.shipment, "transitor")
		if not self.is_cancelled and frappe.db.exists(
			"IQ Customs Case", {"shipment": self.shipment, "is_cancelled": 0, "name": ["!=", self.name or ""]}
		):
			frappe.throw(_("Shipment {0} already has an open customs case.").format(self.shipment))
		t = getdate(today())
		for f in DATE_ORDER:
			if self.get(f) and getdate(self.get(f)) > t:
				frappe.throw(_("{0} cannot be in the future.").format(self.meta.get_label(f)))
		if self.lodged_date:
			for f in DATE_ORDER[1:]:
				if self.get(f) and getdate(self.get(f)) < getdate(self.lodged_date):
					frappe.throw(_("{0} cannot be before the lodgement date.").format(self.meta.get_label(f)))
		elif any(self.get(f) for f in DATE_ORDER[1:]):
			frappe.throw(_("Enter the lodgement date first."))
		for row in self.taxes:
			if flt(row.assessed_amount) < 0 or flt(row.paid_amount) < 0:
				frappe.throw(_("Tax line {0}: amounts cannot be negative.").format(row.idx))
			if row.exempted and not (row.exemption_basis or "").strip():
				row.exemption_basis = self.privilege or ""
				if not row.exemption_basis:
					frappe.throw(_("Tax line {0}: give the basis of the exemption (privilege or decision).").format(row.idx))
		self.total_assessed = round(sum(flt(r.assessed_amount) for r in self.taxes), 2)
		self.total_exempted = round(sum(flt(r.assessed_amount) for r in self.taxes if r.exempted), 2)
		self.total_payable = round(self.total_assessed - self.total_exempted, 2)
		self.total_paid = round(sum(flt(r.paid_amount) for r in self.taxes), 2)
		if self.release_date and self.total_paid < self.total_payable:
			frappe.msgprint(_("Released with {0} {1} of assessed duties not recorded as paid.").format(
				round(self.total_payable - self.total_paid, 2), self.currency), indicator="orange", alert=True)
		self.status = self.derive_status()
		end = getdate(self.release_date) if self.release_date else t
		self.clearance_days = (end - getdate(self.lodged_date)).days if self.lodged_date else None

	def derive_status(self):
		if self.is_cancelled:
			return "Cancelled"
		if self.release_date:
			return "Released"
		if self.payment_date and self.total_paid >= self.total_payable:
			return "Duties Paid"
		if self.inspection_date or self.lane in ("Yellow", "Red"):
			return "Inspection"
		if self.assessed_date:
			return "Assessed"
		if self.lodged_date:
			return "Lodged"
		return "Draft"

	def on_update(self):
		self.sync_shipment()
		self.sync_cost_line()

	def on_trash(self):
		if frappe.db.get_value("IQ Shipment", self.shipment, "customs_case") == self.name:
			frappe.db.set_value("IQ Shipment", self.shipment, "customs_case", None, update_modified=False)
		if self.cost_line and frappe.db.exists("IQ Cost Line", self.cost_line):
			line, self.cost_line = self.cost_line, None
			frappe.db.set_value("IQ Customs Case", self.name, "cost_line", None, update_modified=False)
			frappe.delete_doc("IQ Cost Line", line, ignore_permissions=True)

	def sync_shipment(self):
		sh = frappe.get_doc("IQ Shipment", self.shipment)
		changed = False
		if self.is_cancelled:
			if sh.customs_case == self.name:
				sh.customs_case, changed = None, True
		else:
			if sh.customs_case != self.name:
				sh.customs_case, changed = self.name, True
			for milestone, date in (("Customs Declaration Lodged", self.lodged_date), ("Customs Released", self.release_date)):
				if not date:
					continue
				row = next((m for m in sh.milestones if m.milestone == milestone), None) or sh.append("milestones", {"milestone": milestone})
				if str(row.actual_date or "") != str(date):
					row.actual_date, changed = date, True
			if self.release_date and sh.status in ("In Transit", "At Port", "Customs Clearance"):
				sh.status, changed = "Released", True
			elif self.lodged_date and not self.release_date and sh.status in ("In Transit", "At Port"):
				sh.status, changed = "Customs Clearance", True
		if changed:
			sh.flags.ignore_permissions = True
			sh.save()

	def sync_cost_line(self):
		"""Paid duties become an actual 'Duties & Taxes' cost line on the shipment."""
		if not has_module(self.organization, "Cost Intelligence"):
			return
		if self.is_cancelled or not self.total_paid:
			if self.cost_line and frappe.db.exists("IQ Cost Line", self.cost_line):
				line = self.cost_line
				self.db_set("cost_line", None, update_modified=False)
				frappe.delete_doc("IQ Cost Line", line, ignore_permissions=True)
			return
		refs = ", ".join(filter(None, (r.payment_reference for r in self.taxes)))
		values = {
			"organization": self.organization, "shipment": self.shipment, "cost_category": "Duties & Taxes",
			"cost_status": "Actual", "currency": self.currency, "amount": self.total_paid,
			"cost_date": self.payment_date or self.assessed_date or today(), "vendor": self.customs_office,
			"invoice_reference": (refs or self.declaration_number or "")[:140],
			"description": f"Duties and taxes paid - customs case {self.name}",
		}
		line = frappe.get_doc("IQ Cost Line", self.cost_line) if self.cost_line and frappe.db.exists("IQ Cost Line", self.cost_line) else frappe.new_doc("IQ Cost Line")
		line.update(values)
		line.flags.ignore_permissions = True
		line.save()
		if self.cost_line != line.name:
			self.db_set("cost_line", line.name, update_modified=False)

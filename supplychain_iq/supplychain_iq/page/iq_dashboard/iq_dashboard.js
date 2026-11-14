// SupplyChain IQ unified dashboard
frappe.pages["iq-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("SupplyChain IQ"), single_column: true });
	wrapper.iq = new IQDashboard(page);
};
frappe.pages["iq-dashboard"].on_page_show = function (wrapper) {
	wrapper.iq && wrapper.iq.refresh();
};

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const fmtDate = (d) => (d ? frappe.datetime.str_to_user(d) : "-");
const route = (dt, name) => `/desk/${frappe.router.slug(dt)}/${encodeURIComponent(name)}`;
const listUrl = (dt, query) => `/desk/${frappe.router.slug(dt)}` + (query ? `?${query}` : "");
const STATUS_COLORS = {
	OK: "#2f855a", Delivered: "#2f855a", Low: "#d69e2e", Medium: "#d69e2e", "Expiring Soon": "#dd6b20", High: "#dd6b20",
	Expired: "#c53030", "Out of Stock": "#9b2c2c", Critical: "#c53030", "Customs Clearance": "#805ad5", "QA Hold": "#6b46c1",
	Receipt: "#2f855a", Issue: "#2b6cb0", Transfer: "#319795", "Adjustment In": "#b7791f", "Adjustment Out": "#c53030",
};
const COLORS = ["#2b6cb0", "#2f855a", "#b7791f", "#c53030", "#6b46c1", "#319795", "#718096", "#d53f8c", "#dd6b20"];

class IQDashboard {
	constructor(page) {
		this.page = page;
		this.org = null;
		this.$body = $('<div class="iq-dash"></div>').appendTo(page.main);
		page.set_primary_action(__("Run Checks"), () => this.run_checks(), "refresh");
		page.set_secondary_action(__("Refresh"), () => this.refresh());
		this.setup_menus();
		frappe.call("supplychain_iq.api.dashboard.get_organizations").then((r) => {
			const orgs = r.message || [];
			if (orgs.length > 1) {
				this.org_field = page.add_field({
					fieldtype: "Select", fieldname: "organization", label: __("Organization"),
					options: orgs.map((o) => o.name), default: orgs[0].name,
					change: () => { this.org = this.org_field.get_value(); this.refresh(); },
				});
				this.org = orgs[0].name;
			}
			this.refresh();
		});
	}

	setup_menus() {
		const page = this.page;
		const add = __("Add");
		const new_import = (type) => frappe.new_doc("IQ Import Batch", { import_type: type });
		page.add_inner_button(__("Shipment"), () => frappe.new_doc("IQ Shipment"), add);
		page.add_inner_button(__("Purchase Order"), () => frappe.new_doc("IQ Purchase Order"), add);
		page.add_inner_button(__("Stock Balance"), () => frappe.new_doc("IQ Stock Balance"), add);
		page.add_inner_button(__("Cost Line"), () => frappe.new_doc("IQ Cost Line"), add);
		page.add_inner_button(__("Stock Receipt"), () => frappe.new_doc("IQ Stock Movement", { movement_type: "Receipt" }), add);
		page.add_inner_button(__("Stock Issue / Transfer"), () => frappe.new_doc("IQ Stock Movement", { movement_type: "Issue" }), add);
		page.add_inner_button(__("Delivery"), () => frappe.new_doc("IQ Delivery"), add);
		page.add_inner_button(__("Temperature Reading"), () => frappe.new_doc("IQ Temperature Log"), add);
		page.add_inner_button(__("Privilege / Permit"), () => frappe.new_doc("IQ Privilege"), add);
		page.add_inner_button(__("LC Case"), () => frappe.new_doc("IQ LC Case"), add);
		page.add_inner_button(__("Import Temperature File"), () => new_import("Temperature Readings"), add);
		page.add_inner_button(__("Exchange Rate"), () => frappe.new_doc("IQ Exchange Rate"), add);
		page.add_inner_button(__("Import Stock File"), () => new_import("Existing Stock"), add);
		page.add_inner_button(__("Import Shipments File"), () => new_import("Inbound Shipments"), add);

		const go = __("View");
		page.add_inner_button(__("Open Exceptions"), () => frappe.set_route("List", "IQ Exception", { status: "Open" }), go);
		page.add_inner_button(__("Delayed Shipments"), () => frappe.set_route("List", "IQ Shipment", { is_delayed: 1 }), go);
		page.add_inner_button(__("Stock Alerts"), () => frappe.set_route("List", "IQ Stock Balance", { stock_status: ["!=", "OK"] }), go);
		page.add_inner_button(__("Import History"), () => frappe.set_route("List", "IQ Import Batch"), go);
		page.add_inner_button(__("Landed Cost Report"), () => frappe.set_route("query-report", "IQ Landed Cost"), go);
		page.add_inner_button(__("Supplier Performance"), () => frappe.set_route("query-report", "IQ Supplier Performance"), go);
		page.add_inner_button(__("Stock Summary"), () => frappe.set_route("query-report", "IQ Stock Summary"), go);
		page.add_inner_button(__("Stock on QA Hold"), () => frappe.set_route("List", "IQ Stock Balance", { qa_status: "Quarantined" }), go);
		page.add_inner_button(__("Open Deliveries"), () => frappe.set_route("List", "IQ Delivery", { status: ["in", ["Draft", "Dispatched"]] }), go);

		page.add_menu_item(__("Download: existing stock template"), () => window.open("/assets/supplychain_iq/templates/existing_stock_template.csv"));
		page.add_menu_item(__("Download: inbound shipments template"), () => window.open("/assets/supplychain_iq/templates/inbound_shipments_template.csv"));
		page.add_menu_item(__("Organization settings"), () => frappe.set_route("List", "IQ Organization"));
		page.add_menu_item(__("Auto-refresh every 5 minutes"), () => this.toggle_auto_refresh(), true);
	}

	toggle_auto_refresh() {
		if (this.timer) {
			clearInterval(this.timer);
			this.timer = null;
			frappe.show_alert(__("Auto-refresh off"));
		} else {
			this.timer = setInterval(() => document.visibilityState === "visible" && this.refresh(), 5 * 60 * 1000);
			frappe.show_alert(__("Auto-refresh on"));
		}
	}

	refresh() {
		frappe.call("supplychain_iq.api.dashboard.get_dashboard_data", { organization: this.org }).then((r) => this.render(r.message));
	}

	run_checks() {
		frappe.call({ method: "supplychain_iq.api.dashboard.run_checks", args: { organization: this.org }, freeze: true })
			.then((r) => {
				const m = r.message || {};
				frappe.show_alert({ message: m.skipped ? m.skipped : __("Checks done: {0} new, {1} resolved, {2} open", [m.created, m.resolved, m.open]), indicator: "green" });
				this.refresh();
			});
	}

	tile(value, label, cls, href) {
		return `<div class="iq-tile ${cls || ""}" data-href="${href || ""}"><div class="v">${value == null ? "-" : esc(value)}</div><div class="l">${esc(label)}</div></div>`;
	}

	section(title, sub) {
		return `<div class="iq-section"><h4>${esc(title)}</h4><span>${esc(sub || "")}</span></div>`;
	}

	bar(counts) {
		const entries = Object.entries(counts || {});
		const total = entries.reduce((a, [, v]) => a + v, 0);
		if (!total) return '<div class="empty">' + __("No records") + "</div>";
		const color = (k, i) => STATUS_COLORS[k] || COLORS[i % COLORS.length];
		const segs = entries.map(([k, v], i) => `<div title="${esc(k)}: ${v}" style="width:${(100 * v) / total}%;background:${color(k, i)}"></div>`).join("");
		const legend = entries.map(([k, v], i) => `<span><span style="color:${color(k, i)}">&#9632;</span> ${esc(k)} ${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>`).join("");
		return `<div class="bar">${segs}</div><div class="legend">${legend}</div>`;
	}

	table(cols, rows, empty) {
		if (!rows || !rows.length) return `<div class="empty">${esc(empty || __("Nothing to show"))}</div>`;
		const head = cols.map((c) => `<th>${esc(c[0])}</th>`).join("");
		const body = rows.map((r) => "<tr>" + cols.map((c) => `<td>${c[1](r)}</td>`).join("") + "</tr>").join("");
		return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
	}

	locked(module) {
		return `<div class="locked">${__("{0} is not included in your package.", [esc(module)])}</div>`;
	}

	render(d) {
		const s = d.shipments, inv = d.inventory, ex = d.exceptions, pr = d.procurement;
		const pill = (v) => `<span class="pill ${esc(String(v).replace(/ /g, "-"))}">${esc(v)}</span>`;
		const link = (dt, name, label) => `<a href="${route(dt, name)}">${esc(label || name)}</a>`;
		let h = `<div class="iq-toolbar">${__("Organization")}: <b>${esc(d.organization)}</b> &middot; ${__("Package")}: <b>${esc(d.package || "-")}</b> &middot; ${__("As of")} ${fmtDate(d.as_of)}</div>`;

		h += this.section(__("Executive summary"), __("what needs attention now"));
		h += '<div class="iq-tiles">';
		if (s) {
			h += this.tile(s.active, __("Active shipments"), "", "/desk/iq-shipment?status=%5B%22not%20in%22%2C%5B%22Delivered%22%2C%22Closed%22%2C%22Cancelled%22%5D%5D");
			h += this.tile(s.delayed, __("Delayed shipments"), s.delayed ? "bad" : "ok", "/desk/iq-shipment?is_delayed=1");
			h += this.tile(s.in_customs, __("In customs clearance"), s.in_customs ? "warn" : "", "/desk/iq-shipment?status=Customs%20Clearance");
		}
		if (ex) {
			h += this.tile(ex.open, __("Open exceptions"), ex.open ? "warn" : "ok", "/desk/iq-exception?status=Open");
			h += this.tile(ex.critical + ex.high, __("Critical / high"), ex.critical + ex.high ? "bad" : "ok", "/desk/iq-exception?status=Open&severity=%5B%22in%22%2C%5B%22Critical%22%2C%22High%22%5D%5D");
		}
		if (inv) {
			h += this.tile(inv.items, __("Items in stock records"), "", "/desk/iq-stock-balance");
			h += this.tile(inv.expiring_90_days, __("Batches expiring in 90 days"), inv.expiring_90_days ? "warn" : "ok", "/desk/iq-stock-balance?stock_status=Expiring%20Soon");
		}
		h += "</div>";

		h += this.section(__("Upstream"), __("planned, ordered and expected"));
		h += '<div class="iq-grid2">';
		h += '<div class="iq-card"><h5>' + __("Procurement") + "</h5>";
		h += pr ? `<div class="iq-tiles">${this.tile(pr.open_pos, __("Open POs"), "", "/desk/iq-purchase-order")}${this.tile(pr.pos_due_14_days, __("POs due to ship in 14 days"), "", "/desk/iq-purchase-order")}</div>` : this.locked("Procurement Intelligence");
		h += "</div>";
		h += '<div class="iq-card"><h5>' + __("Planned shipments") + "</h5>";
		h += s ? this.table([[__("Shipment"), (r) => link("IQ Shipment", r.name, r.shipment_title)], [__("Route"), (r) => `${esc(r.origin)} &rarr; ${esc(r.destination)}`], [__("Planned ETA"), (r) => fmtDate(r.planned_eta)], [__("Docs missing"), (r) => (r.missing_documents ? pill(r.missing_documents) : "0")]], s.upcoming_list, __("No planned shipments")) : this.locked("Shipment Control Tower");
		h += "</div></div>";

		h += this.section(__("In transit"), __("moving, at port or in customs"));
		h += '<div class="iq-grid2">';
		if (s) {
			h += `<div class="iq-card"><h5>${__("Shipments by status")}</h5>${this.bar(s.by_status)}<h5 style="margin-top:12px">${__("By mode")}</h5>${this.bar(s.by_mode)}
				<div class="iq-tiles" style="margin-top:12px">${this.tile(s.arriving_7_days, __("Arriving in 7 days"))}${this.tile(s.missing_documents, __("Shipments missing documents"), s.missing_documents ? "warn" : "ok")}</div></div>`;
			h += '<div class="iq-card"><h5>' + __("In transit: planned vs actual") + "</h5>" + this.table([
				[__("Shipment"), (r) => link("IQ Shipment", r.name, r.shipment_title)],
				[__("Status"), (r) => esc(r.status)],
				[__("Mode"), (r) => esc(r.transport_mode)],
				[__("Planned ETA"), (r) => fmtDate(r.planned_eta)],
				[__("Delay"), (r) => (r.delay_days ? pill(r.delay_days + "d") : "-")],
			], s.in_transit_list, __("Nothing in transit")) + "</div>";
		} else h += this.locked("Shipment Control Tower");
		h += "</div>";

		h += this.section(__("Downstream"), __("received, in stock and expiring"));
		h += '<div class="iq-grid2">';
		if (inv) {
			h += `<div class="iq-card"><h5>${__("Stock status")}</h5>${this.bar(inv.by_status)}
				<div class="iq-tiles" style="margin-top:12px">${this.tile(inv.stock_lines, __("Stock lines"))}${this.tile(inv.warehouses, __("Warehouses"), "", "/desk/iq-warehouse")}${this.tile(inv.cover_unknown, __("Lines without consumption data"), inv.cover_unknown ? "warn" : "")}</div>
				<div class="empty">${__("Stock cover is only calculated where average monthly consumption is recorded.")}</div></div>`;
			h += '<div class="iq-card"><h5>' + __("Stock alerts") + "</h5>" + this.table([
				[__("Item"), (r) => link("IQ Stock Balance", r.name, r.item_name || r.item)],
				[__("Warehouse"), (r) => esc(r.warehouse_name || r.warehouse)],
				[__("Batch"), (r) => esc(r.batch_no || "-")],
				[__("Qty"), (r) => esc(r.quantity) + " " + esc(r.uom || "")],
				[__("Cover (months)"), (r) => (r.stock_cover_months == null ? "-" : esc(r.stock_cover_months))],
				[__("Expiry"), (r) => fmtDate(r.expiry_date)],
				[__("Status"), (r) => pill(r.stock_status)],
			], inv.alerts, __("No stock alerts")) + "</div>";
		} else h += this.locked("Inventory Intelligence");
		h += "</div>";

		h += this.section(__("Intelligence"), __("priority exceptions with their evidence"));
		h += '<div class="iq-grid2">';
		if (ex) {
			h += '<div class="iq-card"><h5>' + __("Priority exceptions") + "</h5>" + this.table([
				[__("Severity"), (r) => pill(r.severity)],
				[__("Exception"), (r) => link("IQ Exception", r.name, r.title)],
				[__("Source"), (r) => (r.reference_name ? link(r.reference_doctype, r.reference_name) : "-")],
				[__("Due"), (r) => fmtDate(r.due_date)],
			], ex.top, __("No open exceptions. Click Run Checks to scan.")) + "</div>";
			h += `<div class="iq-card"><h5>${__("Open exceptions by type")}</h5>${this.bar(ex.by_type)}<div class="iq-tiles" style="margin-top:12px">${this.tile(ex.overdue, __("Past due date"), ex.overdue ? "bad" : "ok")}</div></div>`;
		} else h += this.locked("Exception Management");
		h += "</div>";

		const c = d.costs;
		const money = (v) => (v == null ? "-" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }));
		h += this.section(__("Costs & suppliers"), c ? __("landed cost in {0}", [c.base_currency]) : "");
		h += '<div class="iq-grid2">';
		if (c) {
			h += `<div class="iq-card"><h5>${__("Landed cost")}</h5><div class="iq-tiles">
				${this.tile(money(c.landed_cost_total), __("Landed cost ({0})", [c.base_currency]), "", "/desk/iq-cost-line")}
				${this.tile(money(c.actual_total), __("Actual invoiced"), "")}
				${this.tile(money(c.estimate_total), __("Estimated"), "")}
				${this.tile(c.shipments_uncosted, __("Shipments without costs"), c.shipments_uncosted ? "warn" : "ok", "/desk/iq-shipment?cost_lines_count=0")}
				</div><h5 style="margin-top:12px">${__("By category")}</h5>${this.bar(c.by_category)}</div>`;
			h += '<div class="iq-card"><h5>' + __("Highest landed cost") + "</h5>" + this.table([
				[__("Shipment"), (r) => link("IQ Shipment", r.name, r.shipment_title)],
				[__("Status"), (r) => esc(r.status)],
				[__("Landed cost"), (r) => money(r.landed_cost_total)],
				[__("Per unit"), (r) => (r.landed_cost_per_unit ? money(r.landed_cost_per_unit) + " / " + esc(r.uom || __("unit")) : "-")],
			], c.top_shipments, __("No cost lines recorded yet")) + "</div>";
			h += '<div class="iq-card"><h5>' + __("Demurrage watch") + "</h5>" + this.table([
				[__("Shipment"), (r) => link("IQ Shipment", r.name, r.shipment_title)],
				[__("Free time ends"), (r) => fmtDate(r.free_time_ends)],
				[__("Status"), (r) => (r.days > 0 ? pill(__("{0} days charged", [r.days])).replace('class="pill ', 'class="pill High ') : pill(__("{0} days left", [r.days_left])))],
				[__("Exposure"), (r) => money(r.exposure) + " " + esc(r.currency || "")],
			], c.demurrage, __("No shipments near or past free time")) + `<div class="empty">${esc(c.demurrage_note)}</div></div>`;
		} else h += this.locked("Cost Intelligence");
		if (d.suppliers) {
			h += '<div class="iq-card"><h5>' + __("Supplier performance (lowest on-time first)") + "</h5>" + this.table([
				[__("Supplier"), (r) => link("IQ Supplier", r.name, r.supplier_name)],
				[__("Measured"), (r) => esc(r.shipments_measured)],
				[__("On time"), (r) => esc(r.on_time_rate) + "%"],
				[__("Avg delay"), (r) => esc(r.avg_delay_days) + "d"],
				[__("Avg transit"), (r) => (r.avg_transit_days ? esc(r.avg_transit_days) + "d" : "-")],
				[__("PO lead time"), (r) => (r.avg_po_lead_time_days ? esc(r.avg_po_lead_time_days) + "d" : "-")],
			], d.suppliers, __("No delivered shipments measured yet")) + "</div>";
		} else h += this.locked("Supplier Intelligence");
		h += "</div>";

		const o = d.operations;
		h += this.section(__("Warehouse, distribution & cold chain"), __("movements, deliveries and QA holds"));
		h += '<div class="iq-grid2">';
		if (o) {
			let tiles = "";
			if (o.deliveries) {
				const dl = o.deliveries;
				tiles += this.tile(dl.to_dispatch, __("Deliveries to dispatch"), dl.to_dispatch ? "warn" : "", "/desk/iq-delivery?status=Draft");
				tiles += this.tile(dl.in_transit, __("Deliveries on the road"), "", "/desk/iq-delivery?status=Dispatched");
				tiles += this.tile(dl.overdue, __("Deliveries overdue"), dl.overdue ? "bad" : "ok");
				tiles += this.tile(dl.on_time_rate == null ? "-" : dl.on_time_rate + "%", __("On-time delivery"), "");
			}
			if (o.qa_hold) tiles += this.tile(o.qa_hold.length, __("Stock lines on QA hold"), o.qa_hold.length ? "bad" : "ok", "/desk/iq-stock-balance?qa_status=Quarantined");
			if (o.excursions_7d != null) tiles += this.tile(o.excursions_7d, __("Temperature excursions (7 days)"), o.excursions_7d ? "bad" : "ok", "/desk/iq-temperature-log?is_excursion=1");
			if (o.draft_movements != null) tiles += this.tile(o.draft_movements, __("Draft stock movements"), o.draft_movements ? "warn" : "", "/desk/iq-stock-movement?docstatus=0");
			h += `<div class="iq-card"><h5>${__("Operations")}</h5><div class="iq-tiles">${tiles}</div>`;
			if (o.movements_30d) h += `<h5 style="margin-top:12px">${__("Stock movements, last 30 days")}</h5>${this.bar(o.movements_30d)}`;
			h += "</div>";
			if (o.qa_hold && o.qa_hold.length) {
				h += '<div class="iq-card"><h5>' + __("QA hold: awaiting decision") + "</h5>" + this.table([
					[__("Item"), (r) => link("IQ Stock Balance", r.name, r.item_name || r.item)],
					[__("Batch"), (r) => esc(r.batch_no || "-")],
					[__("Qty"), (r) => esc(r.quantity) + " " + esc(r.uom || "")],
					[__("Reason"), (r) => esc((r.qa_hold_reason || "").slice(0, 90))],
				], o.qa_hold) + "</div>";
			}
			if (o.deliveries) {
				h += '<div class="iq-card"><h5>' + __("Open deliveries") + "</h5>" + this.table([
					[__("Delivery"), (r) => link("IQ Delivery", r.name, r.recipient)],
					[__("Destination"), (r) => esc(r.destination)],
					[__("Planned"), (r) => fmtDate(r.planned_delivery_date)],
					[__("Status"), (r) => pill(r.status)],
				], o.deliveries.open_list, __("No open deliveries")) + "</div>";
			}
			if (o.recent_movements) {
				h += '<div class="iq-card"><h5>' + __("Recent stock movements") + "</h5>" + this.table([
					[__("Movement"), (r) => link("IQ Stock Movement", r.name)],
					[__("Type"), (r) => esc(r.movement_type)],
					[__("Date"), (r) => fmtDate(r.posting_date)],
					[__("Qty"), (r) => esc(r.total_quantity)],
				], o.recent_movements, __("No movements in the last 30 days")) + "</div>";
			}
		} else h += this.locked("Warehouse & Batch Control / Distribution / Cold Chain");
		h += "</div>";

		if (d.compliance) {
			const cp = d.compliance;
			h += this.section(__("Compliance & finance"), __("privileges, permits and LC deadlines"));
			h += '<div class="iq-grid2">';
			if (cp.privileges_by_validity) {
				h += `<div class="iq-card"><h5>${__("Privileges & permits by validity")}</h5>${this.bar(cp.privileges_by_validity)}
					<div class="iq-tiles" style="margin-top:12px">${this.tile(cp.privileges_pending_review, __("Awaiting review"), cp.privileges_pending_review ? "warn" : "ok", "/desk/iq-privilege")}</div></div>`;
			}
			if (cp.lc_cases) {
				h += '<div class="iq-card"><h5>' + __("Open LC cases") + "</h5>" + this.table([
					[__("LC"), (r) => link("IQ LC Case", r.name, r.lc_number || r.name)],
					[__("Bank"), (r) => esc(r.bank)],
					[__("Status"), (r) => esc(r.status)],
					[__("Amount"), (r) => esc(r.currency) + " " + money(r.amount)],
					[__("Next deadline"), (r) => fmtDate(r.next_deadline)],
					[__("Checklist"), (r) => esc(r.checklist_progress) + "%"],
				], cp.lc_cases, __("No open LC cases")) + "</div>";
			}
			h += "</div>";
		}

		h += this.section(__("Performance"), "");
		h += '<div class="iq-grid2"><div class="iq-card">';
		if (d.performance) {
			const p = d.performance;
			h += `<div class="iq-tiles">${this.tile(p.on_time_rate == null ? "-" : p.on_time_rate + "%", __("On-time arrival rate"), "")}${this.tile(p.delivered_shipments, __("Delivered shipments measured"))}</div><div class="empty">${esc(p.on_time_definition)}</div>`;
		} else h += this.locked("Shipment Control Tower");
		h += "</div>";
		h += '<div class="iq-card"><h5>' + __("Recent imports") + "</h5>";
		h += d.imports ? this.table([[__("Batch"), (r) => link("IQ Import Batch", r.name)], [__("Type"), (r) => esc(r.import_type)], [__("Status"), (r) => esc(r.status)], [__("Rows"), (r) => esc(r.total_rows)], [__("Errors"), (r) => esc(r.error_rows)]], d.imports, __("No imports yet")) : this.locked("Data Intake");
		h += "</div></div>";

		this.$body.html(h);
		this.$body.find(".iq-tile[data-href!='']").on("click", function () {
			const href = $(this).attr("data-href");
			if (href) window.location.href = href;
		});
	}
}

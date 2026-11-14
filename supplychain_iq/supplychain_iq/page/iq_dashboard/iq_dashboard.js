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
	Expired: "#c53030", "Out of Stock": "#9b2c2c", Critical: "#c53030", "Customs Clearance": "#805ad5",
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
		page.add_inner_button(__("Import Stock File"), () => new_import("Existing Stock"), add);
		page.add_inner_button(__("Import Shipments File"), () => new_import("Inbound Shipments"), add);

		const go = __("View");
		page.add_inner_button(__("Open Exceptions"), () => frappe.set_route("List", "IQ Exception", { status: "Open" }), go);
		page.add_inner_button(__("Delayed Shipments"), () => frappe.set_route("List", "IQ Shipment", { is_delayed: 1 }), go);
		page.add_inner_button(__("Stock Alerts"), () => frappe.set_route("List", "IQ Stock Balance", { stock_status: ["!=", "OK"] }), go);
		page.add_inner_button(__("Import History"), () => frappe.set_route("List", "IQ Import Batch"), go);

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
		const legend = entries.map(([k, v], i) => `<span><span style="color:${color(k, i)}">&#9632;</span> ${esc(k)} ${v}</span>`).join("");
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

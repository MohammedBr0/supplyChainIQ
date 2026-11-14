// Diplomatic Affairs dashboard (personal data: restricted roles only)
frappe.pages["iq-diplomatic"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Diplomatic Affairs"), single_column: true });
	wrapper.dip = new IQDiplomatic(page);
};
frappe.pages["iq-diplomatic"].on_page_show = (wrapper) => wrapper.dip && wrapper.dip.refresh();

class IQDiplomatic {
	constructor(page) {
		this.page = page;
		this.org = null;
		this.$body = $('<div class="iq-dash"></div>').appendTo(page.main);
		page.set_primary_action(__("Run Checks"), () => this.run_checks(), "refresh");
		page.set_secondary_action(__("Refresh"), () => this.refresh());
		const add = __("Add");
		page.add_inner_button(__("Diplomat Persona"), () => frappe.new_doc("IQ Diplomatic Persona"), add);
		page.add_inner_button(__("Diplomatic ID"), () => frappe.new_doc("IQ Diplomatic ID"), add);
		page.add_inner_button(__("Personal Privilege"), () => frappe.new_doc("IQ Personal Privilege"), add);
		page.add_inner_button(__("Organization Privilege"), () => frappe.new_doc("IQ Privilege"), add);
		const go = __("View");
		page.add_inner_button(__("Renewals in progress"), () => frappe.set_route("List", "IQ Diplomatic ID", { renewal_status: ["not in", ["Not Started", "Collected"]] }), go);
		page.add_inner_button(__("Privileges pending review"), () => frappe.set_route("List", "IQ Personal Privilege", { review_status: ["in", ["Draft", "Under Review", "Needs Legal Review"]] }), go);
		page.add_inner_button(__("Departing staff"), () => frappe.set_route("List", "IQ Diplomatic Persona", { persona_status: ["!=", "Departed"] }), go);
		page.add_menu_item(__("SupplyChain IQ Dashboard"), () => frappe.set_route("iq-dashboard"));
		frappe.call("supplychain_iq.api.diplomatic.get_organizations").then((r) => {
			const orgs = r.message || [];
			if (orgs.length > 1) {
				const fld = page.add_field({ fieldtype: "Select", fieldname: "organization", label: __("Organization"), options: orgs, default: orgs[0],
					change: () => { this.org = fld.get_value(); this.refresh(); } });
			}
			this.org = orgs[0] || null;
			this.refresh();
		});
	}

	refresh() {
		frappe.call("supplychain_iq.api.diplomatic.get_data", { organization: this.org }).then((r) => this.render(r.message));
	}

	run_checks() {
		frappe.call({ method: "supplychain_iq.api.dashboard.run_checks", args: { organization: this.org }, freeze: true }).then(() => this.refresh());
	}

	render(d) {
		const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
		const date = (v) => (v ? frappe.datetime.str_to_user(v) : "-");
		const link = (dt, n, label) => `<a href="/desk/${frappe.router.slug(dt)}/${encodeURIComponent(n)}">${esc(label || n)}</a>`;
		const pill = (v, cls) => `<span class="pill ${esc(cls || String(v).replace(/ /g, "-"))}">${esc(v)}</span>`;
		const tile = (v, l, cls, href) => `<div class="iq-tile ${cls || ""}" ${href ? `onclick="window.location.href='${href}'"` : ""}><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`;
		const table = (cols, rows, empty) => (!rows || !rows.length) ? `<div class="empty">${esc(empty)}</div>` :
			`<table><thead><tr>${cols.map((c) => `<th>${esc(c[0])}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => "<tr>" + cols.map((c) => `<td>${c[1](r)}</td>`).join("") + "</tr>").join("")}</tbody></table>`;
		const bar = (counts) => {
			const e = Object.entries(counts || {}), tot = e.reduce((a, [, v]) => a + v, 0);
			const C = ["#2c3e74", "#2f855a", "#b7791f", "#c53030", "#6b46c1", "#319795"];
			if (!tot) return `<div class="empty">${__("No records")}</div>`;
			return `<div class="bar">${e.map(([k, v], i) => `<div title="${esc(k)}" style="width:${(100 * v) / tot}%;background:${C[i % C.length]}"></div>`).join("")}</div>
				<div class="legend">${e.map(([k, v], i) => `<span><span style="color:${C[i % C.length]}">&#9632;</span> ${esc(k)} ${v}</span>`).join("")}</div>`;
		};
		const p = d.personas, ids = d.ids, pv = d.privileges;
		let h = `<div class="iq-toolbar">${__("Organization")}: <b>${esc(d.organization)}</b> &middot; ${__("As of")} ${date(d.as_of)} &middot;
			<span>${__("Personal data: visible only to Protocol Officers, HR Officers and Org Admins. IQ records your organization's workflow; it does not submit to authorities.")}</span></div>`;
		h += `<div class="iq-section"><h4>${__("Overview")}</h4></div><div class="iq-tiles">
			${tile(p.active, __("Active diplomat personas"), "", "/desk/iq-diplomatic-persona")}
			${tile(ids.due.length, __("IDs due for renewal"), ids.due.length ? "bad" : "ok", "/desk/iq-diplomatic-id?id_status=Renewal%20Due")}
			${tile(ids.in_renewal.length, __("Renewals in progress"), "")}
			${tile(ids.follow_up_overdue.length, __("Follow-ups overdue"), ids.follow_up_overdue.length ? "bad" : "ok")}
			${tile(pv.expiring.length, __("Personal privileges expiring"), pv.expiring.length ? "warn" : "ok")}
			${tile(pv.pending_review.length, __("Privileges pending review"), pv.pending_review.length ? "warn" : "")}
			${tile(p.departing_60d.length, __("Departures in 60 days"), p.departing_60d.length ? "warn" : "")}</div>`;
		h += `<div class="iq-section"><h4>${__("People")}</h4></div><div class="iq-grid2">
			<div class="iq-card"><h5>${__("Personas by category")}</h5>${bar(p.by_category)}
				<h5 style="margin-top:12px">${__("Diplomatic IDs by status")}</h5>${bar(ids.by_status)}</div>
			<div class="iq-card"><h5>${__("Upcoming departures (close-out)")}</h5>${table([
				[__("Name"), (r) => link("IQ Diplomatic Persona", r.name, r.full_name)], [__("Category"), (r) => esc(r.diplomatic_category)],
				[__("Assignment ends"), (r) => date(r.assignment_end_date)], [__("Open IDs / privileges"), (r) => `${r.active_ids || 0} / ${r.active_privileges || 0}`],
			], p.departing_60d, __("No departures in the next 60 days"))}</div></div>`;
		h += `<div class="iq-section"><h4>${__("Diplomatic IDs")}</h4></div><div class="iq-grid2">
			<div class="iq-card"><h5>${__("Due for renewal (not started)")}</h5>${table([
				[__("Name"), (r) => link("IQ Diplomatic ID", r.name, r.employee_name)], [__("Type"), (r) => esc(r.id_type)],
				[__("Expiry"), (r) => date(r.expiry_date)], [__("Status"), (r) => pill(r.id_status, r.id_status === "Expired" ? "Critical" : "High")],
			], ids.due, __("No IDs due"))}</div>
			<div class="iq-card"><h5>${__("Renewals in progress")}</h5>${table([
				[__("Name"), (r) => link("IQ Diplomatic ID", r.name, r.employee_name)], [__("Stage"), (r) => esc(r.renewal_status)],
				[__("Next follow-up"), (r) => date(r.next_follow_up)], [__("Expiry"), (r) => date(r.expiry_date)],
			], ids.in_renewal, __("No renewals in progress"))}</div></div>`;
		h += `<div class="iq-section"><h4>${__("Privileges")}</h4></div><div class="iq-grid2">
			<div class="iq-card"><h5>${__("Personal privileges by type")}</h5>${bar(pv.by_type)}
				<h5 style="margin-top:12px">${__("Quota use (75%+)")}</h5>${table([
				[__("Name"), (r) => link("IQ Personal Privilege", r.name, r.full_name)], [__("Privilege"), (r) => esc(r.privilege_type)],
				[__("Used"), (r) => `${esc(r.used_value)} / ${esc(r.quota_value)} ${esc(r.quota_unit || "")}`], [__("%"), (r) => pill(r.quota_used_pct + "%", r.quota_used_pct >= 90 ? "High" : "Medium")],
			], pv.quota_high, __("No quotas near their limit"))}</div>
			<div class="iq-card"><h5>${__("Expiring or pending review")}</h5>${table([
				[__("Name"), (r) => link("IQ Personal Privilege", r.name, r.full_name)], [__("Privilege"), (r) => esc(r.privilege_type)],
				[__("Expiry"), (r) => date(r.expiry_date)], [__("Review"), (r) => esc(r.review_status)], [__("Validity"), (r) => esc(r.validity_status)],
			], [...pv.expiring, ...pv.pending_review.filter((x) => !pv.expiring.includes(x))], __("Nothing expiring or pending"))}</div>`;
		if (d.org_privileges) {
			h += `<div class="iq-card"><h5>${__("Organization privileges")}</h5>${bar(d.org_privileges.by_validity)}${table([
				[__("Privilege"), (r) => link("IQ Privilege", r.name, r.title)], [__("Type"), (r) => esc(r.privilege_type)],
				[__("Review"), (r) => esc(r.review_status)], [__("Expiry"), (r) => date(r.expiry_date)],
			], d.org_privileges.list, __("No organization privileges"))}</div>`;
		}
		h += `<div class="iq-card"><h5>${__("Open diplomatic exceptions")}</h5>${table([
			[__("Severity"), (r) => pill(r.severity)], [__("Exception"), (r) => link("IQ Exception", r.name, r.title)], [__("Due"), (r) => date(r.due_date)],
		], d.exceptions, __("No open exceptions. Click Run Checks to scan."))}</div></div>`;
		this.$body.html(h);
	}
}

## SupplyChain IQ

The intelligence layer for end-to-end supply chains: Ethiopia first, Africa ready.
SupplyChain IQ is a [Frappe Framework](https://frappe.io/framework) v16 app (`supplychain_iq`).
It complements ERP and government systems rather than replacing them. Customers can start with spreadsheets and manual entry; integrations are optional.

This repository **is** the Frappe app. Clone it into `frappe-bench/apps/supplychain_iq`, or let the Dockerfile do that for you.

### What is built (blueprint stages 1–4)

| Area | What works |
| --- | --- |
| Customers and packages | `IQ Organization`, `IQ Package` with module entitlements and usage limits (users, active shipments, warehouses, import rows). Members get IQ roles automatically. |
| Tenant isolation | Every operational record carries `organization`. Server-side query filters, document permission checks, organization stamping and cross-organization link checks (see `supplychain_iq/tenancy.py`). |
| Shipment Control Tower | Shipments with ordered transport legs (multimodal needs the *Multimodal Corridor* module), milestones (overdue detection), document checklist and delay calculation. |
| Procurement | Suppliers and purchase orders (PO links need *Procurement Intelligence*). |
| Inventory | Items, warehouses and stock balances by batch, with stock cover, days to expiry and stock status. |
| File intake | `IQ Import Batch` for existing stock (path B) and inbound shipments. Staged pipeline: CSV/XLSX → column mapping → row validation → preview → explicit confirm. Supports Ethiopian-calendar dates. |
| Intelligence | Deterministic exception rules (delays, overdue milestones, missing documents, stock out, low cover, expiry), each with its evidence. Duplicates are suppressed, cleared conditions auto-resolve, and the rules run daily or on demand. |
| Cost Intelligence (stage 4) | `IQ Exchange Rate` records each rate with its source and date. `IQ Cost Line` holds estimate and actual costs by category (purchase, freight, insurance, duties, clearance, port, storage, demurrage, inland, distribution), each converted to base currency using the latest rate on or before the cost date (or a manual rate with a note). Each shipment rolls these up into a landed cost and a per-unit cost, with actuals replacing estimates per category. Demurrage is calculated from free time and the daily rate. Exception rules flag demurrage and cost overruns. The **IQ Landed Cost** report gives a breakdown for each shipment. |
| Supplier Intelligence (stage 4) | On-time arrival rate, average delay, transit time and PO lead time for each supplier, recalculated whenever a shipment changes and daily. The **IQ Supplier Performance** report shows the same figures. |
| Unified dashboard | `/desk/iq-dashboard` is the main route: root, login and the apps screen land on it. Sections cover upstream, in transit, downstream, intelligence and performance, scoped to the user's organization. A grouped SupplyChain IQ sidebar and Add/View quick-action menus are included. |

Not built yet: regulatory privileges, diplomatic ID and LC workflows (stage 5), cold chain, distribution and warehouse movements (stage 6), integrations (stage 7) and document/AI extraction.

### Local development

Prerequisites: Python 3.14, Node 24, Yarn, Redis, PostgreSQL (or MariaDB) and `frappe-bench`. See [Frappe's installation guide](https://docs.frappe.io/framework/user/en/installation).

```bash
bench init frappe-bench --frappe-branch version-16
```

```bash
cd frappe-bench && bench get-app https://github.com/MohammedBr0/supplyChainIQ
```

```bash
bench new-site development.localhost --db-type postgres --install-app supplychain_iq
```

```bash
DEMO_PASSWORD='choose-one' bench --site development.localhost execute supplychain_iq.setup.demo.create_demo
```

```bash
bench start
```

The demo creates two **synthetic** organizations, so you can check that each one sees only its own data:

| User | Organization / package | IQ role |
| --- | --- | --- |
| `relief.admin@demo.example` | Demo Relief Org / IQ Professional | Org Admin |
| `relief.logistics@demo.example` | Demo Relief Org | Logistics Officer |
| `relief.warehouse@demo.example` | Demo Relief Org | Warehouse Officer |
| `pharma.admin@demo.example` | Demo Pharma Importer / IQ Essential | Org Admin |

### Tests

```bash
bench --site development.localhost set-config allow_tests true
```

```bash
bench --site development.localhost run-tests --app supplychain_iq
```

The 46 tests cover cost intelligence (rate resolution, landed cost roll-up, demurrage, overruns, supplier performance), as well as tenant isolation, entitlements and limits, the import pipeline (mapping, validation, preview gating, immutability, Ethiopian dates), calculations, exception lifecycle and dashboard scoping.

### Deployment (Render + Neon)

The `Dockerfile` builds a single image: Frappe v16, this app, gunicorn and a local Redis. `deploy/entrypoint.sh` does the following on each start:

1. writes the site config from environment variables,
2. installs the site on first boot, otherwise runs `migrate`,
3. optionally loads the demo data,
4. starts gunicorn on `$PORT`.

| Variable | Required | Notes |
| --- | --- | --- |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | yes | PostgreSQL (e.g. Neon). TLS is on by default (`PGSSLMODE=require`). |
| `ADMIN_PASSWORD` | yes | Password for the `Administrator` user, used on first install. |
| `ENCRYPTION_KEY` | yes | Fernet key. Keep it stable, or encrypted fields become unreadable. |
| `FRAPPE_SITE` | no | Internal site name, default `iq.local`. |
| `DEMO_PASSWORD` | no | When set, loads or refreshes the synthetic demo organizations and users. |
| `ENABLE_BACKGROUND` | no | `1` starts the worker and scheduler (daily exception checks). Needs more than 512 MB. |

Known limits on Render's free plan:
- The service sleeps when idle, and the first request takes about a minute.
- Uploaded files live on the container disk and are lost on redeploy (imported data is kept in the database). Add a persistent disk or object storage before production.
- Real-time (socket.io) updates are off.

See `docs/ARCHITECTURE.md` for the decisions behind this design.

### License

Proprietary. All rights reserved.

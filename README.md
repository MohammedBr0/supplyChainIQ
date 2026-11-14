## SupplyChain IQ

The intelligence layer for end-to-end supply chains: Ethiopia first, Africa ready.
SupplyChain IQ is a [Frappe Framework](https://frappe.io/framework) v16 app (`supplychain_iq`).
It complements ERP and government systems rather than replacing them. Customers can start with spreadsheets and manual entry; integrations are optional.

This repository **is** the Frappe app. Clone it into `frappe-bench/apps/supplychain_iq`, or let the Dockerfile do that for you.

### What is built (blueprint stages 1–6, plus partner portals and the Diplomatic Affairs app)

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
| Warehouse and batch control (stage 6) | `IQ Stock Movement` (receipt, issue, transfer, adjustment in/out) is submitted and cancelled like an accounting document, and posts to an append-only `IQ Stock Ledger Entry`. Issues and transfers allocate batches by **FEFO**, skipping expired and QA-held stock. Once a stock line has ledger history, its quantity can only change through a movement. Receipts against a shipment mark it received and flag quantity discrepancies. Imported stock counts are written to the ledger. The **IQ Stock Summary** report shows issuable, on-hold and expired stock, consumption from recorded issues, and stock cover. |
| Distribution and delivery (stage 6) | `IQ Delivery`: dispatch issues the stock by FEFO and records which batches went where. Confirming delivery requires the delivered date, the receiver and an attached proof of delivery. Partial deliveries and on-time delivery are tracked, and a cancelled dispatch returns the stock. |
| Cold chain (stage 6) | `IQ Temperature Log` readings are typed in or imported from logger CSV/XLSX, and checked against the item or warehouse range. They cannot be edited after saving. An excursion **puts the affected cold-chain stock on QA hold automatically**, and cargo received from a shipment that had an excursion is held on arrival. Only a QA Officer or Org Admin can release or reject stock, with notes; IQ never releases stock on its own. |
| Regulatory & Privileges (stage 5) | `IQ Privilege` records duty-free privileges, permits and exemptions: authority, reference, jurisdiction, scope, source document, and conditions each tied to a page or paragraph. **Validity is never assumed**: either the stated expiry date is entered or "no expiry stated" is ticked. **Maker-checker review**: the person who submits a record cannot confirm it, and substantive edits send it back for re-review. Shipments link to a privilege, and IQ flags planned arrivals outside the recorded validity or unconfirmed privileges. These are checks on your records, not legal advice. |
| LC & Import Finance (stage 5) | `IQ LC Case` holds an editable bank checklist template, milestones that drive its status, and the latest shipment date, expiry and presentation deadline (calculated from linked shipments). IQ warns before deadlines. It never issues LCs or approves foreign exchange. |
| Diplomatic Affairs app | A separate entry on the apps screen (`/desk/iq-diplomatic`). It is **off by default**; an Org Admin enables it, and only NGO/INGO/UN-related and international organizations qualify. It holds diplomat personas (category, dependants, passport, assignment dates), diplomatic ID renewal (requirements checklist, internal review, submission, follow-up, collection, with no claim to submit to authorities) and personal privileges (vehicle and personal-effects duty-free imports, plates, tax cards, residence), with tracked quota use and the same maker-checker review. Only Protocol Officers, HR Officers and Org Admins can see this personal data, including in exceptions. |
| Partner portals | Logins for suppliers and transitors (clearing and forwarding agents) at `/iq-portal`, with no desk access. Suppliers see their own POs and shipments; they confirm POs, update ETD and AWB/BL, record origin milestones and upload shipping documents. Transitors see shipments assigned to them; they record port and customs milestones, update status and port arrival, upload documents and submit charges, which arrive as estimates for verification. Every portal action is checked against the partner's link and written to the record's timeline. |
| Customs management | `IQ Customs Case` per shipment covers the customs office, procedure (home consumption, duty-free privilege, transit, temporary import, re-export), declaration, declarant and inspection lane. Tax lines (duty, VAT, excise, surtax, withholding, levies) record amounts exactly as assessed, with exemptions and their basis, and payments. Status follows the process dates; clearance time is tracked. The case updates the shipment's milestones and status, and paid duties become an actual "Duties & Taxes" cost line automatically. Alerts fire for slow clearance and unpaid duties. Transitors can work their customs cases from the portal. |
| Item lines, shipping notices and returns | Shipments carry item lines (item, quantity, batch, expiry, value). Landed cost is allocated per line by value or by quantity. **Create Receipt** drafts the warehouse receipt from outstanding lines, and receipt discrepancies are compared line by line. Suppliers can submit an **advance shipping notice** with packing details against a confirmed PO from the portal. **Record Return** on a delivery puts goods back into the batches that were dispatched (latest expiry first), always on QA hold for inspection, and closes the delivery once every unit is delivered or returned. |
| Unified dashboard | `/desk/iq-dashboard` is the main route: root, login and the apps screen land on it. Sections cover upstream, in transit, downstream, intelligence and performance, scoped to the user's organization. A grouped SupplyChain IQ sidebar and Add/View quick-action menus are included. |

In progress: audit log, ERP integration API and notifications; document extraction; AI analyst (needs an API key); persistent file storage on Render (needs object storage).

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
| `relief.qa@demo.example` | Demo Relief Org | QA Officer |
| `relief.compliance@demo.example` | Demo Relief Org | Compliance Officer |
| `relief.protocol@demo.example` | Demo Relief Org (Diplomatic Affairs enabled) | Protocol Officer |
| `supplier.demo@demo.example` | Supplier portal: Example Global Health Supplies | portal |
| `transitor.demo@demo.example` | Transitor portal: Example Clearing & Forwarding PLC | portal |
| `pharma.admin@demo.example` | Demo Pharma Importer / IQ Essential | Org Admin |

### Tests

```bash
bench --site development.localhost set-config allow_tests true
```

```bash
bench --site development.localhost run-tests --app supplychain_iq
```

The 83 tests cover customs (status, exemptions, duties cost line, alerts), line allocation, receipts from lines, returns, supplier shipping notices and transitor customs scope, as well as privileges (validity rules, maker-checker review, conflicts), LC deadlines, the Diplomatic Affairs opt-in and its personal-data restrictions, renewal steps and quotas, and portal scoping and security, as well as warehouse movements (FEFO, ledger, cancellation, transfers, quantity locking, shipment receipts), deliveries (dispatch, proof of delivery, shortfalls, cancellation) and cold chain (excursions, QA hold and release permissions, logger import), as well as cost intelligence (rate resolution, landed cost roll-up, demurrage, overruns, supplier performance), as well as tenant isolation, entitlements and limits, the import pipeline (mapping, validation, preview gating, immutability, Ethiopian dates), calculations, exception lifecycle and dashboard scoping.

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

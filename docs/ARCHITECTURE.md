# Architecture and decisions (MVP)

## Layers implemented

| Blueprint layer | Implementation |
| --- | --- |
| 1. Customer and subscription | `IQ Package` (module catalogue entries and limits) and `IQ Organization` (package, status, members, thresholds). `entitlements.py` enforces both on the server. |
| 2. Data intake | `intake/` handles reading, mapping (synonyms plus flagged similarity matches) and dates (Gregorian, Excel serial, Ethiopian). `importer.py` is a staged pipeline. |
| 3. Functional modules | Shipments (legs, milestones, documents), POs, suppliers, items, warehouses, stock balances. |
| 4. Intelligence engine | `intelligence/calculations.py` holds pure, deterministic functions. `exceptions.py` holds the rule engine. |
| 5. Workflow and exceptions | `IQ Exception` (owner, due date, resolution notes, auto-resolve). Change history comes from Frappe's track-changes. |
| 6. Unified dashboard | The `iq-dashboard` page, served by `api/dashboard.py`. |

## ADR-1: Frappe v16 on PostgreSQL
Frappe gives users, roles, forms, an API, background jobs and migrations out of the box. PostgreSQL was chosen so the app runs on managed Postgres (Neon) and Render, which offer no MariaDB. ERPNext is not a dependency.

## ADR-2: Tenancy is organization-level inside one site (for now)
The blueprint review recommended one Frappe site per customer for the strongest isolation. For the MVP, a single deployment hosts all customers in one site, with these controls:

- `permission_query_conditions` filters every list, report and `get_list` call by organization.
- `has_permission` denies document access across organizations, and denies it when the module is not entitled.
- The `validate` hook stamps the organization and rejects writes and links into other organizations.
- Platform staff (System Manager) see all organizations.

Residual risks:
- `frappe.get_all` and raw SQL bypass permissions. Code must always filter by organization, and the tests cover the API surface.
- Frappe's standard report builder respects the query conditions, but custom Script Reports must as well.

Revisit before onboarding real UN or diplomatic data: move high-sensitivity customers to dedicated sites or databases. The app code supports that unchanged, because one organization per site still works.

## ADR-3: Stock cover is never invented
Float columns cannot store NULL in Frappe, so `cover_available` records whether stock cover could be calculated. Without average monthly consumption, cover is unknown rather than 0.

## ADR-4: Imports are re-validated at confirmation
Confirming an import re-reads the source file and re-runs validation. Records are written only when the result has no errors. Similarity-based column matches need explicit confirmation. Imported batches are immutable, and their status fields can only be set by the server pipeline.

## ADR-5: Single-container deployment
gunicorn, a local Redis and static file serving (`deploy_wsgi.py`) run in one container, which fits Render's 512 MB free plan (about 200 MB in use). The worker and scheduler are optional (`ENABLE_BACKGROUND=1`).

## Next stages
4. Cost intelligence (landed cost, FX rate source and date per cost line).
5. Regulatory privileges, diplomatic ID and LC workflows (source-linked rules, reviewer approval).
6. Multimodal corridor analytics, cold chain, distribution.
7. Integration adapters, object storage for files, per-customer sites.

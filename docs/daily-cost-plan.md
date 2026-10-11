# Daily Cost Management — entry UX and data plan

Status: the daily cost module (register, day sheet, baselines, import, submit/reopen,
dashboard) is built and covered by tests. This document plans the daily cost **entry
experience** and records how the data captured from the AFE and the daily cost sheet
is structured so the future cost-analysis and reporting modules need no rework.
Everything in "Future modules" is explicitly **not shipped yet**.

The working Excel cost sheet was not attached to this session. The capture structure
below follows the AFE estimate and the app's daily sheet; when the Excel is shared,
map its columns one-to-one against the tables in "What is captured today" and record
any gap as a follow-up.

---

## 1. How the data is captured today (the part that matters)

The analytics value of every future module depends on two frozen inputs and one
transactional fact table. All of it is column-wise storage (no JSON blobs), tenant
scoped, audited, soft-deleted.

### 1.1 AFE side — the plan (locked once per AFE)

When the first daily sheet of a well + AFE is created, the app snapshots:

| Snapshot table | Content | Why future modules need it |
| --- | --- | --- |
| `daily_cost_baselines` | AFE code/name, standard currency, group totals, grand total, lock time/actor | Planned vs actual comparisons never drift when the AFE is later revised |
| `daily_cost_baseline_budget_lines` | One row per AFE cost line: group (Services/Consumables/Tangibles), kind, code/name, section/phase, quantity, unit rate, native amount, currency, FX, planned amount | Budget-key matching turns itemized daily actuals into category balances |
| `daily_cost_baseline_service_rates` | Every rate card row of Day Rate / Per Service Rate / Per Section Rate services | A daily line quotes the exact saved AFE rate, so rate variances are traceable |
| `daily_cost_baseline_sections` / `..._phases` | The configured well plan (sections, phases, days) | Depth/phase context for cost per section and cost per phase reporting |
| `daily_cost_baseline_exchange_rates` | Standard currency units per foreign unit | Multi-currency roll-ups in one standard currency |
| `daily_cost_well_rate_baselines` + `..._catalogue_rate_snapshots` | Frozen price of every mud chemical, additive, fuel, drill bit and tangible at lock time | Chemicals consumed daily are priced at the frozen catalogue rate, not a moving master price |

### 1.2 Daily side — the facts (one sheet per well + AFE + date)

`daily_cost_entries` is the day header: rig/well/AFE snapshot columns, cost date,
standard currency, status (draft/submitted), remarks, group totals, grand total,
UPA total, NPT total, warning count, submit/reopen custody, soft-delete columns.

`daily_cost_service_lines`, `daily_cost_consumable_lines`, `daily_cost_tangible_lines`
share one column-wise shape (`daily_cost_lines`):

- **Scope**: activity (code/name snapshot), hole section + phase, sub activity,
  classification (`Planned` / `UPA` / `NPT`), vendor or responsible party.
- **Quantity**: value + unit (`days`, `hours`, `service`, `section`, `unit`); hours
  convert to day fractions for Day Rate charging.
- **Price honesty**: `captured_rate` (the locked rate), `override_rate` (optional
  user override), `override_reason` (mandatory with an override), `rate_source`
  (`afe_baseline`, `catalogue_baseline`, `daily_override`, `manual_unplanned`),
  catalogue revision number and effective date.
- **Money**: `amount` (native currency), `exchange_rate`, `standard_amount`
  (AFE standard currency), plus `budget_key` + `baseline_budget_line_id` linking the
  actual to its planned allowance.

Because every row stores both native and standard amounts with its FX factor, any
future report can slice by currency, group, section, phase, activity, vendor,
classification or day without re-deriving conversions.

### 1.3 Rules that protect the analysis

1. **Immutability after submit** — a submitted sheet is read-only; reopen requires a
   reason and is audited. Reports can trust the numbers per day.
2. **Baselines never update silently** — master-data price changes do not leak into
   open or submitted sheets; a new AFE or a reopened baseline is an explicit act.
3. **Rate overrides are justified and audited** — each override writes its own audit
   entry with old rate, new rate and reason.
4. **Actual-to-date is cumulative** — the comparison endpoint folds every active
   sheet of the same baseline up to the effective date, drafts included and labelled.
5. **Bulk allowance reconciliation** — itemized chemical/fuel actuals map to their
   `consumable_category` budget envelope, so the AFE balance stays meaningful while
   the sheet stays itemized.

---

## 2. The daily entry UX (shipped in this increment)

The entry surface is `Daily Cost Management → day sheet` and is designed around one
principle: **a cost controller records a day in under a minute, with zero pricing
decisions unless something changed.**

1. **Start a day** (register page): pick well, AFE and date; the app validates the
   well plan, the AFE estimate and duplicate dates, then locks the baselines.
2. **Prefill — Copy previous day** (new): one click pulls the closest earlier sheet
   of the same well and AFE with all lines; the drafter only edits quantities.
   Copying replaces the draft's lines after an explicit confirm when the draft is
   not empty; the current remarks are kept.
3. **Add or edit a line**: the dialog offers only valid choices — activities,
   sections/phases from the locked plan, services with their saved AFE rate cards,
   catalogue items with their frozen rates. Amounts price instantly; UPA/NPT lines
   must identify the responsible party; overrides require a reason.
4. **See the day in context while typing**: totals, UPA/NPT, AFE remaining balance
   and budget-line reconciliation update through a live preview before saving.
5. **Close the day**: Save, then Submit (locks the sheet). Import (CSV/XLSX) and
   export remain available for sheet-level and register-level flows; every action is
   permission-gated (`daily-cost:*`) and audited.
6. **Register page**: all sheets with quick search, advanced filters, date-range
   filter, pagination (20/50/100), bulk actions, Deleted Entries view, and the
   module dashboard (planned vs actual by currency, group balances, 30-day trend,
   recent activity).

---

## 3. Future modules (planned, not built)

### Module A — Day-by-day operations view

A well-centric daily timeline (default: today; date picker to move across the well's
history). One row per day per well/AFE: date, status, day total, cumulative total,
AFE remaining, UPA/NPT flags. Row click opens the day sheet. This is a read model
over `daily_cost_entries` — **no new capture is required**; it needs only list
endpoints filtered by well and date range with server pagination (already covered by
the standing conventions).

### Module B — Whole-well cost details (all factors)

A single "well cost book" screen for one well (+ its AFEs):

- Planned vs actual vs balance per group (Services/Consumables/Tangibles), per
  budget line, per section, per phase, per activity, per vendor, per currency.
- Classification breakdown: planned, UPA, NPT with responsible parties.
- Depth/day progress (from the locked plan) against spend to date.
- Full line-level drill-down (every daily line with its rate source and override
  reason) and PDF/XLSX/CSV export of any cut.

Every cut is a `GROUP BY` over existing columns (`cost_group`, `budget_key`,
`section_code_snapshot`, `phase_code_snapshot`, `activity_code_snapshot`,
`vendor_code_snapshot`, `classification`, `currency`, `standard_amount`) joined to
the baseline budget lines — the structure above was designed for exactly this.

### Module C — Cost analysis and reporting

- AFE performance: planned vs actual vs commitment; overrun early warning (the
  `over_budget_afes` KPI already exists on the dashboard).
- Well benchmarks: cost per metre/foot (needs `total_depth`, already on wells),
  cost per day, spread rate composition.
- UPA/NPT analytics: hours and value by vendor and cause, feed for contract
  management.
- Rate variance report: `captured_rate` vs `override_rate` frequency and value.
- Export pack: one PDF/XLSX well cost statement assembled from the cuts above,
  reusing the shared export and audit plumbing.

### Sequencing

1. Module A (small, read-only) — gives the "daily basis" view.
2. Module B — the complete well cost details view.
3. Module C — analytics and report packs.

No schema change is expected for A–C; they are query/UI layers over the captured
columns. If the Excel reveals an attribute the sheet does not capture, extend
`daily_cost_lines`/baselines with a typed column and snapshot it at lock time —
never a JSON blob.

---

## 4. Conventions checklist (this module)

- Audit trail for create, save, import, submit, reopen, delete, restore, purge,
  rate overrides and exports. Submitted sheets are immutable without reopen.
- Light/dark themes, Navy Blue & White palette, no animations or emojis.
- Top navigation; module dashboard; register with pagination 20/50/100.
- Quick search + advanced filters + separate date-range filter.
- Import (CSV/XLSX with preview and row-level errors) and export (CSV/XLSX/PDF).
- Pop-ups close only via Cancel; alerts appear near the data; destructive actions
  confirm via dialog.
- RBAC: `daily-cost:read/create/update/delete/restore/permanent-delete/import/
  export/submit/reopen`; the API re-checks grants on every request.
- Soft delete first; restore/purge only from Deleted Entries.

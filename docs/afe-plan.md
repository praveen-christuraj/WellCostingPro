# AFE Management: design and open questions

This document describes the AFE Management module added to WellCostingPro. It was ported for
functionality from the reference Nuxt application (praveen-christuraj/Well-Costing). The UI is
redesigned for this app's structure and models; the reference tab layout is not copied.

## Scope

- **AFE register** (`/afe/register`, tab `AFE`): well-scoped AFEs with rig, well, AFE code, name,
  type (Drilling or Completion) and remarks. Status is shown here but never changed here.
- **AFE Cost Estimation** (same page, tab `AFE Cost Estimation`): the approval workflow. Status moves
  (submit, review, approve, reopen) happen only here and in the estimate workspace.
- **Deleted entries** (same page, tab `Deleted entries`): restore or permanently delete soft-deleted AFEs.
- **Overview dashboard** (`/afe`): totals, approval progress, highest-cost wells, recent activity.
- **Estimate workspace** (`/afe/estimate/:afeId`): line-item estimate, bulk estimate by section (available from
  both the Services and Consumables cards), currency and conversion panel, section rollup, print
  (two-page AFE report, see *Print format*).

## Data model

| Table | Purpose |
| --- | --- |
| `afes` | Header: rig, well, code (unique per workspace), name, type, remarks, status, standard currency, soft-delete. |
| `afe_service_lines` | Service line: service, charging basis, scope (section, phase), currency, remarks. |
| `afe_service_rates` | Unit rate per charge category for Day Rate lines. |
| `afe_service_charges` | Explicit day quantities (days or hours) per day-based category. |
| `afe_service_section_rates` | Amount per (section, phase) for Per Section Rate lines. |
| `afe_consumable_lines` | Lump sum (Mud Chemicals, Cement Additives, Fuel) or drill bit line (bit, quantity, override). |
| `afe_tangible_lines` | Tangible line: item, quantity, override rate. |
| `afe_exchange_rates` | Conversion rate per foreign currency: units of the standard currency per one unit. Only for mixed-currency estimates. |

No JSON columns. Migration `a9d4e2f7c138` follows `f3a7d0b9c214`. Migration `b2c8f1d4a9e6` adds the
standard currency column and `afe_exchange_rates`. Both upgrade, downgrade and re-upgrade cleanly on SQLite,
and `alembic check` reports the models and migrations in sync.

Estimates are stored as line rows. Saving replaces all lines for the AFE under a row lock and a process
lock, so a double click cannot duplicate lines.

## Pricing rules (`app/domain/afe_costing.py`)

- Charge categories are fixed: Mobilization, Demobilization, Operation, Standby, Personnel-Operation,
  Personnel-Standby, Fixed Charge, Others. Mobilization, Demobilization and Fixed Charge are one-time.
- **Day Rate**: planned days × unit rate for each day-based category. Hours convert at 24 per day.
  Operation uses the planned days of the scope unless explicit Operation days are entered.
  A well-wide line (no section) is split across sections by each section's planned days, and each
  share is shown under its section. This fixes the reference bug that showed daily cost well-wide.
- **Per Section Rate**: one amount per (section, optional phase).
- **Per Service Rate**: one lump sum for the chosen section and phase.
- **Consumables**: lump sums cost the entered amount. Drill bits cost quantity × effective rate, and
  their currency comes from the drill bit's master record.
- **Tangibles**: quantity × effective rate. The override wins over the captured master rate.
  Captured rate = `final_cost` when set, otherwise `unit_rate`.
- Sections and phases come only from the well configuration. Anything outside it produces a warning,
  not a silent price.
- Money rounds to 2 decimals (half-up).
- **Currency** (`resolve_currency` in `app/domain/afe_costing.py`):
  - Each line keeps the currency it was entered in. Totals as entered are shown per currency and are never added together.
  - One detected currency: it is the standard currency. No choice and no rate are needed.
  - Several detected currencies: the user selects the standard currency and enters one conversion rate for each other
    currency (units of standard per one foreign unit, up to 6 decimals). Every line and section is converted with its rate.
  - Converted totals (services, consumables, tangibles, grand total and the section rollup) are null until every rate is
    entered. The estimate cannot be saved in that state, so a stored estimate is always fully converted.
  - Saving stores the effective standard currency and only the rates in use. Rates are a snapshot taken at save time.

## Workflow

- An AFE can be created only for an active well on an active rig whose plan has at least one section and is marked
  **Configured** in Rig & Well Management. Create, edit, import and estimate save are refused for a well whose plan is in
  Draft. Submit is refused when the plan is no longer Configured.
- Header edits, estimate edits and soft delete are allowed only in Draft.
- Transitions: submit (Draft → Submitted, needs a saved estimate with total > 0), review
  (Submitted → Review), approve (Review → Approval, remarks ≥ 3 characters), reopen (Submitted, Review or
  Approval → Draft, remarks ≥ 3 characters). Each transition checks its own permission.
- Preview prices live master data and the well plan, writes nothing, and reports every problem at once.
  The UI previews only valid lines, so one incomplete row does not block the rest.

## Print format

The printed AFE is a fixed two-page A4 portrait report with 9 mm / 10 mm / 11 mm margins, a navy
heading rule, no repeated page furniture (the page number sits in the `@page` margin box) and the
app itself hidden while printing.

**Page 1 — the AFE.**

1. Title block: "AFE Cost Estimate" with the AFE name only. It has no long-form authorization
   wording or print timestamp.
2. Compact metadata: rig, well, AFE name, AFE type, objective of the well, location / block,
   total depth and planned days. Configuration, well-plan status, AFE status and estimate-save
   details are intentionally omitted.
3. Unified cost schedule: service rows print in the fixed Master Data reporting order — Rig Operations,
   Formation Evaluation, Well Services, Land Facilities and Preparation, Miscellaneous Services,
   Supervisions — with the group captioned once at the start of its block and service-code order
   inside each block. One row per service line: name, provider / vendor, charging basis with
   its entered-currency rate detail (unit rate × charged quantity, fixed amount, or **each** section
   and phase with its entered section rate), amount in the entered currency and **remarks**.
   Scoped day-rate and per-service lines include their section / phase in the Basis cell;
   there are no separate Scope or Currency columns. The services subtotal uses the standard currency.
   The same table then shows Consumables as four categorized lump sums (**Mud Chemicals, Cement
   Additives, Fuel and Drill Bits**) plus a Consumables total, followed by the Tangibles lump sum and
   total. The **total AFE amount** closes the table.
4. The section/depth/phase plan follows the unified cost schedule on page 1.

**Page 2 — supporting detail.** Every consumable line (lump sums show their section and phase;
drill bits show the bit, make, type, size and description), and every
tangible line (manufacturer, UOM, quantity, rate, amount, remarks). Each table closes with its
standard-currency total. Warnings and the authorisation table (**Submitted by / Reviewed by /
Approved by**, each with name, email, date and an empty signature row) follow the line details.
Names come from the latest recorded move per workflow action in the audit trail; a reopen clears
stages recorded before it.

Amounts stay in each line's currency; subtotals and totals are converted to the estimate's standard
currency at the rates saved with it, and an incomplete conversion prints "Pending conversion" rather
than a wrong figure.

## Permissions and audit

- Permission keys: `afe:read`, `create`, `update`, `delete`, `restore`, `permanent-delete`, `import`,
  `export`, `estimate`, `submit`, `review`, `approve`, `reopen`. Provisioning seeds them for new
  tenants, and the migration backfills existing tenants.
- Every route is guarded. Pages are guarded by `afe:read`, and each action checks its own key.
- Audit entities: `afe`, `afe_estimate`, `afe_export`. They appear in the Audit Log entity filter.

## Reference bugs addressed

| Reference bug | Handling here |
| --- | --- |
| Duplicated lines on reload or concurrent save | Save replaces all lines under a row lock and a process lock. |
| 502 on `POST …/estimates/{id}/preview` | Preview uses the normal shared connection pool, not a shared StaticPool connection. |
| "Mud chemical #0 no longer exists" on a second lumpsum line | Lumpsum lines are keyed by client key, not by a sentinel item id. |
| Slow AFE page load | Explicit loader options instead of eager-loading cycles. |
| Lumpsum round-trip | Lumpsum stores quantity 1, captured rate 0 and the estimated amount. Load and save round-trip exactly. |
| Print shows only days and costs | Print sheet is plain HTML that prints every section in order. |
| Daily cost shown well-wide | Split per section by planned days. |
| Only the last line added is visible, although all lines are in the total | The grids keyed rows by a missing `id`, so every line shared one row id. Rows are now keyed by the line key. |
| Currency totals added across currencies | Lines are converted to one standard currency with user-entered rates. Totals stay withheld until every rate is entered. |
| AFE created for a well whose plan is not Configured | Creating, editing, importing and saving the estimate now require the plan to be Configured. |

## Daily cost (information only)

Daily cost tracking is not developed yet. The agreed rule, shown on the estimate page as information only, is that daily
expenses can be entered either as one bulk amount per service or as separate amounts per line item. Either way, the day's
total for that service is deducted from the service's estimate. Nothing is deducted today.

## Open question: mud chemical daily consumption

The reference deducts daily consumption from the mud chemical lump sum. The user has not yet confirmed
whether that should apply here. Until it does, the lump sum is kept as a plain estimated amount, and the
UI says that daily consumption is not deducted automatically.

## Verification status

- Backend: `cd backend && ../.venv/bin/python -m pytest -q` passes (84 tests in the full suite, including
  22 AFE tests). Pyflakes is clean on the AFE modules.
- Print: the two-page AFE report renders from `AfePrintSheet.tsx` with the `@media print` rules in
  `styles.css`; the estimate response carries `status_history` for the sign-off block. Verified by
  rendering the real component against sample estimates (structure, lump sums, currency conversion,
  reopen handling) plus the backend suite and `npm run build`; no browser was available in this
  environment for a print-dialog pass.
- Migration: upgrade, downgrade and re-upgrade on a fresh SQLite database; `alembic check` clean.
- Frontend: `npm run build` passes (type check and Vite build).
- `make graph` runs cleanly and refreshes `.agent/memory/architecture.dot`.
- Not verified in this environment: the screens were not exercised in a real browser (no browser could be installed
  here), so the grid fix, currency panel layout, print output and keyboard flow still need a manual pass.

## Known limitations

- The estimate tables are AG Grid instances. The print sheet and the section rollup are plain tables,
  so they print in full.
- The printed AFE is a fixed two-page portrait report (see *Print format* below): page 1 carries the
  metadata, the service schedule with remarks, the consumable and tangible lump sums, the total AFE
  amount and the submitted / reviewed / approved sign-off; page 2 lists every consumable and tangible
  line. Line detail is therefore not repeated on page 1, and the sign-off block names the actors recorded
  in the audit trail for each workflow move.
- Conversion rates are typed in by the user for each save. They are not fetched from a rate source, and the
  rate history is not kept beyond the saved estimate.
- Line-level amounts stay in the entered currency. Converted figures appear at estimate, section and AFE level.
- Overview totals add each AFE in its own standard currency. An AFE whose conversion is incomplete is counted separately.
- Daily cost tracking is not built. The estimate page states the agreed rule (see Daily cost below).
- Estimate line import is not provided. The AFE register supports XLSX and CSV import.

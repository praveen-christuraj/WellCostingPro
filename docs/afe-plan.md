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
- **Estimate workspace** (`/afe/estimate/:afeId`): line-item estimate, bulk estimate by section,
  section rollup, print.

## Data model

| Table | Purpose |
| --- | --- |
| `afes` | Header: rig, well, code (unique per workspace), name, type, remarks, status, soft-delete. |
| `afe_service_lines` | Service line: service, charging basis, scope (section, phase), currency, remarks. |
| `afe_service_rates` | Unit rate per charge category for Day Rate lines. |
| `afe_service_charges` | Explicit day quantities (days or hours) per day-based category. |
| `afe_service_section_rates` | Amount per (section, phase) for Per Section Rate lines. |
| `afe_consumable_lines` | Lump sum (Mud Chemicals, Cement Additives, Fuel) or drill bit line (bit, quantity, override). |
| `afe_tangible_lines` | Tangible line: item, quantity, override rate. |

No JSON columns. Migration `a9d4e2f7c138` follows `f3a7d0b9c214`. It upgrades, downgrades and
re-upgrades cleanly on SQLite, and `alembic check` reports the models and migration in sync.

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
- Money rounds to 2 decimals (half-up). Totals are per currency and are never converted.

## Workflow

- An AFE can be created only for an active well with a saved plan (at least one section) on an active rig.
  The plan does not have to be marked Configured. That sign-off is separate.
- Header edits, estimate edits and soft delete are allowed only in Draft.
- Transitions: submit (Draft → Submitted, needs a saved estimate with total > 0), review
  (Submitted → Review), approve (Review → Approval, remarks ≥ 3 characters), reopen (Submitted, Review or
  Approval → Draft, remarks ≥ 3 characters). Each transition checks its own permission.
- Preview prices live master data and the well plan, writes nothing, and reports every problem at once.
  The UI previews only valid lines, so one incomplete row does not block the rest.

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

## Open question: mud chemical daily consumption

The reference deducts daily consumption from the mud chemical lump sum. The user has not yet confirmed
whether that should apply here. Until it does, the lump sum is kept as a plain estimated amount, and the
UI says that daily consumption is not deducted automatically.

## Verification status

- Backend: `cd backend && ../.venv/bin/python -m pytest -q` passes (79 tests in the full suite, including
  17 AFE tests). Pyflakes is clean on the AFE modules.
- Migration: upgrade, downgrade and re-upgrade on a fresh SQLite database; `alembic check` clean.
- Frontend: `npm run build` passes (type check and Vite build).
- `make graph` runs cleanly and refreshes `.agent/memory/architecture.dot`.
- Not verified in this environment: the screens were not exercised in a real browser, so layout,
  print output and keyboard flow still need a manual pass.

## Known limitations

- The estimate tables are AG Grid instances. The print sheet and the section rollup are plain tables,
  so they print in full.
- Currency is never converted. A multi-currency AFE shows one total per currency.
- Estimate line import is not provided. The AFE register supports XLSX and CSV import.

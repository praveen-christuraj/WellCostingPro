# Daily Cost Management: scope and printing

## Implemented plan

1. **List-only register** (`/daily-cost`)
   - Keep top navigation, New daily sheet, Refresh, Deleted entries, well cost analysis and printing.
   - Keep well, AFE, status and date-range filters; quick/advanced grid filters; pagination; row/bulk actions; CSV/XLSX/PDF exports.
   - Remove workspace KPI cards, charts, cost-group budgets and recent activity.
   - Remove the misleading actual-to-date column calculated from the filtered register. Cumulative reconciliation remains on individual sheets and well analysis.
   - Stop requesting the workspace overview on this page; retain the existing API for compatibility.

2. **Scoped summaries**
   - Retain the existing sheet-specific daily totals and locked AFE comparison.
   - Well analysis requires one explicitly selected well; never show a multi-well summary or silently pick the first well.
   - Reject mixed AFE standard currencies in combined well analysis instead of returning a summed amount with no currency label. Individual sheets and the separated costing report remain available.
   - Preserve existing analysis capabilities. New analysis configuration, metrics and comparison policies remain open until the user supplies requirements.

3. **Print saved records**
   - **Print daily sheet** is available on a sheet to users with `daily-cost:export`. Save or discard unsaved changes first. The print reads the saved record again.
   - **Print well costing sheet** is available from the register, individual sheet and well analysis. Choose one well, inception-to-today or an inclusive date range, and whether to include drafts.
   - Inception means the first recorded cost for the well, not an assumed spud date. Future-dated sheets are excluded from inception-to-today.
   - The well report excludes soft-deleted sheets, includes empty saved sheets, and does not truncate to a grid page or inherit register search filters.
   - Period totals are separated by AFE and standard currency. There is no cross-well, cross-AFE or mixed-currency grand total in print.
   - Each full sheet prints header/shift details, daily totals, services, consumables, tangibles, other expenses, rate/FX/override trace, activity/sub-activity/section/phase/party details, remarks, warnings and AFE reconciliation.
   - AFE actual-to-date and balance are explicitly labelled as cumulative through the sheet date; they may include sheets outside the requested report period and include drafts under the existing reconciliation policy. They are not presented as submitted-only period totals.
   - Tables print all rows using the existing AFE print layout, with repeated table headers. Choose **Save as PDF** in the browser's print dialog for a complete PDF report. Existing grid PDF exports remain unchanged.
   - Print preparation is export-audited with sheet/well scope, period and draft selection. The report API requires both `daily-cost:read` and `daily-cost:export`, and checks the authenticated workspace.

4. **Other expenses (Lost In Hole, hole problems and similar charges)**
   - Unexpected costs that have no AFE allowance — tools lost in hole, hole problems, fishing and recovery, side track, equipment damage, third-party claims, penalties — are captured in their own cost group next to Services, Consumables and Tangibles, in the table `daily_cost_other_expense_lines`.
   - Each line keeps the normal operational scope of a daily cost line: rig-scoped well, AFE, Phase, Activity, Sub-Activity and Hole Section, plus the responsible vendor or party. Classification (Planned/UPA/NPT) stays derived from the Master Data Activity; it is never typed.
   - The expense type comes from a fixed picklist (LIH, Hole Problem, Fishing & Recovery, Side Track, Equipment Damage, Third Party Claim, Penalty / Fine, Miscellaneous). It is deliberately not a master-data register: the deduction rule depends on the type, so free-text categories would make the AFE position untrustworthy. Optional free text belongs in `expense_description`.
   - **Remarks are mandatory** (at least three non-blank characters) because the remark is the only narrative that explains the charge. The rule is enforced in the API schema and as a database `CHECK` constraint, so a non-API writer cannot store an unexplained deduction.
   - The amount is `quantity × unit rate` in the entered currency, converted with the locked AFE exchange rate into the AFE standard currency — the same conversion path as every other line. A daily rate override is rejected on these lines: the entered unit rate is the price and is stored as `captured_rate` with `rate_source = other_expense`.
   - Other expenses are **included in the day's total cost** and **deducted from the locked AFE total**. Reconciliation is therefore `Total AFE − (Services + Consumables + Tangibles) − Other Expenses = AFE remaining`; `tracked_actual_to_date` and `other_expenses_to_date` keep both halves visible, `planned` for the group is always 0.00, and every sheet with a deduction carries the `other-expenses-deducted` warning plus its own audit row (`action = other_expense`) next to the save.
   - Register, well analysis, overview, deleted entries, CSV/XLSX import (`Line Type = Other`) and the printable sheet all expose the group; the printed sheet gives it section 6 and a column in the AFE register.
   - They follow the existing sheet rules exactly: draft-only editing, submit/reopen freeze, soft delete then purge, tenant scoping on every query and permission gating on every action (`daily-cost:update` to save, `daily-cost:read` to view).

## Awaiting the reference daily sheet

No reference sheet was attached to the request implemented in this increment. Existing capture fields and pricing/approval/import/delete functionality have been retained; exact reference-template parity is **not claimed**.

When the reference is supplied:

1. Inventory every header, operational section, cost row, subtotal, note and sign-off field in its printed order.
2. Map each field to existing typed columns, recording gaps explicitly.
3. Confirm units, required fields, repeatable rows and calculation rules with the user where the template is ambiguous.
4. Add only the necessary typed columns/related tables and backward-compatible migrations. Do not persist a JSON document or overwrite historical rate/budget snapshots.
5. Extend data entry, validation, import/export and this complete print layout section by section.
6. Add migration, authorization, pricing and print-parity regression tests.

## Verification

- `make test`: backend regression suite, including report completeness, date boundaries, empty sheets, submitted-only filtering, soft deletion, tenant/well isolation, read/export permissions, scoped audit and mixed-currency safety.
- `make build`: frontend TypeScript and production bundle.
- `make ui-check`: shared light/dark theme, accessible dialog and error conventions.
- `make daily-cost-check`: real print DOM checks for full sections (other-expense section included, with mandatory-remark labelling), 120 unpaginated service rows, separate AFE/currency totals, escaped remarks, synchronous portal mounting and after-print cleanup; static register-content checks.
- `make test` additionally covers: separate totals and their effect on the AFE balance, mandatory remarks and other line validation, FX defaults, import aliases and row errors, well/overview/register/print propagation, tenant and permission gating, submit freeze, soft delete versus purge, and the database `CHECK` constraints on the new table.
- `make graph`: regenerate the import graph.

Items 1 to 3 above needed no migration. The Other-expenses increment (item 4) adds migration `7c1f4a8d92b6`: the `other_expenses_total` roll-up column on `daily_cost_entries` and the new column-wise `daily_cost_other_expense_lines` table (upgrade and downgrade verified, `alembic check` clean). No dependency change, authorization relaxation or change to locked rate/AFE snapshots is involved: the AFE estimate and the locked price book stay untouched. Browser print pagination and physical printer output still warrant a manual check with the supplied reference sheet.

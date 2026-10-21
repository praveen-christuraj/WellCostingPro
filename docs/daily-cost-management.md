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
   - Daily and whole-well reports print in **A4 landscape with 4 mm margins**. Page 1 follows the supplied model-report information architecture: report/well/rig identity; a user-editable milestone label (default **Spud date & time**) and report timing; section planned/current depth; Time Position (Planned, Actual from Spud, Actual against Planned Activities, NPT days and UPA days); service-wise and consumable-wise AFE versus cumulative actual; tangible position; overall AFE summary; section mud actual/reconciled cost; a mud matrix; and NPT/UPA cost, duration, responsible party and remarks.
   - The report title names the well scope it costs, from the AFE behind the sheets: **Well Cost Report - Drilling**, **Daily Cost Report - Completions**, or **… - Drilling & Completions** when the report covers both scopes, followed by the well name (for example `Daily Cost Report - Drilling · WELL-01`).
   - Both daily-sheet and whole-well print dialogs ask for an optional **Lead / Lag** selection and decimal days (up to ten decimal places). The title ends with `(LEAD: <value> days)` or `(LAG: <value> days)`. Choosing neither prints the explicit fallback `(LEAD/LAG: 0 days)`.
   - The page-1 **Services cost** table prints the cumulative actual by activity classification between the AFE amount and the total actual: **Planned**, **UPA** and **NPT** under a grouped "Actual cost by activity" heading, then **Total actual**, **Balance** and **Used**. The three classification amounts always add up to the total actual, in the rows and in the group total. Only this table is compacted (smaller type, tighter padding and eight narrower columns) to fit the extra columns; the consumables, tangible, mud and incident tables keep their existing layouts.
   - Print presentation uses names only for rigs, wells, AFEs and all named operational/cost entities; service, consumable and tangible codes are not repeated. On the page-1 summary, services follow their hidden service-code order, while consumables print only category totals: Drill Bits is one cumulative row and the Mud Chemicals/Cement Additives labels omit "allowance". Every printed decimal is rounded and displayed to two places. This is presentation-only and does not reduce the ten-decimal stored precision.
   - The mud matrix follows the model report's upper-right layout: section and mud type are column headers; Opening Stock, Receipt, Additions, Total Mud, Losses, Closing Stock, Meterage (current depth), Cost/BBL and Reconciled Cost are rows populated from material-balance, reconciliation and daily-depth records.
   - **Consumption / Losses cumulative** is also transposed as a matrix: section and mud type are columns. Surface-loss rows are Verti-G/Mud on Cuttings, Centrifuge, By-Pass, Evaporation and Trips, followed by Surface losses total. Other-loss rows are Mud Cleaner, Formation/Seepage, Pit Cleaning/Dump, Left-In-Hole and Others, followed by Other losses total and Total losses. Historical Shakers and the former separate other-deduction rows roll into Others, so Surface losses + Other losses always reconciles to every stock deduction.
   - Page 2 onward is cumulative rather than one breakdown per day: every used service is listed in hidden service-code order, consumables remain exactly four category totals (Mud Chemicals, Cement Additives, Fuel and Drill Bits), and used tangible items print item-wise with their cumulative prices. Daily source records and precision remain unchanged.
   - AFE actual-to-date and balance are explicitly labelled as cumulative through the sheet date; they may include sheets outside the requested report period and include drafts under the existing reconciliation policy. They are not presented as submitted-only period totals.
   - Actual days start at the entered spud date and time. Until progress is completed, they end at the close of the last cost-sheet date included for that scope, never the date the report is printed; once a progress-completed date and time exists, its exact timestamp replaces the cost-sheet end date and freezes the count.
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

5. **Consumption and losses report** (`/reports/consumption-losses`)
   - Uses the same normalized Mud Cost entries and loss taxonomy as the printed matrix. No duplicate report store or JSON snapshot is created.
   - Supports date-wise, month-wise, selected required date range and inception views, with rig, well, section, drilling/completion scope, mud type and from/to filters. Aggregate rows drill back to their daily dates.
   - The on-screen matrix keeps sections and mud types as columns and the ten loss measures plus Surface, Other and grand totals as rows. The detail grid retains quick/advanced/date filtering, 20/50/100 pagination and CSV/XLSX/PDF exports.
   - Read access uses `daily-cost:read`; exports use `daily-cost:export` and are audited as `module="consumption_losses"`. Tenant and rig/well/section boundaries are validated by the API.

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
- `make daily-cost-check`: real print DOM checks for bulk depth/quantity/unit controls, the editable milestone label, Lead/Lag decimal validation and title suffix/fallback, Actual against Planned Activities, the transposed mud and Consumption/Losses matrices, the service-wise Planned/UPA/NPT actual columns (rows and group total, other tables unchanged), scope-aware report titles, hidden-code service ordering, four cumulative consumable categories, item-wise tangible cumulative prices, cumulative-only continuation pages, two-decimal measurements, landscape/margins, escaping, synchronous portal mounting and cleanup; static register-content checks.
- `make test` additionally covers: separate totals and their effect on the AFE balance, mandatory remarks and other line validation, FX defaults, import aliases and row errors, well/overview/register/print propagation, tenant and permission gating, submit freeze, soft delete versus purge, and the database `CHECK` constraints on the new table.
- `make graph`: regenerate the import graph.

Items 1 to 3 above needed no migration. The Other-expenses increment (item 4) adds migration `7c1f4a8d92b6`: the `other_expenses_total` roll-up column on `daily_cost_entries` and the new column-wise `daily_cost_other_expense_lines` table (upgrade and downgrade verified, `alembic check` clean). No dependency change, authorization relaxation or change to locked rate/AFE snapshots is involved: the AFE estimate and the locked price book stay untouched. Browser print pagination and physical printer output still warrant a manual check with the supplied reference sheet.

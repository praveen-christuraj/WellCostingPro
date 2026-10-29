# Daily service entry and workspace-global costing sets

## Entering the day's services

1. Open a draft Daily Cost sheet and choose **Add service**, or select a service set with **Add from set**. Both open the same editor; applying a service set no longer immediately adds guessed scope/quantity lines to the sheet.
2. Choose the service once. The default rate is from the current saved AFE. Existing saved lines keep their historical rate until deliberately changed with **Matched AFE rate**.
3. For time-based charges, use **Add activity allocation** for each activity/sub-activity, section, phase and optional depth. For example, enter Planned 10h, NPT 11h and UPA 3h. Classification comes from Master Data Activity; NPT/UPA responsibility comes from the selected well sub activity. Partial days are permitted. Only an explicit `hours` allocation is authoritative operational time; a `days` quantity remains a billing quantity and is never silently treated as elapsed time. The backend treats the date + classification + activity + sub-activity + section + phase hour allocation as the operational time record, counts repeated service/charge lines for that allocation once, and requires the whole-well Planned + NPT + UPA hour total to remain within 24 for the daily sheet.

The dedicated NPT/UPA report shows two deliberately separate measures. **Affected cost dates** count distinct dates containing the classification and can overlap between NPT and UPA. **Allocated duration** converts the deduplicated explicit service allocation hours to days (`hours / 24`); it is not derived from affected-date counts, billing-day quantities or cost-line counts. Portfolio values sum the per-well measures. Legacy sheets that still exceed 24 deduplicated hours are flagged in the report and must be corrected before their duration is treated as MIS-ready.
4. Check any additional configured AFE charge categories below the service's rate. Operating/time-based categories use the allocation hours. Mobilization, demobilization and fixed charges are taken in full once, against the first allocation. Reorder your entry by entering the desired one-time scope first if necessary.
5. Per-service and per-section charges do not require working hours. New entries default to a quantity of one (existing saved section/service quantities are retained) and one activity/scope (the first allocation, if allocations are supplied). With no allocations, common criteria remain available for the original single-activity workflow.
6. Save the dialog, review the sheet's live preview, and save the sheet. The dialog does not commit the daily costs itself.

A service is selected once in the entry window, but its allocations/categories are deliberately persisted as separate ordinary **ledger rows**. This preserves existing activity/section/phase/depth, classification, FX, AFE comparison, print and report calculations; no JSON storage or secondary cost engine is introduced. Rows remain individually editable after saving. To change several allocations together, select their rows and use **Assign scope**.

Manual cost-breakdown totals cannot be repeated across several timed allocations: remove those manual amounts and use the rate-based split, or edit the individual ledger amounts deliberately. This prevents multiplying a manually entered total by the number of activities.

## Bulk allocation and historical rate changes

The bulk service scope dialog includes the same allocation editor. All selected time-based service charges receive the entered allocation; one-time and non-time-based charges remain whole.

**Use current AFE service rates and charging basis** is an explicit opt-in bulk action. It replaces manual rate overrides with the selected current AFE rate. This permits upgrading old per-section entries to day-rate entries, including on older draft/reopened sheets, without automatically repricing history. Approved/submitted sheets still require the existing reopen workflow and permissions.

Draft sheet loading calls the permission-protected `POST /daily-cost/entries/{id}/refresh-service-rates`. This appends new rate versions and marks superseded versions non-current. The original budget, catalogue price book, saved costs and old rate versions are retained. If the current AFE cannot be loaded, the old sheet still opens with a warning rather than becoming inaccessible. The refresh is idempotent and audited when it changes versions.

AFE saves replace source line IDs. Revised service rates reconnect to an original locked service allowance only where the service/scope mapping is unambiguous. An ambiguous/new allowance does not rewrite the locked budget. Current FX not present in the original baseline still uses the existing daily FX-entry validation.

## Create a missing well sub activity without leaving the entry

Users with `rig-well:create` see **Create well sub activity here**. Rig, well and configuration scope are fixed from the current sheet; the user selects an activity and enters the code, name, description and responsibility. Creation uses the existing tenant-scoped, audited Rig & Well API. The new sub activity is immediately selectable without clearing the cost dialog's typed values. Standard unsaved-changes protection applies to both dialogs.

## Global sets

Service, tangible and consumable sets (including mud chemicals, cement additives, fuel and drill bits) have a **Global — share with everyone in this workspace** checkbox. Global never means cross-tenant. Anyone with `costing-sets:read` in the same workspace can discover and use the set in the existing AFE and daily entry pickers. The creator alone can edit/delete/unshare it, subject to the existing write permissions. Other users' private sets stay private. Sets contain item references, not shared prices.

## Deployment and verification

Run the additive migration before deploying the application:

```sh
cd backend
alembic upgrade head
```

Revision `c7a1d9e4b205` adds `daily_cost_baseline_service_rates.is_current` (true for old rates) and `user_costing_sets.is_global` (false for old sets). It neither updates actual amounts nor removes data.

Regression coverage:

- Backend: section-rate history retained, AFE changed to day rate, idempotent version refresh, explicit old-sheet edit, 10/11/3 allocation plus full mobilization, original allowance reconciliation, 24-hour rejection, tenant isolation, global set visibility/unsharing/owner-only mutations.
- `make daily-cost-check`: real dialog submit with activity allocation and an additional charge; bulk historical-to-current-rate upgrade; allocation depths and NPT/UPA responsibility; whole one-time/non-time charges; cross-scope rejection and manual-total split protection; existing printing/selector checks.
- `make ui-check`: shared light/dark design and dialog safeguards.

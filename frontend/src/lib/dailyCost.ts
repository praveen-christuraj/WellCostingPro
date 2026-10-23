export type DailyCostStatus = 'draft' | 'submitted'
export type CostClassification = 'Planned' | 'UPA' | 'NPT'
export type ChargingBasis = 'Day Rate' | 'Per Service Rate' | 'Per Section Rate'
export type ChargeCategory =
  | 'Mobilization' | 'Demobilization' | 'Operation' | 'Standby'
  | 'Personnel-Operation' | 'Personnel-Standby' | 'Fixed Charge' | 'Others'
export type ConsumableCategory = 'Mud Chemicals' | 'Cement Additives' | 'Fuel' | 'Drill Bits'
/** Unexpected charges with no AFE allowance (Lost In Hole, hole problems, claims). */
export type OtherExpenseType =
  | 'LIH' | 'HOLE_PROBLEM' | 'FISHING' | 'SIDE_TRACK' | 'EQUIPMENT_DAMAGE'
  | 'THIRD_PARTY_CLAIM' | 'PENALTY' | 'MISC'
export type OtherExpenseUnit = 'unit' | 'days' | 'hours'
/** The four cost groups of a daily sheet. Only the last one has no AFE budget. */
export type DailyCostGroup = 'Services' | 'Consumables' | 'Tangibles' | 'Other Expenses'
export const DAILY_COST_GROUPS: DailyCostGroup[] = ['Services', 'Consumables', 'Tangibles', 'Other Expenses']
export type ConsumableKind = 'mud_chemical' | 'cement_additive' | 'fuel' | 'drill_bit'
export type DailyQuantityUnit = 'days' | 'hours' | 'service' | 'section' | 'unit'

export type DailyCostRigOption = { id: string; rig_code: string; rig_name: string; display_name: string }
export type DailyCostPhaseOption = { phase_id: string; phase_code: string; phase_name: string; days: string }
export type DailyCostSectionOption = {
  hole_section_id: string; section_code: string; section_name: string
  from_depth: string; to_depth: string; total_days: string; phases: DailyCostPhaseOption[]
}
export type DailyCostWellOption = {
  id: string; rig_id: string; well_code: string; well_name: string; display_name: string
  status: string; config_status: string; completion_status: string; completion_config_status: string
  drilling_is_deleted?: boolean; completion_is_deleted?: boolean
  sections: DailyCostSectionOption[]
}
export type WellScopeKey = 'drilling' | 'completion'
export type DailyCostAfeOption = {
  id: string; well_id: string; afe_code: string; afe_name: string; afe_type: string
  status: string; configuration_scope?: WellScopeKey
  standard_currency: string; total_cost: string; estimate_saved_at: string; display_name: string
}
export type DailyCostActivityOption = { id: string; activity_code: string; activity_name: string; display_name: string }
export type DailyCostSubActivityOption = {
  id: string; well_id: string; scope?: WellScopeKey; activity_id: string; sub_activity_code: string
  sub_activity_name: string; responsible_party: string; display_name: string
}
export type DailyCostServiceOption = {
  id: string; service_code: string; service_name: string; service_category: string
  service_group: string
  provider_type: string; vendor_id: string | null; vendor_code: string; vendor_name: string; display_name: string
}
export type DailyCostCatalogueOption = {
  id: string; item_kind: ConsumableKind | 'tangible'; category: ConsumableCategory | 'Tangibles'
  item_code: string; item_name: string; description: string; uom: string; captured_rate: string
  currency: string; revision_number: number; effective_date: string | null; display_name: string
}
export type DailyCostVendorOption = {
  id: string; vendor_code: string; vendor_name: string; vendor_type: string; status: string; display_name: string
}
export type DailyCostOtherExpenseTypeOption = { code: OtherExpenseType; label: string }
export type DailyCostReference = {
  rigs: DailyCostRigOption[]; wells: DailyCostWellOption[]; afes: DailyCostAfeOption[]
  activities: DailyCostActivityOption[]; sub_activities: DailyCostSubActivityOption[]
  services: DailyCostServiceOption[]; catalogue_items: DailyCostCatalogueOption[]
  vendors: DailyCostVendorOption[]; currencies: string[]; charge_categories: ChargeCategory[]
  charge_bases: ChargingBasis[]; quantity_units: DailyQuantityUnit[]; classifications: CostClassification[]
  consumable_categories: ConsumableCategory[]
  other_expense_types: DailyCostOtherExpenseTypeOption[]
}

export type DailyCostRateOption = {
  id: string; service_id: string; source_afe_line_id: string; service_code: string; service_name: string
  charging_basis: ChargingBasis; rate_kind: 'day_rate' | 'per_service' | 'per_section'; charge_category: string
  hole_section_id: string | null; section_label: string; phase_id: string | null; phase_label: string
  unit_rate: string; currency: string; display_name: string
}
export type DailyCostBudgetLine = {
  id: string; cost_group: 'Services' | 'Consumables' | 'Tangibles'
  budget_kind: 'service' | 'consumable_category' | 'drill_bit' | 'tangible' | string
  item_key: string; item_code: string; item_name: string; service_group?: string; source_afe_line_id: string
  section_id: string | null; phase_id: string | null; quantity: string; unit_rate: string
  native_amount: string; currency: string; exchange_rate: string; planned_amount: string; uom: string
}
export type DailyCostBaseline = {
  id: string; rate_baseline_id: string; afe_id: string; afe_code: string; afe_name: string
  standard_currency: string; total_amount: string; locked_at: string; locked_by: string
  afe_estimate_saved_at: string | null; catalogue_rates: DailyCostCatalogueOption[]
  service_rates: DailyCostRateOption[]; budget_lines: DailyCostBudgetLine[]
  sections: DailyCostSectionOption[]; exchange_rates: Record<string, string>
}

import type { DepthUnit } from './units'

export type DailyCostSectionDepth = {
  hole_section_id: string | null
  section_code: string
  section_name: string
  actual_depth: string
  depth_unit: 'm'
  entered_depth: string | null
  entered_unit: DepthUnit
  daily_cost_code: string
}

export type DailyCostEntry = {
  id: string; daily_cost_code: string; rig_id: string; rig_code: string; rig_name: string
  well_id: string; well_code: string; well_name: string; afe_id: string; afe_code: string; afe_name: string
  afe_status: string; cost_date: string; standard_currency: string; remarks: string; status: DailyCostStatus
  submitted_at: string | null; submitted_by: string; status_remarks: string
  services_count: number; consumables_count: number; tangibles_count: number; other_expenses_count: number
  services_total: string; consumables_total: string; tangibles_total: string; other_expenses_total: string
  total_cost: string
  upa_total: string; npt_total: string
  usd_exchange_rate?: string
  services_total_usd?: string; consumables_total_usd?: string; tangibles_total_usd?: string; other_expenses_total_usd?: string
  total_cost_usd?: string; upa_total_usd?: string; npt_total_usd?: string
  actual_depth?: string | null
  depth_unit?: 'm'
  section_depths?: DailyCostSectionDepth[]
  rate_baseline_locked_at: string; budget_baseline_locked_at: string
  warning_count: number; is_deleted: boolean; deleted_at: string | null
  created_by: string; updated_by: string; created_at: string; updated_at: string
}

export type DailyCostLineBase = {
  id?: string | null; activity_id: string; hole_section_id: string | null; phase_id: string | null
  sub_activity_id: string | null; vendor_id: string | null; party_name: string
  quantity: string; currency: string
  exchange_rate?: string | null
  actual_depth?: string | null
  actual_depth_unit?: DepthUnit
  depth_seq?: number | null
  override_rate: string | null; override_reason: string; remarks: string
}
export type ServiceCostItem = { description: string; amount: string }
export type DailyCostServiceInput = DailyCostLineBase & {
  cost_items?: ServiceCostItem[]
  service_id: string; baseline_service_rate_id: string | null; charging_basis: ChargingBasis | null
  charge_category: ChargeCategory; quantity_unit: DailyQuantityUnit
}
export type DailyCostConsumableInput = DailyCostLineBase & {
  category: ConsumableCategory; item_kind: ConsumableKind; item_id: string
}
export type DailyCostTangibleInput = DailyCostLineBase & { tangible_id: string }
export type DailyCostOtherExpenseInput = DailyCostLineBase & {
  expense_type: OtherExpenseType; expense_description: string
  quantity_unit: OtherExpenseUnit; unit_rate: string
}
export type DailyCostSavePayload = {
  remarks: string
  usd_exchange_rate?: string | null
  services: DailyCostServiceInput[]
  consumables: DailyCostConsumableInput[]; tangibles: DailyCostTangibleInput[]
  other_expenses: DailyCostOtherExpenseInput[]
}

export type DailyCostLineOutput = DailyCostLineBase & {
  id: string; activity_code: string; activity_name: string; section_code: string; section_name: string
  phase_code: string; phase_name: string; sub_activity_code: string; sub_activity_name: string
  sub_activity_party: string; vendor_code: string; vendor_name: string; quantity_unit: DailyQuantityUnit
  /** Derived from the Master Data Activity; not entered on the line. */
  classification: CostClassification
  captured_rate: string; effective_rate: string; exchange_rate: string; amount: string; standard_amount: string
  usd_exchange_rate?: string; usd_amount?: string
  actual_depth?: string | null; actual_depth_entered?: string | null; actual_depth_unit?: DepthUnit; depth_seq?: number
  rate_source: string; rate_revision_number: number | null; rate_effective_date: string | null
  baseline_budget_line_id: string | null; budget_key: string; budget_name: string
}
export type DailyCostServiceLine = DailyCostLineOutput & {
  cost_items?: ServiceCostItem[]
  service_id: string; service_code: string; service_name: string; service_group?: string
  charging_basis: ChargingBasis
  charge_category: ChargeCategory; baseline_service_rate_id: string | null
}
export type DailyCostConsumableLine = DailyCostLineOutput & {
  category: ConsumableCategory; item_kind: ConsumableKind; item_id: string
  item_code: string; item_name: string; uom: string; catalogue_rate_snapshot_id: string | null
}
export type DailyCostTangibleLine = DailyCostLineOutput & {
  tangible_id: string; tangible_code: string; tangible_name: string; uom: string
  catalogue_rate_snapshot_id: string | null
}
export type DailyCostOtherExpenseLine = DailyCostLineOutput & {
  expense_type: OtherExpenseType; expense_type_label: string; expense_description: string
}
/** Every priced line of a sheet, whichever cost group it belongs to. */
export type AnyDailyCostLine =
  | DailyCostServiceLine | DailyCostConsumableLine | DailyCostTangibleLine | DailyCostOtherExpenseLine

export type DailyCostComparisonGroup = {
  cost_group: DailyCostGroup; planned: string; actual_to_date: string; balance: string
  /** `actual_to_date` split by the lines' activity classification; the three add up to it. */
  actual_planned?: string; actual_upa?: string; actual_npt?: string
}
export type DailyCostComparisonLine = {
  budget_key: string; cost_group: DailyCostGroup; budget_kind: string
  item_code: string; item_name: string; service_group?: string
  planned: string; actual_to_date: string; balance: string; is_planned: boolean
  /** Cumulative actual under Planned / UPA / NPT; `actual_planned` is the default case. */
  actual_planned?: string; actual_upa?: string; actual_npt?: string
}
/**
 * `actual_to_date` covers all four groups, so `balance` is the AFE total less the
 * tracked actuals and less the other expenses. The two split fields keep the
 * separately accounted deduction visible.
 */
export type DailyCostComparison = {
  effective_on: string; currency: string; planned_total: string; actual_to_date: string
  tracked_actual_to_date: string; other_expenses_to_date: string; balance: string
  /** LIH Cost Register cost filed against this AFE, added to actual and deducted from the AFE. */
  lih_cost_to_date?: string; actual_including_lih?: string; afe_available?: string
  over_budget: boolean; includes_draft_entries: boolean; upa_to_date: string; npt_to_date: string
  groups: DailyCostComparisonGroup[]; budget_lines: DailyCostComparisonLine[]
  // Revised AFE amount when an approved SOW adjustment exists. planned_total
  // always stays the locked (original) AFE total.
  adjusted_planned_total: string | null; adjusted_balance: string | null; has_adjustment: boolean
}
export type DailyCostWarning = { code: string; severity: 'info' | 'warning' | 'error'; message: string }
/**
 * One configuration scope's register milestones. Actual days count from the
 * Well Spud Date & Time (never from the first sheet) to the end of the report
 * date, and stop at the Progress Completed Date & Time once it is entered.
 */
export type WellProgressScope = {
  scope: 'drilling' | 'completion'; scope_label: string; progress_label: string
  spud_at: string | null; progress_completed_at: string | null; is_completed: boolean
  planned_days: string; actual_days: string | null; days_variance: string | null
  as_of_date: string | null
}
export type WellProgressReport = {
  well_id: string; well_code: string; well_name: string; scopes: WellProgressScope[]
}
export type DailyCostDay = {
  entry: DailyCostEntry; services: DailyCostServiceLine[]; consumables: DailyCostConsumableLine[]
  tangibles: DailyCostTangibleLine[]; other_expenses: DailyCostOtherExpenseLine[]
  comparison: DailyCostComparison; warnings: DailyCostWarning[]
  progress: WellProgressScope | null
}
export type DailyCostPreview = {
  services: DailyCostServiceLine[]; consumables: DailyCostConsumableLine[]; tangibles: DailyCostTangibleLine[]
  other_expenses: DailyCostOtherExpenseLine[]
  services_total: string; consumables_total: string; tangibles_total: string; other_expenses_total: string
  total_cost: string; upa_total: string; npt_total: string
  total_cost_usd?: string; actual_depth?: string | null; depth_unit?: 'm'; section_depths?: DailyCostSectionDepth[]
  warnings: DailyCostWarning[]
}
export type DailyCostOverview = {
  active_entries: number; deleted_entries: number; submitted_entries: number; draft_entries: number
  wells_tracked: number; active_baselines: number; over_budget_afes: number
  total_planned_by_currency: Record<string, string>; actual_to_date_by_currency: Record<string, string>
  remaining_by_currency: Record<string, string>
  lih_cost_by_currency?: Record<string, string>; lih_entries?: number; lih_lines?: number
  groups: { currency: string; cost_group: DailyCostGroup; planned: string; actual: string; balance: string }[]
  trend: { cost_date: string; currency: string; actual: string; upa: string; npt: string }[]
  recent_activity: { id: string; action: string; entity_type: string; entity_label: string; summary: string; created_at: string }[]
}
export type DailyCostImportResult = { imported_count: number; error_count: number; errors: string[]; success: boolean }

export const DAILY_COST_STATUSES: Record<DailyCostStatus, string> = { draft: 'Draft', submitted: 'Submitted' }

/**
 * Classification (Planned / UPA / NPT) is not entered on daily cost lines: the
 * Master Data Activity already carries that meaning. Mirrors the server rule in
 * `app.services.daily_cost.classify_activity`.
 */
export function deriveClassification(
  activity: Pick<DailyCostActivityOption, 'activity_code' | 'activity_name'> | null | undefined,
): CostClassification {
  const text = `${activity?.activity_code ?? ''} ${activity?.activity_name ?? ''}`.toLowerCase()
  if (/\bnpt\b/.test(text) || /non[ -]?productive/.test(text)) return 'NPT'
  if (/\bupa\b/.test(text) || text.includes('unplanned')) return 'UPA'
  return 'Planned'
}
export const DAILY_CHARGE_CATEGORIES: ChargeCategory[] = [
  'Mobilization', 'Demobilization', 'Operation', 'Standby', 'Personnel-Operation', 'Personnel-Standby', 'Fixed Charge', 'Others',
]
export const DAILY_CHARGING_BASES: ChargingBasis[] = ['Day Rate', 'Per Service Rate', 'Per Section Rate']
export const DAILY_CONSUMABLE_CATEGORIES: ConsumableCategory[] = ['Mud Chemicals', 'Cement Additives', 'Fuel', 'Drill Bits']
/**
 * Types an operator can book an unexpected charge against. The API snapshots the
 * label on every line, so history keeps the wording that was in force when the
 * cost was recorded; this list only seeds the picker before a reference loads.
 */
export const OTHER_EXPENSE_TYPES: DailyCostOtherExpenseTypeOption[] = [
  { code: 'LIH', label: 'Lost In Hole (LIH)' },
  { code: 'HOLE_PROBLEM', label: 'Hole Problem' },
  { code: 'FISHING', label: 'Fishing & Recovery' },
  { code: 'SIDE_TRACK', label: 'Side Track & Re-entry' },
  { code: 'EQUIPMENT_DAMAGE', label: 'Equipment Damage / Loss' },
  { code: 'THIRD_PARTY_CLAIM', label: 'Third Party Claim' },
  { code: 'PENALTY', label: 'Penalty / Fine' },
  { code: 'MISC', label: 'Miscellaneous Other Cost' },
]
export const OTHER_EXPENSE_MIN_REMARKS = 3

export function otherExpenseLabel(code: string, options: DailyCostOtherExpenseTypeOption[] = OTHER_EXPENSE_TYPES): string {
  return options.find(option => option.code === code)?.label ?? code
}
export const DAILY_ONE_TIME_CATEGORIES: ChargeCategory[] = ['Mobilization', 'Demobilization', 'Fixed Charge']

export function dailyMoney(value: string | number | null | undefined, currency = ''): string {
  const amount = Number(value ?? 0)
  if (!Number.isFinite(amount)) return '—'
  const formatted = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount)
  return currency ? `${currency} ${formatted}` : formatted
}

export function localToday(): string {
  const now = new Date()
  const offset = now.getTimezoneOffset()
  return new Date(now.getTime() - offset * 60_000).toISOString().slice(0, 10)
}

export function displayDate(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00`)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Title wording for a scope: "Drilling", "Completions", or both scopes together. */
export function scopeTitleLabel(scopes: Iterable<string | null | undefined>): string {
  const found = new Set([...scopes].filter(scope => scope === 'drilling' || scope === 'completion'))
  const labels = (['drilling', 'completion'] as const)
    .filter(scope => found.has(scope))
    .map(scope => scope === 'completion' ? 'Completions' : 'Drilling')
  return labels.join(' & ')
}

/**
 * The printed cost report is titled with the well scope it costs, e.g.
 * "Well Cost Report - Drilling · WELL-01". The scope comes from the AFE(s)
 * behind the sheets; the well name stays the descriptive part of the title.
 */
export function costReportTitle(
  kind: 'daily' | 'well', scopes: Iterable<string | null | undefined>, wellName = '',
): string {
  const base = kind === 'daily' ? 'Daily Cost Report' : 'Well Cost Report'
  const scope = scopeTitleLabel(scopes)
  const title = scope ? `${base} - ${scope}` : base
  return wellName.trim() ? `${title} · ${wellName.trim()}` : title
}

export function saveFromDay(day: DailyCostDay): DailyCostSavePayload {
  const lineFxAndDepth = (line: DailyCostLineOutput) => ({
    exchange_rate: line.currency && line.currency.toUpperCase() !== 'USD' && line.usd_exchange_rate
      ? line.usd_exchange_rate
      : null,
    actual_depth: line.actual_depth_entered ?? line.actual_depth ?? null,
    actual_depth_unit: line.actual_depth_unit ?? 'm',
  })
  return {
    remarks: day.entry.remarks,
    usd_exchange_rate: day.entry.standard_currency && day.entry.standard_currency.toUpperCase() !== 'USD'
      ? (day.entry.usd_exchange_rate ?? null)
      : null,
    services: day.services.map(line => ({
      id: line.id, activity_id: line.activity_id, hole_section_id: line.hole_section_id,
      phase_id: line.phase_id, sub_activity_id: line.sub_activity_id,
      vendor_id: line.vendor_id, party_name: line.party_name, quantity: line.quantity,
      currency: line.currency, ...lineFxAndDepth(line), override_rate: line.override_rate, override_reason: line.override_reason,
      cost_items: line.cost_items ?? [], remarks: line.remarks, service_id: line.service_id, baseline_service_rate_id: line.baseline_service_rate_id,
      charging_basis: line.charging_basis, charge_category: line.charge_category, quantity_unit: line.quantity_unit,
    })),
    consumables: day.consumables.map(line => ({
      id: line.id, activity_id: line.activity_id, hole_section_id: line.hole_section_id,
      phase_id: line.phase_id, sub_activity_id: line.sub_activity_id,
      vendor_id: line.vendor_id, party_name: line.party_name, quantity: line.quantity,
      currency: line.currency, ...lineFxAndDepth(line), override_rate: line.override_rate, override_reason: line.override_reason,
      remarks: line.remarks, category: line.category, item_kind: line.item_kind, item_id: line.item_id,
    })),
    tangibles: day.tangibles.map(line => ({
      id: line.id, activity_id: line.activity_id, hole_section_id: line.hole_section_id,
      phase_id: line.phase_id, sub_activity_id: line.sub_activity_id,
      vendor_id: line.vendor_id, party_name: line.party_name, quantity: line.quantity,
      currency: line.currency, ...lineFxAndDepth(line), override_rate: line.override_rate, override_reason: line.override_reason,
      remarks: line.remarks, tangible_id: line.tangible_id,
    })),
    other_expenses: day.other_expenses.map(line => ({
      id: line.id, activity_id: line.activity_id, hole_section_id: line.hole_section_id,
      phase_id: line.phase_id, sub_activity_id: line.sub_activity_id,
      vendor_id: line.vendor_id, party_name: line.party_name, quantity: line.quantity,
      currency: line.currency, ...lineFxAndDepth(line), override_rate: null, override_reason: '',
      remarks: line.remarks, expense_type: line.expense_type, expense_description: line.expense_description,
      quantity_unit: line.quantity_unit as OtherExpenseUnit, unit_rate: line.captured_rate,
    })),
  }
}

// ---------------------------------------------------------------------------
// Whole-well cost analysis (daily run sheet + every cost factor)
// ---------------------------------------------------------------------------

export type DailyCostAfePosition = {
  afe_id: string; afe_code: string; afe_name: string; afe_status: string; currency: string
  planned_total: string; actual: string; other_expenses: string; balance: string; over_budget: boolean
  /** LIH register cost deducted explicitly from this AFE's total. */
  lih_cost?: string; actual_including_lih?: string; afe_available?: string; balance_including_lih?: string
  sheets: number; days_recorded: number; first_day: string | null; last_day: string | null
  adjusted_planned_total: string | null; adjusted_balance: string | null; has_adjustment: boolean
}
export type DailyCostDailyRow = {
  cost_date: string; services: string; consumables: string; tangibles: string; other_expenses: string
  total: string; upa: string; npt: string; cumulative: string; budget_balance: string; sheets: number
  /** LIH register cost for the day and the AFE balance after deducting it. */
  lih?: string; cumulative_including_lih?: string; budget_balance_including_lih?: string
  status: 'draft' | 'submitted' | 'mixed'
  adjusted_budget_balance: string | null
  actual_depth?: string | null
  total_usd?: string
  cumulative_usd?: string
}
export type DailyCostFactorRow = {
  key: string; code: string; name: string; detail: string; amount: string
  planned: string | null; balance: string | null; share: string; quantity: string
}
export type DailyCostFactorDimension =
  | 'cost_group' | 'classification' | 'section' | 'phase' | 'activity'
  | 'sub_activity' | 'party' | 'rate_source' | 'currency' | 'item'
export type DailyCostFactorGroup = {
  dimension: DailyCostFactorDimension; label: string; currency: string; total: string; rows: DailyCostFactorRow[]
}
export type DailyCostWellTotals = {
  currency: string; planned: string; actual: string; balance: string; used_percent: string
  services: string; consumables: string; tangibles: string; other_expenses: string; upa: string; npt: string
  /** Services actual split by activity classification (the three add up to `services`). */
  services_actual_planned?: string; services_actual_upa?: string; services_actual_npt?: string
  planned_days: string; recorded_days: number; elapsed_days: number; average_per_day: string
  days_to_budget: string | null; first_day: string | null; last_day: string | null
  sheets: number; draft_sheets: number; submitted_sheets: number; lines: number
  // Revised plan when approved SOW adjustments exist. Nulls mean no approved
  // adjustment, so callers use planned / planned_days above.
  adjusted_planned: string | null; adjusted_balance: string | null; adjusted_used_percent: string | null
  adjusted_planned_days: string | null; has_adjustment: boolean
  // Progress days counted from the Well Spud Date & Time (null until a spud
  // date is entered on any scope).
  spud_actual_days: string | null; spud_days_variance: string | null
  // Mud chemicals comparison: the recorded actual and the reconciled amount
  // that the final AFE comparison uses. comparison_* are the final figures.
  actual_mud_chemicals: string; reconciled_mud_cost: string; comparison_mud_cost: string
  mud_cost_adjustment: string
  comparison_actual: string | null; comparison_consumables: string | null
  comparison_balance: string | null; comparison_used_percent: string | null
  comparison_adjusted_balance: string | null; has_mud_reconciliation: boolean
  // LIH Cost Register: recorded separately, added to the actual cost and
  // deducted from the AFE amount in every comparison.
  lih_cost?: string; lih_line_count?: number; lih_entries?: number
  afe_available?: string; actual_including_lih?: string
  comparison_actual_including_lih?: string; comparison_balance_including_lih?: string
  comparison_used_percent_including_lih?: string; comparison_adjusted_balance_including_lih?: string | null
}
export type DailyCostMudSectionReconciliation = {
  section_id: string; section_label: string
  mud_type: string | null; mud_type_label: string
  is_configured: boolean; is_wbm: boolean
  currency: string; base_rate: string; actual_cost: string
  reconciled_cost: string | null; cost_per_bbl: string | null
  consumption_losses: string; adjustment: string | null; remarks: string
}
export type DailyCostMudReconciliation = {
  available: boolean; currency: string
  actual_cost: string; reconciled_cost: string; unreconciled_actual_cost: string
  comparison_cost: string; adjustment: string
  latest_cost_per_bbl: string | null; latest_cost_per_bbl_section: string
  latest_cost_per_bbl_date: string | null
  configured_section_count: number; unconfigured_section_count: number
  sections: DailyCostMudSectionReconciliation[]; note: string
}
/** One LIH register day inside the well cost analysis. */
export type DailyCostLihDay = {
  entry_id: string; cost_date: string; afe_id: string | null; afe_code: string
  currency: string; line_count: number; total_cost: string
}
/** LIH cost filed against one AFE, deducted from that AFE's total. */
export type DailyCostLihDeduction = {
  afe_id: string; afe_code: string; afe_name: string; currency: string
  lih_cost: string; afes_total: string
}
/** The well's LIH Cost Register, accounted apart from the daily cost groups. */
export type DailyCostLihSummary = {
  available: boolean; currency: string; total: string; line_count: number; entry_count: number
  deductions_by_afe: DailyCostLihDeduction[]; days: DailyCostLihDay[]
}

export type DailyCostWellSummary = {
  well: {
    id: string; well_code: string; well_name: string; rig_code: string; rig_name: string
    status: string; config_status: string; afes: DailyCostAfeOption[]
  }
  from_date: string | null; to_date: string | null; as_of: string | null; include_draft: boolean
  totals: DailyCostWellTotals
  afes: DailyCostAfePosition[]
  daily: DailyCostDailyRow[]
  factors: DailyCostFactorGroup[]
  budget_lines: DailyCostComparisonLine[]
  warnings: DailyCostWarning[]
  progress: WellProgressScope[]
  mud_cost: DailyCostMudReconciliation | null
  lih_cost: DailyCostLihSummary | null
}

/** Server-side register filters, so the daily basis stays quick on a long well. */
export type DailyCostEntryFilter = {
  well_id?: string; afe_id?: string; status?: '' | DailyCostStatus
  from?: string; to?: string
}

export function entryQuery(filter: DailyCostEntryFilter): string {
  const params = new URLSearchParams()
  if (filter.well_id) params.set('well_id', filter.well_id)
  if (filter.afe_id) params.set('afe_id', filter.afe_id)
  if (filter.status) params.set('status', filter.status)
  if (filter.from) params.set('from', filter.from)
  if (filter.to) params.set('to', filter.to)
  const query = params.toString()
  return query ? `?${query}` : ''
}

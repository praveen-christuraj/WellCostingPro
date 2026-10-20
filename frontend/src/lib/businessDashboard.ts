// Typed contract for the Business Dashboard. Every Decimal arrives as a string
// (the API serialises money without losing precision), so formatting helpers
// live here and every figure keeps the currency it was reported in.

export type Money = string | null

export type DashboardCapabilities = { plan: boolean; budget: boolean; actuals: boolean }

export type DashboardRigOption = { id: string; code: string; name: string }
export type DashboardWellOption = { id: string; code: string; name: string; rig_id: string; rig_code: string; status: string }
export type DashboardAfeOption = {
  id: string
  code: string
  name: string
  well_id: string
  rig_id: string
  afe_type: string
  status: string
  currency: string
}

export type DashboardFilterOptions = {
  rigs: DashboardRigOption[]
  wells: DashboardWellOption[]
  afes: DashboardAfeOption[]
  currencies: string[]
  default_currency: string
  afe_types: string[]
}

export type DashboardKpis = {
  rigs: number | null
  wells: number | null
  active_wells: number | null
  completed_wells: number | null
  configured_wells: number | null
  draft_wells: number | null
  afes: number | null
  wells_with_actuals: number | null
  planned_days: Money
  actual_days: number | null
  recorded_days: number | null
  npt_days: number | null
  upa_days: number | null
  day_variance: Money
  afe_amount: Money
  sow_adjusted_amount: Money
  effective_afe_amount: Money
  actual_amount: Money
  afe_balance: Money
  utilisation_percent: Money
  npt_amount: Money
  upa_amount: Money
  other_expenses_amount: Money
  planned_depth: Money
  actual_depth: Money
  depth_progress_percent: Money
  depth_unit: string
  over_budget_wells: number
  over_budget_afes: number
  conversion_pending_afes: number
}

export type DashboardWellRow = {
  well_id: string
  well_code: string
  well_name: string
  well_location: string
  block: string
  status: string
  config_status: string
  depth_unit: string
  configured_depth_unit?: string
  rig_id: string
  rig_code: string
  rig_name: string
  drilling_planned_days: Money
  completion_planned_days: Money
  planned_days: Money
  drilling_plan_adjusted: boolean
  completion_plan_adjusted: boolean
  section_count: number | null
  planned_depth: Money
  actual_depth: Money
  depth_progress_percent: Money
  afe_count: number | null
  drilling_afe_count: number | null
  completion_afe_count: number | null
  afe_amount: Money
  sow_adjusted_amount: Money
  has_sow_adjustment: boolean
  effective_afe_amount: Money
  afe_balance: Money
  utilisation_percent: Money
  over_budget: boolean
  actual_amount: Money
  services_amount: Money
  consumables_amount: Money
  tangibles_amount: Money
  other_expenses_amount: Money
  npt_amount: Money
  upa_amount: Money
  first_cost_date: string | null
  last_cost_date: string | null
  actual_days: number | null
  recorded_days: number | null
  sheets: number | null
  draft_sheets: number | null
  npt_days: number | null
  upa_days: number | null
  currency: string
}

export type DashboardAfeRow = {
  afe_id: string
  afe_code: string
  afe_name: string
  afe_type: string
  configuration_scope: string
  status: string
  well_id: string
  well_code: string
  well_name: string
  rig_id: string
  rig_code: string
  rig_name: string
  currency: string
  afe_amount: Money
  sow_adjusted_amount: Money
  has_sow_adjustment: boolean
  sow_revision: number | null
  effective_afe_amount: Money
  actual_amount: Money
  afe_balance: Money
  utilisation_percent: Money
  over_budget: boolean
  conversion_pending: boolean
  first_cost_date: string | null
  last_cost_date: string | null
  actual_days: number | null
  recorded_days: number | null
  sheets: number | null
  npt_days: number | null
  upa_days: number | null
  npt_amount: Money
  upa_amount: Money
}

export type DashboardRigRow = {
  rig_id: string
  rig_code: string
  rig_name: string
  wells: number
  active_wells: number
  completed_wells: number
  planned_days: Money
  actual_days: number | null
  recorded_days: number | null
  npt_days: number | null
  upa_days: number | null
  afe_amount: Money
  effective_afe_amount: Money
  actual_amount: Money
  afe_balance: Money
  planned_depth: Money
  actual_depth: Money
  draft_sheets: number | null
}

export type DashboardDailyPoint = {
  cost_date: string
  actual: string
  cumulative: string
  npt: string
  upa: string
  sheets: number
}

export type DashboardSlice = {
  key: string
  label: string
  count: number | null
  days: number | null
  planned: Money
  actual: Money
  balance: Money
  share: Money
}

export type DashboardSectionRow = {
  hole_section_id: string | null
  section_code: string
  section_name: string
  scope: string
  from_depth: Money
  to_depth: Money
  actual_depth?: Money
  depth_unit?: string
  planned_days: Money
  active_days: number | null
  amount: Money
  share: Money
  reached: boolean
  planned_phase_count: number | null
}

export type DashboardActivityRow = {
  activity_id: string | null
  activity_code: string
  activity_name: string
  classification: string
  active_days: number | null
  amount: Money
  share: Money
  sub_activity_count: number | null
}

export type DashboardAlert = {
  kind: string
  severity: 'info' | 'warning' | 'error'
  title: string
  detail: string
  well_id: string | null
}

export type BusinessDashboard = {
  generated_at: string
  date_from: string | null
  date_to: string | null
  include_draft: boolean
  currency: string
  available_currencies: string[]
  default_currency: string
  capabilities: DashboardCapabilities
  filters: DashboardFilterOptions
  kpis: DashboardKpis
  alerts: DashboardAlert[]
  well_statuses: DashboardSlice[]
  afe_statuses: DashboardSlice[]
  cost_groups: DashboardSlice[]
  classification: DashboardSlice[]
  daily: DashboardDailyPoint[]
  rigs: DashboardRigRow[]
  wells: DashboardWellRow[]
  afes: DashboardAfeRow[]
  excluded_afe_count: number
  excluded_entry_count: number
  conversion_pending_afes: number
}

export type DashboardDaySheet = {
  entry_id: string
  cost_date: string
  afe_code: string
  status: string
  total: string
  npt: string
  upa: string
  actual_depth?: Money
  depth_unit?: string
  warning_count: number
}

export type DashboardWellDetail = {
  well: DashboardWellRow
  afes: DashboardAfeRow[]
  daily: DashboardDailyPoint[]
  sheets: DashboardDaySheet[]
  classification: DashboardSlice[]
  cost_groups: DashboardSlice[]
  activities: DashboardActivityRow[]
  sections: DashboardSectionRow[]
  notes: string[]
}

export type DashboardFilters = {
  from: string
  to: string
  rig: string
  well: string
  afe: string
  afeType: string
  status: string
  currency: string
  includeDraft: boolean
}

export const EMPTY_FILTERS: DashboardFilters = {
  from: '', to: '', rig: '', well: '', afe: '', afeType: '', status: '', currency: '', includeDraft: true,
}

export function dashboardQuery(filters: Partial<DashboardFilters>): string {
  const params = new URLSearchParams()
  if (filters.from) params.set('from', filters.from)
  if (filters.to) params.set('to', filters.to)
  if (filters.rig) params.set('rig_id', filters.rig)
  if (filters.well) params.set('well_id', filters.well)
  if (filters.afe) params.set('afe_id', filters.afe)
  if (filters.afeType) params.set('afe_type', filters.afeType)
  if (filters.status) params.set('well_status', filters.status)
  if (filters.currency) params.set('currency', filters.currency)
  if (filters.includeDraft === false) params.set('include_draft', 'false')
  return params.toString()
}

export function money(value: Money | number | undefined, currency: string): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  const formatted = Math.abs(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const sign = amount < 0 ? '−' : ''
  return `${sign}${currency ? `${currency} ` : ''}${formatted}`
}

export function compactMoney(value: Money | number | undefined, currency: string): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  const abs = Math.abs(amount)
  const text = abs >= 1_000_000_000 ? `${(abs / 1_000_000_000).toFixed(2)}B`
    : abs >= 1_000_000 ? `${(abs / 1_000_000).toFixed(2)}M`
      : abs >= 1_000 ? `${(abs / 1_000).toFixed(1)}K`
        : abs.toLocaleString(undefined, { maximumFractionDigits: 0 })
  return `${amount < 0 ? '−' : ''}${currency ? `${currency} ` : ''}${text}`
}

export function decimal(value: Money | number | undefined, digits = 0): string {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function percent(value: Money | number | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return `${Number(value).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
}

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toLocaleString()
}

export function displayDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(`${value}T00:00:00`)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

export function displayDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString(undefined, {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

export const AFE_STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  review: 'In review',
  approval: 'Approved',
}

export const CLASSIFICATION_TONES: Record<string, 'neutral' | 'info' | 'success' | 'warning' | 'error'> = {
  Planned: 'success',
  UPA: 'warning',
  NPT: 'error',
}

// Presets keep the date filter a single click for the common views.
export function presetRange(preset: 'all' | '7d' | '30d' | 'month' | 'quarter'): { from: string; to: string } {
  const today = new Date()
  const iso = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
  if (preset === 'all') return { from: '', to: '' }
  if (preset === 'month') {
    return { from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: iso(today) }
  }
  if (preset === 'quarter') {
    const startMonth = Math.floor(today.getMonth() / 3) * 3
    return { from: iso(new Date(today.getFullYear(), startMonth, 1)), to: iso(today) }
  }
  const days = preset === '7d' ? 6 : 29
  const start = new Date(today)
  start.setDate(start.getDate() - days)
  return { from: iso(start), to: iso(today) }
}

// Reports module: shared types, report registry and helpers for the six
// usage / cost matrix reports. All figures are read-only projections of the
// Daily Cost ledger served by /usage-reports.
import { api, body } from './api'

export type UsageReportKey = 'mud-chemicals' | 'drill-bits' | 'tangibles' | 'services' | 'vendors'
export type NptUpaKey = 'npt-upa'
export type AnyReportKey = UsageReportKey | NptUpaKey
export type UsageMode = 'usage' | 'cost'
export type ScopeFilter = '' | 'drilling' | 'completion'
export type LifecycleFilter = '' | 'active' | 'final_review' | 'completed'

export interface UsageReportFilters {
  blockId: string
  rigId: string
  wellIds: string[]
  scope: ScopeFilter
  lifecycle: LifecycleFilter
  currency: string
  dateFrom: string
  dateTo: string
  includeDraft: boolean
}

export const EMPTY_FILTERS: UsageReportFilters = {
  blockId: '',
  rigId: '',
  wellIds: [],
  scope: '',
  lifecycle: '',
  currency: '',
  dateFrom: '',
  dateTo: '',
  includeDraft: true,
}

export interface UsageBlockOption { id: string; block_code: string; block_name: string }
export interface UsageRigOption { id: string; rig_code: string; rig_name: string }
export interface UsageWellOption {
  id: string
  rig_id: string
  block_id: string
  well_code: string
  well_name: string
  display_name: string
  status: string
  config_status: string
  completion_status: string
  completion_config_status: string
  scopes: string[]
  has_costs: boolean
}
export interface UsageCurrencyOption { code: string; name: string; symbol: string; is_default: boolean }
export interface UsageReference {
  blocks: UsageBlockOption[]
  rigs: UsageRigOption[]
  wells: UsageWellOption[]
  currencies: UsageCurrencyOption[]
  default_currency: string
}

export interface UsageSection {
  section_key: string
  hole_section_id: string
  section_code: string
  section_name: string
  scope: string
}
export interface UsageWellColumn {
  well_id: string
  well_code: string
  well_name: string
  rig_id: string
  rig_code: string
  rig_name: string
  block_id: string
  block_code: string
  block_name: string
  scopes: string[]
  sections: UsageSection[]
}
export interface UsageCell { section_key: string; quantity: string; amount: string }
export interface UsageWellCell { well_id: string; sections: UsageCell[]; quantity: string; amount: string }
export interface UsageItemRow {
  item_id: string
  item_code: string
  item_name: string
  uom: string
  category: string
  subcategory: string
  manufacturer: string
  detail: string
  cells: UsageWellCell[]
  quantity_total: string
  amount_total: string
}
export interface UsageDetailRow {
  row_id: string
  report: string
  cost_group: string
  item_id: string
  item_code: string
  item_name: string
  uom: string
  category: string
  subcategory: string
  manufacturer: string
  detail: string
  well_id: string
  well_code: string
  well_name: string
  rig_code: string
  block_code: string
  scope: string
  section_key: string
  section_code: string
  section_name: string
  quantity: string
  amount: string
  currency: string
}
export interface UsageMatrix {
  report: UsageReportKey
  mode: UsageMode
  currency: string
  date_from: string | null
  date_to: string | null
  include_draft: boolean
  wells: UsageWellColumn[]
  rows: UsageItemRow[]
  detail: UsageDetailRow[]
  well_totals: UsageWellCell[]
  grand_quantity: string
  grand_amount: string
  entry_count: number
  excluded_entry_count: number
}

export interface NptUpaWellRow {
  well_id: string
  well_code: string
  well_name: string
  rig_code: string
  block_code: string
  planned_affected_dates: number
  upa_affected_dates: number
  npt_affected_dates: number
  planned_hours: string
  upa_hours: string
  npt_hours: string
  planned_days: string
  upa_days: string
  npt_days: string
  planned_amount: string
  upa_amount: string
  npt_amount: string
  total_amount: string
  overallocated_dates: number
}
export interface NptUpaDetailRow {
  row_id: string
  well_id: string
  well_code: string
  well_name: string
  rig_code: string
  block_code: string
  scope: string
  classification: string
  affected_dates: number
  hours: string
  days: string
  amount: string
  currency: string
}
export interface NptUpaReport {
  currency: string
  date_from: string | null
  date_to: string | null
  include_draft: boolean
  wells: NptUpaWellRow[]
  detail: NptUpaDetailRow[]
  totals: NptUpaWellRow
  entry_count: number
  excluded_entry_count: number
  overallocated_date_count: number
}

export interface ReportDefinition {
  key: AnyReportKey
  path: string
  title: string
  eyebrow: string
  subtitle: string
  mode: UsageMode | 'npt-upa'
  matrix: boolean
}

export const REPORT_DEFINITIONS: ReportDefinition[] = [
  {
    key: 'mud-chemicals',
    path: '/reports/mud-chemicals-usage',
    title: 'Mud chemicals usage',
    eyebrow: 'REPORTS / MUD CHEMICALS USAGE',
    subtitle: 'Well-wise mud chemical usage matrix: chemicals down the rows, wells across the columns with hole-section usage quantities and costs for the selected filters.',
    mode: 'usage',
    matrix: true,
  },
  {
    key: 'drill-bits',
    path: '/reports/drill-bits-usage',
    title: 'Drill bits usage',
    eyebrow: 'REPORTS / DRILL BITS USAGE',
    subtitle: 'Well-wise drill bit usage matrix with make, model, size and IADC details, section usage quantities and costs across the selected wells.',
    mode: 'usage',
    matrix: true,
  },
  {
    key: 'tangibles',
    path: '/reports/tangibles-usage',
    title: 'Tangibles usage',
    eyebrow: 'REPORTS / TANGIBLES USAGE',
    subtitle: 'Well-wise tangible usage matrix grouped by category and subcategory, with section usage quantities and costs for the selected filters.',
    mode: 'usage',
    matrix: true,
  },
  {
    key: 'services',
    path: '/reports/service-wise-cost',
    title: 'Service-wise cost report',
    eyebrow: 'REPORTS / SERVICE-WISE COST',
    subtitle: 'Total service costs per well and hole section, across every daily cost sheet matching the selected blocks, scopes, well statuses and date range.',
    mode: 'cost',
    matrix: true,
  },
  {
    key: 'vendors',
    path: '/reports/vendor-wise-cost',
    title: 'Vendor/company-wise cost report',
    eyebrow: 'REPORTS / VENDOR-WISE COST',
    subtitle: 'Total costs booked per vendor or recorded company across the selected wells, with cost-group detail and hole-section breakdowns.',
    mode: 'cost',
    matrix: true,
  },
  {
    key: 'npt-upa',
    path: '/reports/npt-upa',
    title: 'NPT/UPA report',
    eyebrow: 'REPORTS / NPT / UPA',
    subtitle: 'Non-productive time and unplanned activity: allocated hours ÷ 24 and their costs per well, with affected cost dates shown separately.',
    mode: 'npt-upa',
    matrix: false,
  },
]

export function reportDefinition(key: AnyReportKey): ReportDefinition {
  const definition = REPORT_DEFINITIONS.find(entry => entry.key === key)
  if (!definition) throw new Error(`Unknown report ${key}`)
  return definition
}

export function buildQuery(filters: UsageReportFilters): string {
  const params = new URLSearchParams()
  if (filters.blockId) params.set('block_id', filters.blockId)
  if (filters.rigId) params.set('rig_id', filters.rigId)
  filters.wellIds.forEach(id => params.append('well_id', id))
  if (filters.scope) params.set('scope', filters.scope)
  if (filters.lifecycle) params.set('lifecycle', filters.lifecycle)
  if (filters.currency) params.set('currency', filters.currency)
  if (filters.dateFrom) params.set('from', filters.dateFrom)
  if (filters.dateTo) params.set('to', filters.dateTo)
  if (!filters.includeDraft) params.set('include_draft', 'false')
  const query = params.toString()
  return query ? `?${query}` : ''
}

export async function fetchReference(): Promise<UsageReference> {
  return api<UsageReference>('/usage-reports/reference')
}

export async function fetchMatrix(key: UsageReportKey, filters: UsageReportFilters): Promise<UsageMatrix> {
  return api<UsageMatrix>(`/usage-reports/matrix/${key}${buildQuery(filters)}`)
}

export async function fetchNptUpa(filters: UsageReportFilters): Promise<NptUpaReport> {
  return api<NptUpaReport>(`/usage-reports/npt-upa${buildQuery(filters)}`)
}

export async function auditExport(report: AnyReportKey, format: 'csv' | 'xlsx' | 'pdf', recordCount: number, filters: UsageReportFilters): Promise<void> {
  await api('/usage-reports/export-audit', {
    method: 'POST',
    body: body({
      report,
      format,
      record_count: recordCount,
      block_id: filters.blockId,
      rig_id: filters.rigId,
      well_ids: filters.wellIds,
      scope: filters.scope,
      lifecycle: filters.lifecycle,
      currency: filters.currency,
      date_from: filters.dateFrom || null,
      date_to: filters.dateTo || null,
      include_draft: filters.includeDraft,
    }),
  })
}

// ---- Formatting -----------------------------------------------------------

export function formatMoney(value: string | number | null | undefined, currency = ''): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '—'
  const text = parsed.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return currency ? `${text} ${currency}` : text
}

export function formatQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '—'
  if (parsed === 0) return '0'
  return parsed.toLocaleString(undefined, { maximumFractionDigits: 4 })
}

export function formatDateText(value: string | null): string {
  if (!value) return 'Inception'
  return new Date(`${value}T00:00:00`).toLocaleDateString()
}

export const LIFECYCLE_OPTIONS: { value: LifecycleFilter; label: string }[] = [
  { value: '', label: 'All well statuses' },
  { value: 'active', label: 'Active wells' },
  { value: 'final_review', label: 'Wells under final review' },
  { value: 'completed', label: 'Completed wells' },
]

export const SCOPE_OPTIONS: { value: ScopeFilter; label: string }[] = [
  { value: '', label: 'All scopes' },
  { value: 'drilling', label: 'Drilling' },
  { value: 'completion', label: 'Completion' },
]

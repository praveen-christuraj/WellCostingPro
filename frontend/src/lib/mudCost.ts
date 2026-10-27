export type MudCostCategory = 'opening_stock' | 'receipt' | 'additions' | 'consumption_losses' | 'others' | 'closing_stock'
export type MudCostBalanceView = 'daily' | 'monthly' | 'section' | 'inception'
export type MudCostLossView = 'daily' | 'monthly' | 'section' | 'inception'
export type MudCostMudType = 'WBM' | 'OBM' | 'SOBM' | 'OTHERS'

export const MUD_COST_MUD_TYPES: { value: MudCostMudType; label: string; help: string }[] = [
  { value: 'WBM', label: 'WBM — Water Based Mud', help: 'Cost/BBL is actual mud chemicals cost divided by additions. The actual cost remains the reconciled cost.' },
  { value: 'OBM', label: 'OBM — Oil Based Mud', help: 'Opening Stock + Extra OBM + Additions form total mud; ALPHA, BETA and Cost/BBL drive the reconciled cost.' },
  { value: 'SOBM', label: 'SOBM — Synthetic Oil Based Mud', help: 'Same reconciliation formula as OBM, using this section’s Cost/BBL base rate. Total mud includes Opening Stock.' },
  { value: 'OTHERS', label: 'OTHERS — Other mud system', help: 'Same formula as OBM (Opening + Extra + Additions). Remarks are mandatory so the mud system is documented.' },
]

export const MUD_COST_MUD_TYPE_LABELS: Record<MudCostMudType, string> = {
  WBM: 'Water Based Mud',
  OBM: 'Oil Based Mud',
  SOBM: 'Synthetic Oil Based Mud',
  OTHERS: 'Others',
}

export type MudCostLineSpec = {
  code: string
  category: MudCostCategory
  label: string
}

export const MUD_COST_CATEGORIES: { key: MudCostCategory; label: string }[] = [
  { key: 'opening_stock', label: 'Opening Stock' },
  { key: 'receipt', label: 'Receipt' },
  { key: 'additions', label: 'Additions' },
  { key: 'consumption_losses', label: 'Consumption/Losses' },
  { key: 'others', label: 'Others' },
]

export const MUD_COST_STOCK_LINES: MudCostLineSpec[] = [
  { code: 'opening_stock', category: 'opening_stock', label: 'Opening Stock' },
]

export const MUD_COST_ENTRY_LINES: MudCostLineSpec[] = [
  { code: 'extra_obm_received', category: 'receipt', label: 'Extra OBM Received' },
  { code: 'other_receipts', category: 'receipt', label: 'Other Receipts' },
  { code: 'drill_water', category: 'additions', label: 'Drill Water' },
  { code: 'base_oil', category: 'additions', label: 'Base Oil' },
  { code: 'crude_tdu_oil', category: 'additions', label: 'Crude/TDU Oil' },
  { code: 'chemicals', category: 'additions', label: 'Chemicals' },
  { code: 'barite', category: 'additions', label: 'Barite' },
  { code: 'other_additions', category: 'additions', label: 'Other Additions' },
  { code: 'verti_g_mud_on_cuttings', category: 'consumption_losses', label: 'Verti-G/Mud on Cuttings' },
  { code: 'mud_cleaner', category: 'consumption_losses', label: 'Mud Cleaner' },
  { code: 'centrifuge', category: 'consumption_losses', label: 'Centrifuge' },
  { code: 'by_pass', category: 'consumption_losses', label: 'By-Pass' },
  { code: 'formation_seepage', category: 'consumption_losses', label: 'Formation/Seepage' },
  { code: 'shakers', category: 'consumption_losses', label: 'Shakers' },
  { code: 'evaporation', category: 'consumption_losses', label: 'Evaporation' },
  { code: 'pit_cleaning_dump', category: 'consumption_losses', label: 'Pit Cleaning/Dump' },
  { code: 'trips', category: 'consumption_losses', label: 'Trips' },
  { code: 'left_in_hole', category: 'consumption_losses', label: 'Left-In-Hole' },
  { code: 'consumption_losses_others', category: 'consumption_losses', label: 'Other losses' },
  { code: 'offline_centrifuge_loss', category: 'others', label: 'Offline Centrifuge Loss' },
  { code: 'backloads', category: 'others', label: 'Backloads' },
  { code: 'obm_left_in_hole', category: 'others', label: 'OBM Left-In-Hole' },
  { code: 'other_losses_others', category: 'others', label: 'Others' },
]

export const MUD_COST_LINE_SPECS = [
  MUD_COST_STOCK_LINES[0],
  ...MUD_COST_ENTRY_LINES,
]

export const MUD_COST_LINE_GROUPS: { key: MudCostCategory; label: string; lines: MudCostLineSpec[] }[] = [
  { key: 'receipt', label: 'Receipt', lines: MUD_COST_ENTRY_LINES.filter(line => line.category === 'receipt') },
  { key: 'additions', label: 'Additions', lines: MUD_COST_ENTRY_LINES.filter(line => line.category === 'additions') },
  { key: 'consumption_losses', label: 'Consumption/Losses', lines: MUD_COST_ENTRY_LINES.filter(line => line.category === 'consumption_losses') },
  { key: 'others', label: 'Others', lines: MUD_COST_ENTRY_LINES.filter(line => line.category === 'others') },
]

export type MudCostLineInput = { line_code: string; amount: string | null; remarks: string }
export type MudCostLine = {
  line_code: string
  category: MudCostCategory
  label: string
  amount: string
  remarks: string
  sort_order: number
}

export type MudCostSectionOption = {
  id: string
  hole_section_id: string
  section_code: string
  section_name: string
  scope: 'drilling' | 'completion'
  from_depth: string
  to_depth: string
  is_current: boolean
  display_name: string
}

export type MudCostRigOption = {
  id: string
  rig_code: string
  rig_name: string
  display_name: string
  is_deleted: boolean
}

export type MudCostWellOption = {
  id: string
  rig_id: string
  well_code: string
  well_name: string
  display_name: string
  status: 'active' | 'completed'
  config_status: 'draft' | 'configured'
  is_deleted: boolean
  sections: MudCostSectionOption[]
}

export type MudCostReference = { rigs: MudCostRigOption[]; wells: MudCostWellOption[] }

export type MudCostEntry = {
  id: string
  rig_id: string
  rig_code: string
  rig_name: string
  well_id: string
  well_code: string
  well_name: string
  section_id: string
  hole_section_id: string
  section_scope: 'drilling' | 'completion'
  section_code: string
  section_name: string
  section_label: string
  section_from_depth: string
  section_to_depth: string
  entry_date: string
  opening_stock: string
  opening_stock_remarks: string
  receipt: string
  additions: string
  consumption_losses: string
  others: string
  closing_stock: string
  lines: MudCostLine[]
  is_deleted: boolean
  deleted_at: string | null
  created_by: string
  updated_by: string
  created_at: string
  updated_at: string
}

export type MudCostEntryPayload = {
  rig_id: string
  well_id: string
  section_id: string
  entry_date: string
  lines: MudCostLineInput[]
}
export type MudCostEntryUpdatePayload = {
  entry_date: string
  lines: MudCostLineInput[]
}

export type MudCostBalanceRow = {
  id: string
  rig_id: string
  rig_code: string
  well_id: string
  well_code: string
  section_id: string
  section_scope: 'drilling' | 'completion'
  section_code: string
  section_name: string
  section_label: string
  period_label: string
  cost_date: string
  first_entry_date: string
  last_entry_date: string
  entry_count: number
  opening_stock: string
  receipt: string
  additions: string
  consumption_losses: string
  others: string
  closing_stock: string
}

export type MudCostMaterialBalance = {
  view: MudCostBalanceView
  from_date: string | null
  to_date: string | null
  selected_section_count: number
  entry_count: number
  rows: MudCostBalanceRow[]
}

export type MudCostSectionSetting = {
  id: string | null
  rig_id: string; rig_code: string; well_id: string; well_code: string
  section_id: string; hole_section_id: string
  section_scope: 'drilling' | 'completion'
  section_code: string; section_name: string; section_label: string; display_name: string
  mud_type: MudCostMudType | null; mud_type_label: string
  remarks: string; base_rate: string; currency: string
  is_configured: boolean; is_current: boolean
  created_by: string; updated_by: string; created_at: string | null; updated_at: string | null
}

export type MudCostSectionSettingPayload = {
  rig_id: string
  well_id: string
  section_id: string
  mud_type: MudCostMudType
  remarks: string
  base_rate: string | null
}

export type MudCostReconciliationRow = {
  id: string
  rig_id: string; rig_code: string
  well_id: string; well_code: string
  section_id: string; section_scope: 'drilling' | 'completion'
  section_code: string; section_name: string; section_label: string
  mud_type: MudCostMudType | null; mud_type_label: string
  is_configured: boolean; is_wbm: boolean
  cost_date: string; currency: string; base_rate: string; opening_stock: string
  additions: string; extra_obm_received: string; actual_cost: string
  total_mud: string; alpha: string | null; beta: string | null
  cost_per_bbl: string | null
  consumption_losses: string; reconciled_cost: string | null
  cumulative_additions: string; cumulative_extra_obm_received: string
  cumulative_actual_cost: string; cumulative_total_mud: string
  cumulative_alpha: string | null; cumulative_beta: string | null
  cumulative_consumption_losses: string; cumulative_reconciled_cost: string | null
}

export type MudCostReconciliationSection = {
  section_id: string; hole_section_id: string
  rig_id: string; rig_code: string; well_id: string; well_code: string
  section_scope: 'drilling' | 'completion'
  section_code: string; section_name: string; section_label: string
  mud_type: MudCostMudType | null; mud_type_label: string
  remarks: string; is_configured: boolean; is_current: boolean; is_wbm: boolean
  currency: string; base_rate: string; opening_stock: string
  first_date: string | null; last_date: string | null; entry_count: number
  additions: string; extra_obm_received: string; actual_cost: string
  /* The section's own AFE Mud Chemicals allowance; null when the well has no locked AFE plan. */
  planned_cost: string | null
  total_mud: string; alpha: string | null; beta: string | null
  consumption_losses: string; cost_per_bbl: string | null
  reconciled_cost: string | null; adjustment: string | null
  verti_g_mud_on_cuttings: string; centrifuge: string; by_pass: string; evaporation: string; trips: string
  surface_loss_total: string
  mud_cleaner: string; formation_seepage: string; pit_cleaning_dump: string; left_in_hole: string; other_losses: string
  other_loss_total: string; total_losses: string
}

export type MudCostReconciliation = {
  from_date: string | null; to_date: string | null; currency: string
  selected_section_count: number; configured_section_count: number
  unconfigured_section_count: number; entry_count: number
  latest_cost_per_bbl: string | null; latest_cost_per_bbl_section: string
  latest_cost_per_bbl_date: string | null
  total_actual_cost: string; total_reconciled_cost: string
  total_adjustment: string; total_consumption_losses: string
  /* Whole-well AFE mud chemicals allowance, including sections with no activity yet. */
  total_planned_cost: string | null
  sections: MudCostReconciliationSection[]
  rows: MudCostReconciliationRow[]
}

export type MudCostImportResult = { imported_count: number; error_count: number; errors: string[]; success: boolean }
export type MudCostExportPayload = {
  module: 'entries' | 'deleted' | 'material_balance' | 'reconciliation' | 'consumption_losses'
  format: 'csv' | 'xlsx' | 'pdf' | 'print'
  record_count: number
  rig_id: string
  well_id: string
  section_id: string
  view?: MudCostBalanceView
  date_from?: string
  date_to?: string
}

export type MudCostLossRow = {
  id: string; period_label: string; cost_date: string; first_entry_date: string; last_entry_date: string; entry_count: number
  rig_id: string; rig_code: string; rig_name: string; well_id: string; well_code: string; well_name: string
  section_id: string; hole_section_id: string; section_scope: 'drilling' | 'completion'
  section_code: string; section_name: string; section_label: string
  mud_type: MudCostMudType | null; mud_type_label: string
  verti_g_mud_on_cuttings: string; centrifuge: string; by_pass: string; evaporation: string; trips: string
  surface_loss_total: string
  mud_cleaner: string; formation_seepage: string; pit_cleaning_dump: string; left_in_hole: string; other_losses: string
  other_loss_total: string; total_losses: string
}

export type MudCostLossReport = {
  view: MudCostLossView; from_date: string | null; to_date: string | null
  selected_section_count: number; entry_count: number
  surface_loss_total: string; other_loss_total: string; total_losses: string
  rows: MudCostLossRow[]
}

export const MUD_COST_LOSS_METRICS = [
  { key: 'verti_g_mud_on_cuttings', label: 'Verti-G/Mud on Cuttings', group: 'surface' },
  { key: 'centrifuge', label: 'Centrifuge', group: 'surface' },
  { key: 'by_pass', label: 'By-Pass', group: 'surface' },
  { key: 'evaporation', label: 'Evaporation', group: 'surface' },
  { key: 'trips', label: 'Trips', group: 'surface' },
  { key: 'surface_loss_total', label: 'Surface losses total', group: 'surface-total' },
  { key: 'mud_cleaner', label: 'Mud Cleaner', group: 'other' },
  { key: 'formation_seepage', label: 'Formation/Seepage', group: 'other' },
  { key: 'pit_cleaning_dump', label: 'Pit Cleaning/Dump', group: 'other' },
  { key: 'left_in_hole', label: 'Left-In-Hole', group: 'other' },
  { key: 'other_losses', label: 'Other losses', group: 'other' },
  { key: 'other_loss_total', label: 'Other losses total', group: 'other-total' },
  { key: 'total_losses', label: 'Total losses', group: 'grand-total' },
] as const

export const MUD_COST_LOSS_VIEWS: { value: MudCostLossView; label: string; help: string }[] = [
  { value: 'daily', label: 'Date-wise', help: 'One drill-through row per saved Mud Cost date and section.' },
  { value: 'monthly', label: 'Month-wise', help: 'Monthly totals per section; drill into a month to see its daily rows.' },
  { value: 'section', label: 'Selected range', help: 'One cumulative row per section for the required date range.' },
  { value: 'inception', label: 'Since inception', help: 'One cumulative row per section from its first record through the To date.' },
]

export const MUD_COST_BALANCE_VIEWS: { value: MudCostBalanceView; label: string; help: string }[] = [
  { value: 'daily', label: 'Date-wise', help: 'One row per entry date, with the opening stock carried forward within each section.' },
  { value: 'monthly', label: 'Month-wise', help: 'Monthly quantities and closing balances remain separate for each section.' },
  { value: 'section', label: 'Section-wise', help: 'One total row per section for the selected date range.' },
  { value: 'inception', label: 'Since inception', help: 'One inception-to-date row per section; sections are never combined.' },
]

export const MUD_COST_IMPORT_HEADERS = ['entry_date']
export const MUD_COST_IMPORT_OPTIONAL_HEADERS = MUD_COST_LINE_SPECS.flatMap(line => [line.code, `${line.code}_remarks`])
export const MUD_COST_IMPORT_SAMPLE: Record<string, string> = {
  entry_date: '2026-10-18',
  opening_stock: '500',
  opening_stock_remarks: 'Initial tank measurement',
  extra_obm_received: '20',
  extra_obm_received_remarks: 'Supplier delivery ticket 1048',
}

export function mudQuantity(value: string | number | null | undefined): string {
  const text = String(value ?? '0').trim()
  // Decimal values from the API can use exponent notation (notably "0E-10").
  // Expand the decimal as text instead of using Number, which loses precision
  // for large stock quantities. Keep the existing three-place display policy.
  const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text)
  if (!match || (!match[2] && !match[3])) return '—'
  const exponent = Number(match[4] ?? '0')
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 1000) return '—'
  const digits = (match[2] || '') + (match[3] || '')
  const decimalAt = (match[2] || '').length + exponent
  const wholeDigits = decimalAt <= 0 ? '0' : decimalAt >= digits.length
    ? digits + '0'.repeat(decimalAt - digits.length)
    : digits.slice(0, decimalAt)
  const fractionDigits = decimalAt < 0 ? '0'.repeat(Math.min(-decimalAt, 3)) + digits : digits.slice(decimalAt)
  const whole = BigInt(wholeDigits || '0')
  const fractional = fractionDigits.slice(0, 3).padEnd(3, '0')
  const milli = whole * 1000n + BigInt(fractional || '0')
  if (milli === 0n) return '0'
  const groupedWhole = whole.toLocaleString()
  const trimmedFraction = fractional.replace(/0+$/, '')
  return `${match[1] === '-' ? '−' : ''}${groupedWhole}${trimmedFraction ? `.${trimmedFraction}` : ''}`
}

export function localMudToday(): string {
  const now = new Date()
  const offset = now.getTimezoneOffset()
  return new Date(now.getTime() - offset * 60_000).toISOString().slice(0, 10)
}

export function validMudDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

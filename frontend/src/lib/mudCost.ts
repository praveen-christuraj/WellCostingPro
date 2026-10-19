export type MudCostCategory = 'opening_stock' | 'receipt' | 'additions' | 'consumption_losses' | 'others' | 'closing_stock'
export type MudCostBalanceView = 'daily' | 'monthly' | 'section' | 'inception'

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
  { code: 'consumption_losses_others', category: 'consumption_losses', label: 'Others' },
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

export type MudCostImportResult = { imported_count: number; error_count: number; errors: string[]; success: boolean }
export type MudCostExportPayload = {
  module: 'entries' | 'deleted' | 'material_balance'
  format: 'csv' | 'xlsx' | 'pdf' | 'print'
  record_count: number
  rig_id: string
  well_id: string
  section_id: string
  view?: MudCostBalanceView
  date_from?: string
  date_to?: string
}

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
  const match = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(text)
  if (!match || (!match[2] && !match[3])) return '—'
  const negative = match[1] === '-'
  const whole = BigInt(match[2] || '0')
  const fractional = (match[3] ?? '').slice(0, 3).padEnd(3, '0')
  const milli = whole * 1000n + BigInt(fractional || '0')
  if (milli === 0n) return '0'
  const groupedWhole = whole.toLocaleString()
  const trimmedFraction = fractional.replace(/0+$/, '')
  return `${negative ? '−' : ''}${groupedWhole}${trimmedFraction ? `.${trimmedFraction}` : ''}`
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

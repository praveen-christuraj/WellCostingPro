/**
 * LIH Cost Register API types and helpers (Daily Cost Management).
 *
 * The register is one worksheet per rig + well + date. Every item on the sheet
 * is captured locally (add, duplicate, paste from a spreadsheet) and the whole
 * sheet — header and all items — is saved in a single request. Each item's
 * total is computed by the server as no_of_units × unit_cost, and the day's
 * total is the sum of its items. That cost is added to the actual cost and
 * deducted from the AFE amount in the daily sheet, cost analysis and printed
 * reports.
 */

export type LihCostRigOption = { id: string; rig_code: string; rig_name: string; display_name: string }
export type LihCostWellOption = {
  id: string; rig_id: string; well_code: string; well_name: string
  status: string; config_status: string; display_name: string
}
export type LihCostAfeOption = {
  id: string; well_id: string; afe_code: string; afe_name: string; status: string
  configuration_scope: string; standard_currency: string; total_cost: string; display_name: string
}
export type LihCostUomOption = { code: string; name: string; symbol: string; display_name: string }
/** A previously entered item offered while typing a description. Never carries a serial number. */
export type LihCostItemSuggestion = {
  item_description: string
  od_size: string | null
  id_size: string | null
  fish_neck_od: string | null
  fish_neck_length: string | null
  connection: string
  length: string | null
  unit: string
  unit_cost: string
}
export type LihCostReference = {
  rigs: LihCostRigOption[]; wells: LihCostWellOption[]; afes: LihCostAfeOption[]
  uoms: LihCostUomOption[]; default_currency: string
  previous_items: LihCostItemSuggestion[]
}

/** How a row entered the register. */
export type LihCostSource = 'manual' | 'duplicate' | 'import'

/** One LIH item as stored. `total_cost` is always computed by the system. */
export type LihCostLine = {
  id: string
  item_description: string
  od_size: string | null
  id_size: string | null
  fish_neck_od: string | null
  fish_neck_length: string | null
  serial_number: string
  connection: string
  length: string | null
  no_of_units: string
  unit: string
  unit_cost: string
  total_cost: string
  remarks: string
  source: LihCostSource
  sort_order: number
  created_at: string
  updated_at: string
}

export type LihCostEntry = {
  id: string
  rig_id: string; rig_code: string; rig_name: string
  well_id: string; well_code: string; well_name: string
  afe_id: string | null; afe_code: string; afe_name: string
  cost_date: string
  currency: string
  remarks: string
  line_count: number
  total_cost: string
  /** Bumped by every save; a stale worksheet is rejected instead of overwriting. */
  revision: number
  display_name: string
  is_deleted: boolean
  deleted_at: string | null
  created_by: string; updated_by: string
  created_at: string; updated_at: string
}

export type LihCostDay = { entry: LihCostEntry; lines: LihCostLine[] }
/** Import outcome: per-row errors are shown beside the import preview. */
export type LihCostImportResponse = {
  imported_count: number
  error_count: number
  success: boolean
  day_count: number
  errors: string[]
}
export type LihCostCurrencyTotal = { currency: string; total: string; line_count: number; entry_count: number }
export type LihCostReport = {
  well_id: string; well_code: string; well_name: string
  from_date: string | null; to_date: string | null
  currency: string; total: string; line_count: number; entry_count: number
  totals: LihCostCurrencyTotal[]
  days: LihCostDay[]
}

/** Editable item values; the server recomputes the total from units × unit cost. */
export type LihCostLineInput = {
  item_description: string
  od_size: string
  id_size: string
  fish_neck_od: string
  fish_neck_length: string
  serial_number: string
  connection: string
  length: string
  no_of_units: string
  unit: string
  unit_cost: string
  remarks: string
}

export const EMPTY_LIH_LINE: LihCostLineInput = {
  item_description: '', od_size: '', id_size: '', fish_neck_od: '', fish_neck_length: '',
  serial_number: '', connection: '', length: '', no_of_units: '1', unit: '', unit_cost: '', remarks: '',
}

/** Editable columns of the worksheet, in entry order. */
export type LihField = keyof LihCostLineInput

/** One unsaved row on the worksheet. `saved` is the stored snapshot it started from. */
export type LihDraftRow = {
  key: string
  id: string | null
  source: LihCostSource
  values: LihCostLineInput
  saved: LihCostLineInput | null
}

/** Row-level validation message keyed by field. */
export type LihRowErrors = Partial<Record<LihField, string>>

let draftSequence = 0
/** Stable key for an unsaved row; never sent to the API. */
export function lihDraftKey(): string {
  draftSequence += 1
  return `lih-row-${draftSequence}`
}

export function lineFromSaved(line: LihCostLine): LihCostLineInput {
  const text = (value: string | null | undefined) => (value === null || value === undefined ? '' : String(value))
  return {
    item_description: line.item_description,
    od_size: text(line.od_size),
    id_size: text(line.id_size),
    fish_neck_od: text(line.fish_neck_od),
    fish_neck_length: text(line.fish_neck_length),
    serial_number: line.serial_number,
    connection: line.connection,
    length: text(line.length),
    no_of_units: trimDecimal(line.no_of_units),
    unit: line.unit,
    unit_cost: trimDecimal(line.unit_cost),
    remarks: line.remarks,
  }
}

/** 1250.5000000000 reads as 1250.5 for the editor, without changing the stored value. */
export function trimDecimal(value: string | number | null | undefined): string {
  const text = String(value ?? '').trim()
  if (!text) return ''
  const parsed = Number(text)
  return Number.isFinite(parsed) ? String(parsed) : text
}

export function draftRowFromSavedLine(line: LihCostLine): LihDraftRow {
  const values = lineFromSaved(line)
  return { key: lihDraftKey(), id: line.id, source: line.source ?? 'manual', values, saved: { ...values } }
}

export function blankDraftRow(defaults: Partial<LihCostLineInput> = {}): LihDraftRow {
  const values = { ...EMPTY_LIH_LINE, ...defaults }
  return { key: lihDraftKey(), id: null, source: 'manual', values, saved: null }
}

export function duplicateDraftRow(row: LihDraftRow, overrides: Partial<LihCostLineInput> = {}): LihDraftRow {
  return {
    key: lihDraftKey(),
    id: null,
    source: 'duplicate',
    values: { ...row.values, ...overrides },
    saved: null,
  }
}

/** A row nothing has been typed into yet; dropped on save instead of erroring. */
export function rowIsBlank(values: LihCostLineInput): boolean {
  return Object.entries(values).every(([field, value]) => {
    if (field === 'no_of_units') return value.trim() === '' || value.trim() === '1'
    return value.trim() === ''
  })
}

/** Saved rows change state when their values no longer match the stored snapshot. */
export function rowHasChanged(row: LihDraftRow): boolean {
  if (!row.id || !row.saved) return !rowIsBlank(row.values)
  return (Object.keys(row.values) as LihField[]).some(field => row.values[field] !== row.saved![field])
}

export function rowState(row: LihDraftRow): 'new' | 'edited' | 'saved' {
  if (!row.id) return 'new'
  return rowHasChanged(row) ? 'edited' : 'saved'
}

/** The item total exactly as the server computes it: units × unit cost, 2 dp. */
export function lihLineTotal(line: Pick<LihCostLineInput, 'no_of_units' | 'unit_cost'>): number {
  const units = Number(line.no_of_units)
  const cost = Number(line.unit_cost)
  if (!Number.isFinite(units) || !Number.isFinite(cost)) return 0
  return Math.round(units * cost * 100) / 100
}

const MAX_DIMENSION = 1000000
const MAX_UNITS = 1000000
const MAX_UNIT_COST = 100000000

function numberProblem(label: string, raw: string, { required = false, max = MAX_DIMENSION, min = 0 } = {}): string {
  const value = raw.trim()
  if (value === '') return required ? `${label} is mandatory.` : ''
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return `${label} must be a number.`
  if (parsed < min) return `${label} must be ${min === 0 ? 'zero or more' : `at least ${min}`}.`
  if (parsed > max) return `${label} cannot be more than ${max.toLocaleString()}.`
  return ''
}

/** Field-level validation for one worksheet row (blank optional fields are fine). */
export function validateDraftValues(values: LihCostLineInput): LihRowErrors {
  const errors: LihRowErrors = {}
  const description = values.item_description.trim()
  if (!description) errors.item_description = 'Item description is mandatory.'
  else if (description.length > 300) errors.item_description = 'Item description cannot be longer than 300 characters.'
  const unitsText = values.no_of_units.trim()
  if (unitsText === '') errors.no_of_units = 'No of units is mandatory.'
  else if (!Number.isFinite(Number(unitsText))) errors.no_of_units = 'No of units must be a number.'
  else if (Number(unitsText) <= 0) errors.no_of_units = 'No of units must be greater than zero.'
  else if (Number(unitsText) > MAX_UNITS) errors.no_of_units = `No of units cannot be more than ${MAX_UNITS.toLocaleString()}.`
  const cost = numberProblem('Unit cost', values.unit_cost, { required: true, max: MAX_UNIT_COST })
  if (cost) errors.unit_cost = cost
  for (const [field, label] of [
    ['od_size', 'OD size'], ['id_size', 'ID size'], ['fish_neck_od', 'Fish neck OD'],
    ['fish_neck_length', 'Fish neck length'], ['length', 'Length'],
  ] as const) {
    const problem = numberProblem(label, values[field])
    if (problem) errors[field] = problem
  }
  if (values.serial_number.length > 100) errors.serial_number = 'Serial number cannot be longer than 100 characters.'
  if (values.connection.length > 100) errors.connection = 'Connection cannot be longer than 100 characters.'
  if (values.unit.length > 50) errors.unit = 'Unit cannot be longer than 50 characters.'
  if (values.remarks.length > 500) errors.remarks = 'Remarks cannot be longer than 500 characters.'
  return errors
}

/** Every problem on the worksheet, in row order, ready to show beside the grid. */
export function validateDraft(rows: LihDraftRow[]): { row: number; key: string; errors: LihRowErrors; message: string }[] {
  const problems: { row: number; key: string; errors: LihRowErrors; message: string }[] = []
  rows.forEach((row, index) => {
    if (rowIsBlank(row.values)) return
    const errors = validateDraftValues(row.values)
    const first = Object.values(errors)[0]
    if (first) problems.push({ row: index + 1, key: row.key, errors, message: first })
  })
  return problems
}

/** The payload the API accepts for one item; blank optional numbers become null. */
export function lihLinePayload(line: LihCostLineInput) {
  const optional = (value: string) => (value.trim() === '' ? null : value.trim())
  return {
    item_description: line.item_description.trim(),
    od_size: optional(line.od_size),
    id_size: optional(line.id_size),
    fish_neck_od: optional(line.fish_neck_od),
    fish_neck_length: optional(line.fish_neck_length),
    serial_number: line.serial_number.trim(),
    connection: line.connection.trim(),
    length: optional(line.length),
    no_of_units: line.no_of_units.trim(),
    unit: line.unit.trim(),
    unit_cost: line.unit_cost.trim(),
    remarks: line.remarks.trim(),
  }
}

/** Lines for a whole-worksheet save: new rows without an id, saved rows with theirs. */
export function lihDayPayloadLines(rows: LihDraftRow[]) {
  return rows
    .filter(row => !rowIsBlank(row.values))
    .map(row => ({
      ...(row.id ? { id: row.id } : {}),
      source: row.source,
      ...lihLinePayload(row.values),
    }))
}

/** Only the rows that need sending: new or edited ones. */
export function lihChangedRows(rows: LihDraftRow[]): LihDraftRow[] {
  return rows.filter(row => rowHasChanged(row) && !rowIsBlank(row.values))
}

/** Fill empty equipment fields from a previously used item (never the serial number). */
export function applySuggestion(values: LihCostLineInput, suggestion: LihCostItemSuggestion): LihCostLineInput {
  const field = (current: string, next: string | null | undefined) =>
    current.trim() === '' && next !== null && next !== undefined && String(next).trim() !== ''
      ? trimDecimal(String(next))
      : current
  return {
    ...values,
    od_size: field(values.od_size, suggestion.od_size),
    id_size: field(values.id_size, suggestion.id_size),
    fish_neck_od: field(values.fish_neck_od, suggestion.fish_neck_od),
    fish_neck_length: field(values.fish_neck_length, suggestion.fish_neck_length),
    connection: field(values.connection, suggestion.connection),
    length: field(values.length, suggestion.length),
    unit: field(values.unit, suggestion.unit),
    unit_cost: field(values.unit_cost, suggestion.unit_cost),
  }
}

/** Server-side filters for the register list. */
export function lihQuery(values: Record<string, string>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value) params.set(key, value)
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

/** A human label for an optional measurement (blank reads as an em dash). */
export function lihMeasure(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed)
    ? parsed.toLocaleString(undefined, { maximumFractionDigits: 4 })
    : String(value)
}

// ---------------------------------------------------------------------------
// Spreadsheet import
// ---------------------------------------------------------------------------

/** Required import columns (item description, units and unit cost identify a row). */
export const LIH_IMPORT_HEADERS = ['item_description', 'no_of_units', 'unit_cost']
export const LIH_IMPORT_OPTIONAL_HEADERS = [
  'cost_date', 'od_size', 'id_size', 'fish_neck_od', 'fish_neck_length', 'serial_number',
  'connection', 'length', 'unit', 'remarks',
]
export const LIH_IMPORT_SAMPLE: Record<string, string> = {
  cost_date: '2026-10-18',
  item_description: '6 5/8 in drill collar',
  no_of_units: '2',
  unit_cost: '1250.50',
  od_size: '6.625',
  id_size: '2.8125',
  fish_neck_od: '4.5',
  fish_neck_length: '24',
  serial_number: 'DC-0091',
  connection: 'NC50',
  length: '9.5',
  unit: 'EA',
  remarks: 'Left in hole while reaming',
}

const IMPORT_ALIASES: Record<string, string> = {
  date: 'cost_date', lihdate: 'cost_date', costdate: 'cost_date',
  itemdescription: 'item_description', description: 'item_description', item: 'item_description',
  od: 'od_size', odsize: 'od_size', idsize: 'id_size', id: 'id_size',
  fishneckod: 'fish_neck_od', fishnecklength: 'fish_neck_length',
  serial: 'serial_number', serialnumber: 'serial_number', serialno: 'serial_number',
  noofunits: 'no_of_units', units: 'no_of_units', unitsqty: 'no_of_units', quantity: 'no_of_units', qty: 'no_of_units',
  uom: 'unit', unitofmeasure: 'unit',
  unitcost: 'unit_cost', rate: 'unit_cost', cost: 'unit_cost', price: 'unit_cost',
  remark: 'remarks', note: 'remarks', notes: 'remarks',
}

/** Map a spreadsheet row (any header spelling) onto the import payload keys. */
export function lihImportRow(row: Record<string, string>): Record<string, string> {
  const mapped: Record<string, string> = {}
  for (const [header, value] of Object.entries(row)) {
    const key = header.toLowerCase().replace(/[^a-z0-9]/g, '')
    const field = IMPORT_ALIASES[key] ?? (LIH_IMPORT_OPTIONAL_HEADERS.includes(key) || LIH_IMPORT_HEADERS.includes(key) ? key : '')
    if (field && mapped[field] === undefined) mapped[field] = String(value ?? '').trim()
  }
  return mapped
}

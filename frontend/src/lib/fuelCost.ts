/**
 * Fuel Cost Register API types and helpers (Daily Cost Management).
 *
 * The register is rig-scoped and measured in litres. A fuel day records the rig
 * engines' AGO, gas (recorded separately and never mixed into AGO), the physical
 * opening/closing stock, daily receipts and the company-wise AGO consumption.
 *
 * The material balance is never sent to the server: `fuelBalancePreview` mirrors
 * the server's arithmetic so the dialog can show the balance while the user
 * types, and the saved day always returns the authoritative figures.
 */

export type FuelCompanyCategory = {
  id: string
  company_id: string
  category_name: string
  remarks: string
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type FuelCompany = {
  id: string
  company_name: string
  vendor_id: string | null
  vendor_code: string
  is_default: boolean
  source: string
  remarks: string
  is_deleted: boolean
  deleted_at: string | null
  categories: FuelCompanyCategory[]
  display_name: string
  created_at: string
  updated_at: string
}

export type FuelCostRigOption = { id: string; rig_code: string; rig_name: string; display_name: string }

export type FuelCostVendorOption = {
  id: string
  vendor_code: string
  vendor_name: string
  vendor_type: string
  status: string
  registered: boolean
  display_name: string
}

export type FuelCostReference = {
  rigs: FuelCostRigOption[]
  companies: FuelCompany[]
  vendors: FuelCostVendorOption[]
}

export type FuelCostLineSource = 'manual' | 'import'

export type FuelCostCompanyLine = {
  id: string
  company_id: string
  company_name: string
  category_id: string | null
  category_name: string
  litres: string
  remarks: string
  source: FuelCostLineSource
  sort_order: number
  display_name: string
  created_at: string
  updated_at: string
}

/** The day's derived material balance. Every value is in litres. */
export type FuelCostBalance = {
  is_first_entry: boolean
  opening_overridden: boolean
  carried_opening: string
  previous_date: string | null
  opening_stock: string
  opening_adjustment: string
  receipt: string
  rig_engine_consumption: string
  company_consumption: string
  /** AGO only: rig engines + every company line. Gas is excluded. */
  total_consumption: string
  book_closing_stock: string
  actual_closing_stock: string
  closing_adjustment: string
  adjustments: string
  /** Recorded beside the balance, never inside it. */
  gas_consumption: string
}

export type FuelCostEntry = {
  id: string
  rig_id: string
  rig_code: string
  rig_name: string
  cost_date: string
  rig_engine_consumption: string
  rig_engine_remarks: string
  gas_consumption: string
  gas_remarks: string
  opening_stock: string | null
  opening_overridden: boolean
  opening_remarks: string
  receipt_quantity: string
  receipt_remarks: string
  closing_stock: string | null
  closing_remarks: string
  remarks: string
  revision: number
  line_count: number
  company_consumption: string
  total_consumption: string
  balance: FuelCostBalance
  display_name: string
  is_deleted: boolean
  deleted_at: string | null
  created_by: string
  updated_by: string
  created_at: string
  updated_at: string
}

export type FuelCostDay = {
  rig_id: string
  rig_code: string
  rig_name: string
  cost_date: string
  entry: FuelCostEntry | null
  lines: FuelCostCompanyLine[]
  balance: FuelCostBalance
}

export type FuelCostCompanyConsumptionRow = {
  company_id: string
  company_name: string
  category_id: string | null
  category_name: string
  litres: string
  day_count: number
  line_count: number
}

export type FuelCostCompanyConsumption = {
  rig_id: string
  rig_code: string
  rig_name: string
  from_date: string | null
  to_date: string | null
  total_litres: string
  rows: FuelCostCompanyConsumptionRow[]
}

export type FuelCostImportResponse = {
  imported_count: number
  line_count: number
  error_count: number
  success: boolean
  day_count: number
  errors: string[]
}

// ---------------------------------------------------------------------------
// Formatting and arithmetic
// ---------------------------------------------------------------------------

/** Litres with grouped thousands. Blank/invalid reads as zero. */
export function fuelLitres(value: string | number | null | undefined, digits = 2): string {
  const number = Number(value ?? 0)
  if (!Number.isFinite(number)) return (0).toFixed(2)
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: Math.min(digits, 2),
    maximumFractionDigits: digits,
  }).format(number)
}

export function fuelNumber(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

/** A percentage of the rig total, or an em dash when the total is zero. */
export function fuelShare(value: string | number | null | undefined, total: number): string {
  if (!total) return '—'
  return `${((fuelNumber(value) / total) * 100).toFixed(1)}%`
}

export function fuelQuery(values: Record<string, string>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value) params.set(key, value)
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

// ---------------------------------------------------------------------------
// Draft state for the consumption dialog
// ---------------------------------------------------------------------------

export type FuelDraftLine = {
  key: string
  id?: string
  company_id: string
  category_id: string
  litres: string
  remarks: string
  source: FuelCostLineSource
}

export type FuelDraft = {
  rigEngine: string
  rigEngineRemarks: string
  gas: string
  gasRemarks: string
  opening: string
  openingRemarks: string
  openingOverride: boolean
  receipt: string
  receiptRemarks: string
  closing: string
  closingRemarks: string
  remarks: string
  lines: FuelDraftLine[]
}

export type FuelDraftErrors = {
  engine?: string
  gas?: string
  opening?: string
  receipt?: string
  closing?: string
  lines: Record<string, string>
  summary: string[]
}

let lineSequence = 0
export function fuelLineKey(): string {
  lineSequence += 1
  return `fuel-line-${lineSequence}`
}

export function blankFuelLine(): FuelDraftLine {
  return { key: fuelLineKey(), company_id: '', category_id: '', litres: '', remarks: '', source: 'manual' }
}

export function draftLineFromSaved(line: FuelCostCompanyLine): FuelDraftLine {
  return {
    key: line.id,
    id: line.id,
    company_id: line.company_id,
    category_id: line.category_id ?? '',
    litres: line.litres,
    remarks: line.remarks,
    source: line.source,
  }
}

/** Seed the dialog from the stored day (or from an empty prospective day). */
export function fuelDraftFromDay(day: FuelCostDay): FuelDraft {
  const entry = day.entry
  const override = Boolean(entry?.opening_overridden)
  return {
    rigEngine: entry?.rig_engine_consumption ?? '',
    rigEngineRemarks: entry?.rig_engine_remarks ?? '',
    gas: entry?.gas_consumption ?? '',
    gasRemarks: entry?.gas_remarks ?? '',
    opening: entry?.opening_stock ?? '',
    openingRemarks: entry?.opening_remarks ?? '',
    openingOverride: override,
    receipt: entry?.receipt_quantity ?? '',
    receiptRemarks: entry?.receipt_remarks ?? '',
    closing: entry?.closing_stock ?? '',
    closingRemarks: entry?.closing_remarks ?? '',
    remarks: entry?.remarks ?? '',
    lines: day.lines.map(draftLineFromSaved),
  }
}

export function fuelDraftDirty(draft: FuelDraft, baseline: FuelDraft): boolean {
  const normalize = (value: FuelDraft) => JSON.stringify({
    ...value,
    lines: value.lines.map(line => ({
      id: line.id ?? '', company_id: line.company_id, category_id: line.category_id,
      litres: line.litres.trim(), remarks: line.remarks.trim(),
    })),
  })
  return normalize(draft) !== normalize(baseline)
}

/** The material balance shown while the user types (mirrors the server). */
export function fuelBalancePreview(day: FuelCostDay, draft: FuelDraft) {
  const isFirst = day.entry ? day.entry.balance.is_first_entry : day.balance.is_first_entry
  const carried = fuelNumber(day.balance.carried_opening)
  const overrideActive = !isFirst && draft.openingOverride
  const opening = isFirst ? fuelNumber(draft.opening) : overrideActive ? fuelNumber(draft.opening) : carried
  const openingAdjustment = isFirst ? 0 : opening - carried
  const engine = fuelNumber(draft.rigEngine)
  const company = draft.lines.reduce((total, line) => total + fuelNumber(line.litres), 0)
  const totalConsumption = engine + company
  const receipt = fuelNumber(draft.receipt)
  const bookClosing = opening + receipt - totalConsumption
  const closingEntered = draft.closing.trim() !== ''
  const actualClosing = closingEntered ? fuelNumber(draft.closing) : bookClosing
  const closingAdjustment = actualClosing - bookClosing
  return {
    isFirst,
    carried,
    overrideActive,
    opening,
    openingAdjustment,
    receipt,
    engine,
    company,
    totalConsumption,
    bookClosing,
    actualClosing,
    closingAdjustment,
    adjustments: openingAdjustment + closingAdjustment,
    gas: fuelNumber(draft.gas),
  }
}

export function validateFuelDraft(draft: FuelDraft, day: FuelCostDay): FuelDraftErrors {
  const errors: FuelDraftErrors = { lines: {}, summary: [] }
  const isFirst = day.entry ? day.entry.balance.is_first_entry : day.balance.is_first_entry
  const check = (key: 'engine' | 'gas' | 'receipt', raw: string, label: string) => {
    if (raw.trim() === '') return
    const value = Number(raw)
    if (!Number.isFinite(value)) errors[key] = `${label} must be a number.`
    else if (value < 0) errors[key] = `${label} cannot be negative.`
  }
  check('engine', draft.rigEngine, 'Rig engine consumption')
  check('gas', draft.gas, 'Gas consumption')
  check('receipt', draft.receipt, 'Receipt')
  if (draft.closing.trim() !== '') {
    const value = Number(draft.closing)
    if (!Number.isFinite(value)) errors.closing = 'Actual closing stock must be a number.'
    else if (value < 0) errors.closing = 'Actual closing stock cannot be negative.'
  }
  const openingRequired = isFirst || draft.openingOverride
  if (openingRequired) {
    if (draft.opening.trim() === '') {
      errors.opening = isFirst
        ? 'Opening stock is mandatory on the first day of this rig.'
        : 'Enter the overridden opening stock, or use the carried opening.'
    } else {
      const value = Number(draft.opening)
      if (!Number.isFinite(value)) errors.opening = 'Opening stock must be a number.'
      else if (value < 0) errors.opening = 'Opening stock cannot be negative.'
    }
  }
  const seen = new Map<string, number>()
  draft.lines.forEach((line, index) => {
    if (!line.company_id && !line.litres.trim() && !line.remarks.trim()) return
    if (!line.company_id) {
      errors.lines[line.key] = 'Choose the company this consumption belongs to.'
      return
    }
    if (line.litres.trim() === '') {
      errors.lines[line.key] = 'Enter the consumption in litres.'
      return
    }
    const value = Number(line.litres)
    if (!Number.isFinite(value)) {
      errors.lines[line.key] = 'Consumption must be a number.'
      return
    }
    if (value < 0) {
      errors.lines[line.key] = 'Consumption cannot be negative.'
      return
    }
    const signature = `${line.company_id}:${line.category_id}`
    if (seen.has(signature)) {
      errors.lines[line.key] = `This company and category is already on row ${(seen.get(signature) ?? 0) + 1}.`
      return
    }
    seen.set(signature, index)
  })
  const hasData = fuelNumber(draft.rigEngine) || fuelNumber(draft.gas) || fuelNumber(draft.receipt)
    || draft.closing.trim() !== '' || draft.lines.some(line => line.company_id && line.litres.trim() !== '')
  if (!hasData) {
    errors.summary.push(
      'Record at least one of rig engine consumption, gas consumption, a receipt, a closing stock or company consumption.',
    )
  }
  if (Object.keys(errors.lines).length) {
    errors.summary.push('Fix the company consumption rows marked below.')
  }
  if (errors.engine || errors.gas || errors.opening || errors.receipt || errors.closing) {
    errors.summary.push('Fix the values marked next to the fields.')
  }
  return errors
}

export function fuelHasErrors(errors: FuelDraftErrors): boolean {
  return Boolean(
    errors.engine || errors.gas || errors.opening || errors.receipt || errors.closing
    || Object.keys(errors.lines).length || errors.summary.length,
  )
}

/** The authoritative save payload (never contains a balance figure). */
export function fuelSavePayload({
  rigId, costDate, draft, day, expectedRevision,
}: {
  rigId: string
  costDate: string
  draft: FuelDraft
  day: FuelCostDay
  expectedRevision?: number | null
}) {
  const isFirst = day.entry ? day.entry.balance.is_first_entry : day.balance.is_first_entry
  const sendOpening = isFirst || draft.openingOverride
  const clearOverride = !isFirst && !draft.openingOverride && Boolean(day.entry?.opening_overridden)
  return {
    rig_id: rigId,
    cost_date: costDate,
    rig_engine_consumption: draft.rigEngine.trim() || '0',
    rig_engine_remarks: draft.rigEngineRemarks.trim(),
    gas_consumption: draft.gas.trim() || '0',
    gas_remarks: draft.gasRemarks.trim(),
    opening_stock: sendOpening ? (draft.opening.trim() || null) : null,
    opening_overridden: !isFirst && draft.openingOverride,
    clear_opening_override: clearOverride,
    opening_remarks: draft.openingRemarks.trim(),
    receipt_quantity: draft.receipt.trim() || '0',
    receipt_remarks: draft.receiptRemarks.trim(),
    closing_stock: draft.closing.trim() || null,
    closing_remarks: draft.closingRemarks.trim(),
    remarks: draft.remarks.trim(),
    expected_revision: expectedRevision ?? null,
    lines: draft.lines
      .filter(line => line.company_id && line.litres.trim() !== '')
      .map(line => ({
        id: line.id,
        company_id: line.company_id,
        category_id: line.category_id || '',
        litres: line.litres.trim(),
        remarks: line.remarks.trim(),
        source: line.source,
      })),
  }
}

// ---------------------------------------------------------------------------
// Import template
// ---------------------------------------------------------------------------

export const FUEL_IMPORT_REQUIRED_HEADERS = ['DATE']
export const FUEL_IMPORT_OPTIONAL_HEADERS = [
  'RIG CODE',
  'RIG ENGINE CONSUMPTION (LITRES)',
  'RIG ENGINE REMARKS',
  'GAS CONSUMPTION (LITRES)',
  'GAS REMARKS',
  'OPENING STOCK (LITRES)',
  'OPENING REMARKS',
  'RECEIPT (LITRES)',
  'RECEIPT REMARKS',
  'ACTUAL CLOSING STOCK (LITRES)',
  'CLOSING REMARKS',
  'DAY REMARKS',
  'COMPANY',
  'CATEGORY',
  'COMPANY CONSUMPTION (LITRES)',
  'LINE REMARKS',
]
export const FUEL_IMPORT_SAMPLE: Record<string, string> = {
  DATE: '2026-10-01',
  'RIG CODE': 'RIG-01',
  'RIG ENGINE CONSUMPTION (LITRES)': '450',
  'RIG ENGINE REMARKS': 'Three engines running',
  'GAS CONSUMPTION (LITRES)': '60',
  'GAS REMARKS': 'Gas recorded separately',
  'OPENING STOCK (LITRES)': '12000',
  'OPENING REMARKS': 'Handover dip reading',
  'RECEIPT (LITRES)': '6000',
  'RECEIPT REMARKS': 'Bulk delivery',
  'ACTUAL CLOSING STOCK (LITRES)': '17000',
  'CLOSING REMARKS': 'Evening dip reading',
  'DAY REMARKS': 'Day one of the register',
  COMPANY: 'Acme Fuel Services',
  CATEGORY: 'Rig crew',
  'COMPANY CONSUMPTION (LITRES)': '200',
  'LINE REMARKS': 'Crew vehicles',
}

/** Map a spreadsheet row to the import API's lenient row contract. */
export function fuelImportRow(row: Record<string, string>) {
  return {
    rig_code: row['RIG CODE'] ?? '',
    cost_date: row.DATE ?? '',
    rig_engine_consumption: row['RIG ENGINE CONSUMPTION (LITRES)'] ?? '',
    rig_engine_remarks: row['RIG ENGINE REMARKS'] ?? '',
    gas_consumption: row['GAS CONSUMPTION (LITRES)'] ?? '',
    gas_remarks: row['GAS REMARKS'] ?? '',
    opening_stock: row['OPENING STOCK (LITRES)'] ?? '',
    opening_remarks: row['OPENING REMARKS'] ?? '',
    receipt_quantity: row['RECEIPT (LITRES)'] ?? '',
    receipt_remarks: row['RECEIPT REMARKS'] ?? '',
    closing_stock: row['ACTUAL CLOSING STOCK (LITRES)'] ?? '',
    closing_remarks: row['CLOSING REMARKS'] ?? '',
    remarks: row['DAY REMARKS'] ?? '',
    company_name: row.COMPANY ?? '',
    category_name: row.CATEGORY ?? '',
    litres: row['COMPANY CONSUMPTION (LITRES)'] ?? '',
    line_remarks: row['LINE REMARKS'] ?? '',
  }
}

/**
 * Fuel Cost Register API types and helpers (Daily Cost Management).
 *
 * The register is rig-scoped and measured in litres. A fuel day records the rig
 * engines' AGO, Rig Saving (litres) — AGO saved through gas usage, recorded
 * separately and never mixed into AGO consumption or stock deduction — the
 * physical opening/closing stock, daily receipts and company-wise AGO usage.
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

export type FuelCostPreviousLine = {
  company_id: string
  company_name: string
  category_id: string | null
  category_name: string
  litres: string
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
  /** AGO only: rig engines + every company line. Rig saving (gas) is excluded. */
  total_consumption: string
  book_closing_stock: string
  actual_closing_stock: string
  closing_adjustment: string
  adjustments: string
  /** Rig Saving (litres): AGO saved through gas usage, recorded beside the balance. */
  gas_consumption: string
  rig_saving_litres?: string
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
  rig_saving_litres?: string
  rig_saving_remarks?: string
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
  previous_lines?: FuelCostPreviousLine[]
  balance: FuelCostBalance
}

export type FuelCostRigSummary = {
  rig_id: string
  rig_code: string
  rig_name: string
  from_date: string | null
  to_date: string | null
  total_active_days: number
  period_days: number
  earliest_date: string | null
  latest_date: string | null
  opening_stock: string
  opening_adjustment: string
  receipt: string
  rig_engine_consumption: string
  company_consumption: string
  total_consumption: string
  expected_closing_stock: string
  book_closing_stock: string
  actual_closing_stock: string
  closing_adjustment: string
  adjustments: string
  gas_consumption: string
  rig_saving_litres: string
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

export type FuelCostCompanySummaryRow = {
  company_id: string
  company_name: string
  vendor_code: string
  is_default: boolean
  category_count: number
  litres: string
  day_count: number
  line_count: number
}

export type FuelCostCategorySummaryRow = {
  category_key: string
  category_name: string
  company_count: number
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
  rig_engine_litres?: string
  total_ago_litres?: string
  rig_saving_litres?: string
  active_day_count?: number
  rows: FuelCostCompanyConsumptionRow[]
  company_rows?: FuelCostCompanySummaryRow[]
  category_rows?: FuelCostCategorySummaryRow[]
}

export type FuelCostLedgerLine = {
  id: string
  entry_id: string
  cost_date: string
  rig_code: string
  company_id: string
  company_name: string
  vendor_code: string
  category_id: string | null
  category_name: string
  litres: string
  remarks: string
  source: string
}

export type FuelCostPaginatedLines = {
  rig_id: string
  total_count: number
  total_litres: string
  page: number
  page_size: number
  rows: FuelCostLedgerLine[]
}

export type FuelCostImportResponse = {
  imported_count: number
  line_count: number
  error_count: number
  success: boolean
  day_count: number
  errors: string[]
}

export type FuelCostExportModule =
  | 'register'
  | 'recent-register'
  | 'deleted'
  | 'material-balance'
  | 'company-consumption'
  | 'category-consumption'
  | 'company-lines'
  | 'day'

export type FuelMonthlyBalanceRow = {
  month: string
  month_label: string
  day_count: number
  opening_stock: number
  opening_adjustment: number
  receipt: number
  rig_engine_consumption: number
  company_consumption: number
  total_consumption: number
  book_closing_stock: number
  actual_closing_stock: number
  closing_adjustment: number
  adjustments: number
  rig_saving_litres: number
}

// ---------------------------------------------------------------------------
// Formatting, date stepping and roll-ups
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

/** Read Rig Saving (litres) from either `rig_saving_litres` or `gas_consumption`. */
export function entryRigSaving(entry: FuelCostEntry | null | undefined): string {
  if (!entry) return '0'
  return entry.rig_saving_litres ?? entry.balance?.rig_saving_litres ?? entry.balance?.gas_consumption ?? entry.gas_consumption ?? '0'
}

/** A percentage of the rig total, or an em dash when the total is zero. */
export function fuelShare(value: string | number | null | undefined, total: number): string {
  if (!total) return '—'
  return `${((fuelNumber(value) / total) * 100).toFixed(1)}%`
}

export function fuelQuery(values: Record<string, string | number | null | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

/** Step a YYYY-MM-DD calendar date by `deltaDays` without local timezone drift. */
export function shiftIsoDate(isoDate: string, deltaDays: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate.trim())
  if (!match) return isoDate
  const utc = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + deltaDays))
  if (Number.isNaN(utc.getTime())) return isoDate
  return utc.toISOString().slice(0, 10)
}

/** Roll active daily entries into chronological monthly material-balance rows. */
export function buildMonthlyMaterialBalance(entries: FuelCostEntry[]): FuelMonthlyBalanceRow[] {
  const ordered = [...entries]
    .filter(entry => !entry.is_deleted)
    .sort((left, right) => left.cost_date.localeCompare(right.cost_date))
  const byMonth = new Map<string, FuelCostEntry[]>()
  for (const entry of ordered) {
    const month = entry.cost_date.slice(0, 7)
    const bucket = byMonth.get(month) ?? []
    bucket.push(entry)
    byMonth.set(month, bucket)
  }
  const rows: FuelMonthlyBalanceRow[] = []
  for (const [month, items] of byMonth.entries()) {
    const first = items[0]
    const last = items[items.length - 1]
    const opening = first.balance.is_first_entry
      ? fuelNumber(first.balance.opening_stock)
      : fuelNumber(first.balance.carried_opening)
    const openingAdj = items.reduce((sum, item) => sum + fuelNumber(item.balance.opening_adjustment), 0)
    const receipt = items.reduce((sum, item) => sum + fuelNumber(item.balance.receipt), 0)
    const engine = items.reduce((sum, item) => sum + fuelNumber(item.balance.rig_engine_consumption), 0)
    const company = items.reduce((sum, item) => sum + fuelNumber(item.balance.company_consumption), 0)
    const totalAgo = engine + company
    const closingAdj = items.reduce((sum, item) => sum + fuelNumber(item.balance.closing_adjustment), 0)
    const adjustments = openingAdj + closingAdj
    const rigSaving = items.reduce((sum, item) => sum + fuelNumber(entryRigSaving(item)), 0)
    const parsed = new Date(`${month}-01T00:00:00`)
    const monthLabel = Number.isNaN(parsed.getTime())
      ? month
      : parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short' })
    rows.push({
      month,
      month_label: monthLabel,
      day_count: items.length,
      opening_stock: opening,
      opening_adjustment: openingAdj,
      receipt,
      rig_engine_consumption: engine,
      company_consumption: company,
      total_consumption: totalAgo,
      book_closing_stock: opening + receipt - totalAgo,
      actual_closing_stock: fuelNumber(last.balance.actual_closing_stock),
      closing_adjustment: closingAdj,
      adjustments,
      rig_saving_litres: rigSaving,
    })
  }
  return rows.reverse()
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
    gas: entry?.rig_saving_litres ?? entry?.gas_consumption ?? '',
    gasRemarks: entry?.rig_saving_remarks ?? entry?.gas_remarks ?? '',
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
    lines: value.lines
      .filter(line => line.id || line.company_id || line.litres.trim() || line.remarks.trim())
      .map(line => ({
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
  const rigSaving = fuelNumber(draft.gas)
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
    gas: rigSaving,
    rigSaving,
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
  check('gas', draft.gas, 'Rig saving litres')
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
      'Record at least one of rig engine consumption, rig saving litres, a receipt, a closing stock or company consumption.',
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

/** Parse tab-separated company rows copied from Excel (`Company \t Litres` or `Company \t Category \t Litres \t Remarks`). */
export function parseFuelCompanyPaste(
  clipboardText: string,
  companies: FuelCompany[],
): { matched: FuelDraftLine[]; unmatched: string[] } {
  const active = companies.filter(company => !company.is_deleted)
  const byName = new Map<string, FuelCompany>()
  for (const company of active) {
    byName.set(company.company_name.trim().toLowerCase(), company)
    if (company.vendor_code) byName.set(company.vendor_code.trim().toLowerCase(), company)
  }
  const matched: FuelDraftLine[] = []
  const unmatched: string[] = []
  const rawRows = clipboardText.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')
  for (const rawRow of rawRows) {
    if (!rawRow.trim()) continue
    const cells = rawRow.split('\t').map(cell => cell.trim())
    if (cells.length < 2) continue
    // Skip an obvious header row from Excel.
    if (cells[0].toLowerCase() === 'company' && /litre|ago|usage/i.test(cells[1] + (cells[2] ?? ''))) continue
    const company = byName.get(cells[0].toLowerCase())
    if (!company) {
      unmatched.push(cells[0])
      continue
    }
    let categoryId = ''
    let litresText = ''
    let remarks = ''
    const cleanNum = (val: string) => val.replace(/,/g, '')
    if (cells.length === 2) {
      litresText = cleanNum(cells[1])
    } else {
      // Decide whether column 2 is a category name or litres directly.
      const secondAsNumber = Number(cleanNum(cells[1]))
      const catMatch = company.categories.find(
        cat => !cat.is_deleted && cat.category_name.trim().toLowerCase() === cells[1].toLowerCase(),
      )
      if (catMatch) {
        categoryId = catMatch.id
        litresText = cleanNum(cells[2] ?? '')
        remarks = cells[3] ?? ''
      } else if (cells[1] === '' && cells[2] !== '') {
        litresText = cleanNum(cells[2])
        remarks = cells[3] ?? ''
      } else if (Number.isFinite(secondAsNumber) && cells[1] !== '') {
        litresText = cleanNum(cells[1])
        remarks = cells.slice(2).join(' ')
      } else {
        unmatched.push(`${company.company_name} (${cells[1]})`)
        continue
      }
    }
    matched.push({
      key: fuelLineKey(),
      company_id: company.id,
      category_id: categoryId,
      litres: litresText,
      remarks,
      source: 'manual',
    })
  }
  return { matched, unmatched }
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
  const rigSavingValue = draft.gas.trim() || '0'
  return {
    rig_id: rigId,
    cost_date: costDate,
    rig_engine_consumption: draft.rigEngine.trim() || '0',
    rig_engine_remarks: draft.rigEngineRemarks.trim(),
    gas_consumption: rigSavingValue,
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
  'RIG SAVING (LITRES)',
  'RIG SAVING REMARKS',
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
  'RIG SAVING (LITRES)': '60',
  'RIG SAVING REMARKS': 'AGO saved through gas usage',
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

function pickCell(row: Record<string, string>, keys: string[]): string {
  const lowerMap = new Map<string, string>()
  for (const [k, v] of Object.entries(row)) {
    lowerMap.set(k.trim().toLowerCase(), v)
  }
  for (const key of keys) {
    const val = row[key] ?? lowerMap.get(key.toLowerCase())
    if (val !== undefined && String(val).trim() !== '') return String(val)
  }
  return ''
}

/** Map a spreadsheet row to the import API's lenient row contract (accepting both Rig Saving and legacy Gas headers). */
export function fuelImportRow(row: Record<string, string>) {
  const rigSaving = pickCell(row, [
    'RIG SAVING (LITRES)',
    'RIG SAVING LITRES',
    'GAS CONSUMPTION (LITRES)',
    'GAS CONSUMPTION',
  ])
  const rigSavingRemarks = pickCell(row, [
    'RIG SAVING REMARKS',
    'GAS REMARKS',
  ])
  return {
    rig_code: pickCell(row, ['RIG CODE']),
    cost_date: pickCell(row, ['DATE']),
    rig_engine_consumption: pickCell(row, ['RIG ENGINE CONSUMPTION (LITRES)', 'RIG ENGINE CONSUMPTION']),
    rig_engine_remarks: pickCell(row, ['RIG ENGINE REMARKS']),
    gas_consumption: rigSaving,
    gas_remarks: rigSavingRemarks,
    rig_saving_litres: rigSaving,
    rig_saving_remarks: rigSavingRemarks,
    opening_stock: pickCell(row, ['OPENING STOCK (LITRES)', 'OPENING STOCK']),
    opening_remarks: pickCell(row, ['OPENING REMARKS']),
    receipt_quantity: pickCell(row, ['RECEIPT (LITRES)', 'RECEIPT']),
    receipt_remarks: pickCell(row, ['RECEIPT REMARKS']),
    closing_stock: pickCell(row, ['ACTUAL CLOSING STOCK (LITRES)', 'ACTUAL CLOSING STOCK', 'CLOSING STOCK']),
    closing_remarks: pickCell(row, ['CLOSING REMARKS']),
    remarks: pickCell(row, ['DAY REMARKS', 'REMARKS']),
    company_name: pickCell(row, ['COMPANY', 'COMPANY NAME']),
    category_name: pickCell(row, ['CATEGORY', 'CATEGORY NAME']),
    litres: pickCell(row, ['COMPANY CONSUMPTION (LITRES)', 'COMPANY CONSUMPTION', 'LITRES']),
    line_remarks: pickCell(row, ['LINE REMARKS']),
  }
}

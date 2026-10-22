/**
 * LIH Cost Register API types and helpers (Daily Cost Management).
 *
 * The register is manual: a rig + well + date is chosen, and LIH items are
 * added one by one. Each item's total is computed by the server as
 * no_of_units × unit_cost, and the day's total is the sum of its items. That
 * cost is added to the actual cost and deducted from the AFE amount in the
 * daily sheet, cost analysis and printed reports.
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
export type LihCostReference = {
  rigs: LihCostRigOption[]; wells: LihCostWellOption[]; afes: LihCostAfeOption[]
  uoms: LihCostUomOption[]; default_currency: string
}

/** One manually entered LIH item. `total_cost` is always computed by the system. */
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
  display_name: string
  is_deleted: boolean
  deleted_at: string | null
  created_by: string; updated_by: string
  created_at: string; updated_at: string
}

export type LihCostDay = { entry: LihCostEntry; lines: LihCostLine[] }
export type LihCostCurrencyTotal = { currency: string; total: string; line_count: number; entry_count: number }
export type LihCostReport = {
  well_id: string; well_code: string; well_name: string
  from_date: string | null; to_date: string | null
  currency: string; total: string; line_count: number; entry_count: number
  totals: LihCostCurrencyTotal[]
  days: LihCostDay[]
}

/** Editable item payload; the server recomputes the total from units × unit cost. */
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

/** Blank optional numbers are sent as null, so the API can store a real NULL. */
export function lihLinePayload(line: LihCostLineInput) {
  const optional = (value: string) => {
    const trimmed = value.trim()
    return trimmed === '' ? null : trimmed
  }
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

/** The item total exactly as the server computes it: units × unit cost, 2 dp. */
export function lihLineTotal(line: Pick<LihCostLineInput, 'no_of_units' | 'unit_cost'>): number {
  const units = Number(line.no_of_units)
  const cost = Number(line.unit_cost)
  if (!Number.isFinite(units) || !Number.isFinite(cost)) return 0
  return Math.round(units * cost * 100) / 100
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

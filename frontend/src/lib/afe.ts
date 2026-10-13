// AFE Management contracts, formatting and client-side line checks.
// Decimal values arrive from the API as strings; money is shown with two decimals.
// Server rules are authoritative. The client checks here only keep obvious mistakes out of preview.

export type AfeStatus = 'draft' | 'submitted' | 'review' | 'approval'
export type AfeStatusAction = 'submit' | 'review' | 'approve' | 'reopen'
export type AfeType = 'Drilling' | 'Completion'
export type ChargingBasis = 'Day Rate' | 'Per Service Rate' | 'Per Section Rate'
export type ChargeCategory =
  | 'Mobilization'
  | 'Demobilization'
  | 'Operation'
  | 'Standby'
  | 'Personnel-Operation'
  | 'Personnel-Standby'
  | 'Fixed Charge'
  | 'Others'
export type ConsumableCategory = 'Mud Chemicals' | 'Cement Additives' | 'Fuel' | 'Drill Bits'
export type QuantityUnit = 'days' | 'hours'

export const AFE_TYPES: AfeType[] = ['Drilling', 'Completion']
export const CHARGING_BASES: ChargingBasis[] = ['Day Rate', 'Per Service Rate', 'Per Section Rate']
export const CHARGE_CATEGORIES: ChargeCategory[] = [
  'Mobilization', 'Demobilization', 'Operation', 'Standby', 'Personnel-Operation', 'Personnel-Standby', 'Fixed Charge', 'Others',
]
export const ONE_TIME_CATEGORIES: ChargeCategory[] = ['Mobilization', 'Demobilization', 'Fixed Charge']
export const LUMP_SUM_CATEGORIES: ConsumableCategory[] = ['Mud Chemicals', 'Cement Additives', 'Fuel']
export const CONSUMABLE_CATEGORIES: ConsumableCategory[] = [...LUMP_SUM_CATEGORIES, 'Drill Bits']

export const STATUS_LABEL: Record<AfeStatus, string> = {
  draft: 'Draft', submitted: 'Submitted', review: 'Review', approval: 'Approval',
}
export const STATUS_TONE: Record<AfeStatus, 'neutral' | 'info' | 'warning' | 'success'> = {
  draft: 'neutral', submitted: 'info', review: 'warning', approval: 'success',
}

// Status moves are offered only from the AFE Cost Estimation tab and the estimate workspace.
export const STATUS_ACTIONS: Record<AfeStatusAction, {
  label: string; title: string; description: string; from: AfeStatus[]; to: AfeStatus; permission: string; remarksRequired: boolean
}> = {
  submit: {
    label: 'Submit', title: 'Submit AFE for review?',
    description: 'The estimate becomes read-only and the AFE moves to Submitted. Save the latest estimate before submitting.',
    from: ['draft'], to: 'submitted', permission: 'afe:submit', remarksRequired: false,
  },
  review: {
    label: 'Start review', title: 'Start AFE review?',
    description: 'The AFE moves to Review. Reviewers may reopen it as Draft with remarks.',
    from: ['submitted'], to: 'review', permission: 'afe:review', remarksRequired: false,
  },
  approve: {
    label: 'Approve', title: 'Approve this AFE?',
    description: 'Approval records the AFE as authorised. Add remarks that explain the approval.',
    from: ['review'], to: 'approval', permission: 'afe:approve', remarksRequired: true,
  },
  reopen: {
    label: 'Reopen as Draft', title: 'Reopen AFE as Draft?',
    description: 'The estimate becomes editable again. Give the reason; it is recorded in the audit trail.',
    from: ['submitted', 'review', 'approval'], to: 'draft', permission: 'afe:reopen', remarksRequired: true,
  },
}

export function nextActions(status: AfeStatus): AfeStatusAction[] {
  return (Object.keys(STATUS_ACTIONS) as AfeStatusAction[]).filter(action => STATUS_ACTIONS[action].from.includes(status))
}

// ---------------------------------------------------------------------------
// Responses
// ---------------------------------------------------------------------------

export type CurrencyTotal = { currency: string; amount: string }

export type Afe = {
  configuration_scope: 'drilling' | 'completion'
  id: string
  rig_id: string
  rig_code: string
  rig_name: string
  well_id: string
  well_code: string
  well_name: string
  well_status: string
  afe_code: string
  afe_name: string
  afe_type: AfeType
  remarks: string
  status: AfeStatus
  status_remarks: string
  status_changed_at: string | null
  status_changed_by: string
  estimate_saved_at: string | null
  estimate_saved_by: string
  service_count: number
  consumable_count: number
  tangible_count: number
  // Converted figures in the standard currency. Null while a conversion rate is still missing.
  services_total: string | null
  consumables_total: string | null
  tangibles_total: string | null
  total_cost: string | null
  standard_currency: string
  conversion_pending: boolean
  totals_by_currency: CurrencyTotal[]
  warning_count: number
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type AfeComponent = {
  group: string
  category: string
  description: string
  amount: string
  section_id: string | null
  section_label: string
  phase_id: string | null
  phase_label: string
  quantity: string | null
  rate: string | null
  unit: string
}

export type ServiceLineOut = {
  id: string | null
  client_key: string | null
  service_id: string
  service_code: string
  service_name: string
  service_category: string
  provider_type: string
  vendor_name: string
  charging_basis: ChargingBasis
  hole_section_id: string | null
  section_label: string
  phase_id: string | null
  phase_label: string
  currency: string
  service_amount: string
  remarks: string
  rates: { category: ChargeCategory; unit_rate: string }[]
  charges: { category: ChargeCategory; quantity: string; quantity_unit: QuantityUnit }[]
  section_rates: { hole_section_id: string; section_label: string; phase_id: string | null; phase_label: string; amount: string }[]
  amount: string
  warnings: string[]
  components: AfeComponent[]
}

export type ConsumableLineOut = {
  id: string | null
  client_key: string | null
  category: ConsumableCategory
  hole_section_id: string
  section_label: string
  phase_id: string | null
  phase_label: string
  drill_bit_id: string | null
  bit_code: string
  bit_name: string
  bit_type: string
  manufacturer: string
  model_no: string
  size: string
  iadc_code: string
  serial_number: string
  bit_description: string
  quantity: string
  captured_rate: string
  override_rate: string | null
  effective_rate: string | null
  estimated_amount: string | null
  currency: string
  remarks: string
  amount: string
  warnings: string[]
  components: AfeComponent[]
}

export type TangibleLineOut = {
  id: string | null
  client_key: string | null
  tangible_id: string
  tangible_code: string
  tangible_name: string
  tangible_scope: string
  category_name: string
  subcategory_name: string
  manufacturer_name: string
  tangible_description: string
  uom: string
  quantity: string
  captured_rate: string
  override_rate: string | null
  effective_rate: string
  currency: string
  remarks: string
  amount: string
  warnings: string[]
  components: AfeComponent[]
}

export type SectionSummary = {
  hole_section_id: string | null
  label: string
  planned_days: string
  services: string | null
  consumables: string | null
  tangibles: string | null
  total: string | null
}

export type CurrencySetup = {
  standard_currency: string
  currencies: string[]
  multi_currency: boolean
  converted: boolean
  standard_missing: boolean
  missing_rates: string[]
  exchange_rates: { currency_code: string; rate: string }[]
}

export type EstimateSummary = {
  services_total: string | null
  consumables_total: string | null
  tangibles_total: string | null
  total: string | null
  totals_by_currency: CurrencyTotal[]
  currency: CurrencySetup
  by_section: SectionSummary[]
  warnings: string[]
}

export type WellScope = {
  scope: 'drilling' | 'completion'
  well_id: string
  well_code: string
  well_name: string
  well_location: string
  block: string
  objective: string
  rig_code: string
  rig_name: string
  depth_unit: string
  status: string
  config_status: string
  total_depth: string | null
  total_days: string
  sections: {
    hole_section_id: string
    section_code: string
    section_name: string
    from_depth: string
    to_depth: string
    total_days: string
    phases: { phase_id: string; phase_code: string; phase_name: string; days: string }[]
  }[]
}

export type AfeEstimate = {
  afe: Afe
  well: WellScope
  services: ServiceLineOut[]
  consumables: ConsumableLineOut[]
  tangibles: TangibleLineOut[]
  summary: EstimateSummary
  persisted: boolean
  saved_at: string | null
  saved_by: string
}

export type AfeOverview = {
  active_afes: number
  deleted_afes: number
  drilling_afes: number
  completion_afes: number
  approved_afes: number
  wells_with_afes: number
  totals_by_currency: CurrencyTotal[]
  approved_by_currency: CurrencyTotal[]
  conversion_pending_afes: number
  statuses: { status: AfeStatus; label: string; count: number }[]
  top_wells: { well_id: string; label: string; total: string; currency: string }[]
  warning_afes: number
  recent_activity: { id: string; action: string; entity_type: string; entity_label: string; summary: string; created_at: string }[]
}

export type ImportResponse = { imported_count: number; error_count: number; errors: string[]; success: boolean }

export type AfeReference = {
  rigs: { id: string; rig_code: string; rig_name: string; display_name: string }[]
  wells: {
    completion_config_status: string
    completion_status: string
    completion_section_count: number
    id: string; rig_id: string; well_code: string; well_name: string; display_name: string; status: string
    config_status: string; total_days: string; total_depth: string | null; depth_unit: string; section_count: number
  }[]
  services: {
    id: string; service_code: string; service_name: string; service_category: string; provider_type: string
    vendor_name: string; display_name: string; description: string
  }[]
  tangibles: {
    id: string; tangible_code: string; tangible_name: string; scope: string; category_name: string; subcategory_name: string
    manufacturer_name: string; description: string; uom: string; unit_rate: string; final_cost: string | null
    captured_rate: string; currency: string; display_name: string
  }[]
  drill_bits: {
    id: string; bit_code: string; bit_name: string; bit_type: string; manufacturer_name: string; model_no: string; size: string
    iadc_code: string; serial_number: string; description: string; captured_rate: string; currency: string; display_name: string
  }[]
  currencies: { code: string; name: string; symbol: string }[]
  afe_types: string[]
  charging_bases: string[]
  charge_categories: string[]
  one_time_categories: string[]
  consumable_categories: string[]
  statuses: string[]
}

// ---------------------------------------------------------------------------
// Estimate request shapes (what the estimate editor sends)
// ---------------------------------------------------------------------------

export type ServiceLineInput = {
  client_key: string
  service_id: string
  charging_basis: ChargingBasis
  hole_section_id: string | null
  phase_id: string | null
  currency: string
  service_amount: string
  remarks: string
  rates: { category: ChargeCategory; unit_rate: string }[]
  charges: { category: ChargeCategory; quantity: string; quantity_unit: QuantityUnit }[]
  section_rates: { hole_section_id: string; phase_id: string | null; amount: string }[]
}

export type ConsumableLineInput = {
  client_key: string
  category: ConsumableCategory
  hole_section_id: string
  phase_id: string | null
  drill_bit_id: string | null
  quantity: string
  override_rate: string | null
  estimated_amount: string | null
  currency: string
  remarks: string
}

export type TangibleLineInput = {
  client_key: string
  tangible_id: string
  quantity: string
  override_rate: string | null
  remarks: string
}

export type ExchangeRateInput = { currency_code: string; rate: string }

export type EstimateInput = {
  services: ServiceLineInput[]
  consumables: ConsumableLineInput[]
  tangibles: TangibleLineInput[]
  // Used only when the estimate mixes currencies. Each rate is units of the standard currency per one foreign unit.
  standard_currency: string
  exchange_rates: ExchangeRateInput[]
}

export const newKey = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`

export function emptyServiceLine(basis: ChargingBasis = 'Day Rate'): ServiceLineInput {
  return {
    client_key: newKey(), service_id: '', charging_basis: basis, hole_section_id: null, phase_id: null,
    currency: '', service_amount: '0', remarks: '', rates: [], charges: [], section_rates: [],
  }
}

export function emptyConsumableLine(category: ConsumableCategory = 'Mud Chemicals'): ConsumableLineInput {
  return {
    client_key: newKey(), category, hole_section_id: '', phase_id: null, drill_bit_id: null,
    quantity: '1', override_rate: null, estimated_amount: null, currency: '', remarks: '',
  }
}

export function emptyTangibleLine(): TangibleLineInput {
  return { client_key: newKey(), tangible_id: '', quantity: '1', override_rate: null, remarks: '' }
}

// Converts a saved or previewed estimate back into request shape, so the editor can resume it exactly.
export function estimateToInput(estimate: AfeEstimate): EstimateInput {
  return {
    standard_currency: estimate.summary.currency.standard_currency,
    exchange_rates: estimate.summary.currency.exchange_rates.map(rate => ({ currency_code: rate.currency_code, rate: rate.rate })),
    services: estimate.services.map(line => ({
      client_key: line.client_key ?? line.id ?? newKey(),
      service_id: line.service_id,
      charging_basis: line.charging_basis,
      hole_section_id: line.hole_section_id,
      phase_id: line.phase_id,
      currency: line.currency,
      service_amount: line.service_amount,
      remarks: line.remarks,
      rates: line.rates.map(rate => ({ category: rate.category, unit_rate: rate.unit_rate })),
      charges: line.charges.map(charge => ({ category: charge.category, quantity: charge.quantity, quantity_unit: charge.quantity_unit })),
      section_rates: line.section_rates.map(rate => ({ hole_section_id: rate.hole_section_id, phase_id: rate.phase_id, amount: rate.amount })),
    })),
    consumables: estimate.consumables.map(line => ({
      client_key: line.client_key ?? line.id ?? newKey(),
      category: line.category,
      hole_section_id: line.hole_section_id,
      phase_id: line.phase_id,
      drill_bit_id: line.drill_bit_id,
      quantity: line.quantity,
      override_rate: line.override_rate,
      estimated_amount: line.estimated_amount,
      currency: line.currency,
      remarks: line.remarks,
    })),
    tangibles: estimate.tangibles.map(line => ({
      client_key: line.client_key ?? line.id ?? newKey(),
      tangible_id: line.tangible_id,
      quantity: line.quantity,
      override_rate: line.override_rate,
      remarks: line.remarks,
    })),
  }
}

// Stable JSON so two equal estimates always compare equal regardless of property order.
export function stableJson(value: unknown): string {
  return JSON.stringify(value, (_key, item) => {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      return Object.keys(item).sort().reduce<Record<string, unknown>>((sorted, key) => {
        sorted[key] = (item as Record<string, unknown>)[key]
        return sorted
      }, {})
    }
    return item
  })
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export function toNumber(value: string | number | null | undefined): number {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

export function amountText(value: string | number | null | undefined, currency = ''): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '—'
  const text = parsed.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return currency ? `${currency} ${text}` : text
}

export function totalsText(totals: CurrencyTotal[]): string {
  if (!totals.length) return '—'
  return totals.map(item => amountText(item.amount, item.currency)).join(' · ')
}

// The AFE total in its standard currency, or a plain notice while a conversion rate is missing.
export function afeTotalText(afe: Pick<Afe, 'total_cost' | 'standard_currency' | 'totals_by_currency' | 'conversion_pending'>): string {
  if (afe.conversion_pending) return 'Pending conversion'
  if (afe.total_cost === null) return '—'
  return afe.standard_currency ? amountText(afe.total_cost, afe.standard_currency) : totalsText(afe.totals_by_currency)
}

export function daysText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${parsed.toLocaleString(undefined, { maximumFractionDigits: 4 })} d` : '—'
}

// Day quantities can be entered in days or hours (hours convert at 24 per day).
export function toDays(quantity: string, unit: QuantityUnit): number {
  const parsed = toNumber(quantity)
  return unit === 'hours' ? parsed / 24 : parsed
}

export function sectionOptions(scope: WellScope | null | undefined) {
  return (scope?.sections ?? []).map(section => ({
    id: section.hole_section_id,
    label: `${section.section_code} · ${section.section_name}`,
    days: section.total_days,
    phases: section.phases,
  }))
}

// One row per section, or per phase where the section has phases. Used by per-section
// rates and bulk estimation, so each amount lands on exactly one (section, phase) pair.
export type ScopeRow = { key: string; sectionId: string; phaseId: string | null; section: string; phase: string; days: string }

export function scopeRows(scope: WellScope | null | undefined): ScopeRow[] {
  return (scope?.sections ?? []).flatMap((section): ScopeRow[] => {
    const label = `${section.section_code} · ${section.section_name}`
    if (!section.phases.length) {
      return [{ key: `${section.hole_section_id}|`, sectionId: section.hole_section_id, phaseId: null, section: label, phase: 'No phase', days: section.total_days }]
    }
    return section.phases.map(phase => ({
      key: `${section.hole_section_id}|${phase.phase_id}`,
      sectionId: section.hole_section_id,
      phaseId: phase.phase_id,
      section: label,
      phase: `${phase.phase_code} · ${phase.phase_name}`,
      days: phase.days,
    }))
  })
}

export function phaseOptions(scope: WellScope | null | undefined, sectionId: string | null) {
  const section = scope?.sections.find(item => item.hole_section_id === sectionId)
  return (section?.phases ?? []).map(phase => ({ id: phase.phase_id, label: `${phase.phase_code} · ${phase.phase_name}`, days: phase.days }))
}

// ---------------------------------------------------------------------------
// Client checks. They mirror the server rules that are cheap to know up front.
// A line with problems is kept out of preview and blocks Save until it is fixed.
// ---------------------------------------------------------------------------

// Numbers are typed as text. Anything that is not a plain decimal is reported on the line, not sent.
export function isDecimalText(value: string | null | undefined): boolean {
  return value === null || value === undefined || value === '' || /^\d+(\.\d+)?$/.test(value)
}

export function serviceProblems(line: ServiceLineInput): string[] {
  const problems: string[] = []
  if (!line.service_id) problems.push('Select a service.')
  if (!line.currency) problems.push('Select the currency.')
  if (!isDecimalText(line.service_amount) || line.rates.some(rate => !isDecimalText(rate.unit_rate)) || line.charges.some(charge => !isDecimalText(charge.quantity))
    || line.section_rates.some(rate => !isDecimalText(rate.amount))) {
    problems.push('Numbers must be plain decimals such as 12 or 0.73.')
  }
  if (line.charging_basis === 'Day Rate') {
    if (!line.rates.some(rate => toNumber(rate.unit_rate) > 0)) problems.push('Enter at least one unit rate for a day-rate service.')
  }
  if (line.charging_basis === 'Per Service Rate') {
    if (!line.hole_section_id) problems.push('Choose the section for a per-service charge.')
    if (toNumber(line.service_amount) <= 0) problems.push('Enter the per-service amount.')
  }
  if (line.charging_basis === 'Per Section Rate') {
    if (!line.section_rates.some(rate => toNumber(rate.amount) > 0)) problems.push('Enter a rate for at least one section.')
  }
  return problems
}

export function consumableProblems(line: ConsumableLineInput): string[] {
  const problems: string[] = []
  if (!line.hole_section_id) problems.push('Select the hole section.')
  if (!isDecimalText(line.quantity) || !isDecimalText(line.override_rate) || !isDecimalText(line.estimated_amount)) {
    problems.push('Numbers must be plain decimals such as 12 or 0.73.')
  }
  if (line.category === 'Drill Bits') {
    if (!line.drill_bit_id) problems.push('Select a drill bit from Master Data.')
    if (toNumber(line.quantity) <= 0) problems.push('Enter the number of bits.')
    if (line.estimated_amount !== null) problems.push('Drill bits are priced per bit; remove the estimated amount.')
  } else {
    if (line.estimated_amount === null || line.estimated_amount === '') problems.push('Enter the estimated amount.')
    if (!line.currency) problems.push('Select the currency.')
  }
  return problems
}

export function tangibleProblems(line: TangibleLineInput): string[] {
  const problems: string[] = []
  if (!line.tangible_id) problems.push('Select a tangible from Master Data.')
  if (!isDecimalText(line.quantity) || !isDecimalText(line.override_rate)) problems.push('Numbers must be plain decimals such as 12 or 0.73.')
  if (toNumber(line.quantity) < 0) problems.push('Quantity cannot be negative.')
  return problems
}

export function remarksProblem(action: AfeStatusAction, remarks: string): string {
  const required = STATUS_ACTIONS[action].remarksRequired
  if (required && remarks.trim().length < 3) return 'Enter remarks of at least 3 characters.'
  return ''
}

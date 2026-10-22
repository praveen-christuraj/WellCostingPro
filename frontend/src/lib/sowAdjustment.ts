// AFE SOW adjustments and well plan adjustments: contracts and API helpers.
//
// Adjustments revise approved estimates and configured plans without rewriting
// them, and are entered through the same modules as the records they revise:
// the section/phase grid for a plan, the service/consumable/tangible estimate
// lines for an AFE. Every revision stores both sides of the entry — `before`
// snapshots the entered values, `after` holds the revised ones — linked by
// `pair_key` so each revised line reads against the value it replaces. Planned
// days, section counts and cost totals are derived server-side from the lines.
// Only the latest approved revision per AFE (or per well and scope) affects
// cost comparisons.

import { api, body } from './api'
import type {
  ConsumableLineInput,
  ConsumableLineOut,
  EstimateSummary,
  ExchangeRateInput,
  ServiceLineInput,
  ServiceLineOut,
  TangibleLineInput,
  TangibleLineOut,
} from './afe'

export type SowStatus = 'draft' | 'approved' | 'void'
export type AdjustmentScope = 'drilling' | 'completion'
export type LineSide = 'before' | 'after'
export type LineChange = 'kept' | 'modified' | 'added' | 'removed'

// ---------------------------------------------------------------------------
// Well plan adjustment — the well-configuration grid, entered as a revision
// ---------------------------------------------------------------------------

export type PlanPhaseEntry = {
  pair_key: string | null
  phase_id: string
  days: string
  remarks: string
}

export type PlanSectionEntry = {
  pair_key: string | null
  hole_section_id: string
  from_depth: string
  to_depth: string
  remarks: string
  phases: PlanPhaseEntry[]
}

export type PlanPhaseRow = {
  pair_key: string
  plan_side: LineSide
  phase_id: string
  phase_code: string
  phase_name: string
  days: string
  remarks: string
  change: LineChange
}

export type PlanSectionRow = {
  pair_key: string
  plan_side: LineSide
  hole_section_id: string
  section_code: string
  section_name: string
  from_depth: string
  to_depth: string
  remarks: string
  total_days: string
  change: LineChange
  phases: PlanPhaseRow[]
}

export type WellPlanAdjustment = {
  id: string
  well_id: string
  configuration_scope: AdjustmentScope
  revision_number: number
  status: SowStatus
  reason: string
  sow_summary: string
  planned_days_before: string
  planned_days_after: string
  delta_days: string
  section_count_before: number
  section_count_after: number
  sections_before: PlanSectionRow[]
  sections_after: PlanSectionRow[]
  depth_unit: string
  well_code: string
  well_name: string
  created_by: string
  approved_by: string
  approved_at: string | null
  created_at: string
  updated_at: string
}

export type WellPlanAdjustmentInput = {
  configuration_scope?: AdjustmentScope
  reason: string
  sow_summary?: string
  sections: PlanSectionEntry[]
}

// ---------------------------------------------------------------------------
// AFE SOW adjustment — the AFE estimate modules, entered as a revision
// ---------------------------------------------------------------------------

export type SowServiceLineInput = ServiceLineInput & { pair_key: string | null }
export type SowConsumableLineInput = ConsumableLineInput & { pair_key: string | null }
export type SowTangibleLineInput = TangibleLineInput & { pair_key: string | null }

export type AfeSowLinesInput = {
  standard_currency: string
  exchange_rates: ExchangeRateInput[]
  services: SowServiceLineInput[]
  consumables: SowConsumableLineInput[]
  tangibles: SowTangibleLineInput[]
}

export type AfeSowAdjustmentInput = AfeSowLinesInput & {
  reason: string
  sow_summary?: string
}

export type AfeSowBundle = {
  services: ServiceLineOut[]
  consumables: ConsumableLineOut[]
  tangibles: TangibleLineOut[]
  summary: EstimateSummary
}

export type AfeSowAdjustment = {
  id: string
  afe_id: string
  well_id: string
  rig_id: string
  configuration_scope: AdjustmentScope
  revision_number: number
  status: SowStatus
  reason: string
  sow_summary: string
  standard_currency: string
  original_services_total: string | null
  original_consumables_total: string | null
  original_tangibles_total: string | null
  original_total: string | null
  adjusted_services_total: string
  adjusted_consumables_total: string
  adjusted_tangibles_total: string
  adjusted_total: string
  delta_total: string
  before: AfeSowBundle | null
  after: AfeSowBundle | null
  afe_code: string
  afe_name: string
  well_code: string
  well_name: string
  created_by: string
  approved_by: string
  approved_at: string | null
  created_at: string
  updated_at: string
}

export type AfeSowAdjustmentPreview = {
  standard_currency: string
  services: ServiceLineOut[]
  consumables: ConsumableLineOut[]
  tangibles: TangibleLineOut[]
  summary: EstimateSummary
  adjusted_services_total: string
  adjusted_consumables_total: string
  adjusted_tangibles_total: string
  adjusted_total: string
}

export type DailyCostAmendment = {
  id: string
  entry_id: string
  well_id: string
  afe_id: string
  amendment_number: number
  cost_date: string
  days_after_cost_date: number
  reason: string
  reopened_by: string
  reopened_at: string
  created_at: string
}

export const SOW_STATUS_LABEL: Record<SowStatus, string> = {
  draft: 'Draft',
  approved: 'Approved',
  void: 'Void',
}

export const SOW_STATUS_TONE: Record<SowStatus, 'neutral' | 'success' | 'error'> = {
  draft: 'neutral',
  approved: 'success',
  void: 'error',
}

export const SOW_CHANGE_LABEL: Record<LineChange, string> = {
  kept: 'Unchanged',
  modified: 'Modified',
  added: 'New',
  removed: 'Removed',
}

export const SOW_CHANGE_TONE: Record<LineChange, 'neutral' | 'info' | 'success' | 'error'> = {
  kept: 'neutral',
  modified: 'info',
  added: 'success',
  removed: 'error',
}

export function listAfeAdjustments(afeId: string): Promise<AfeSowAdjustment[]> {
  return api<AfeSowAdjustment[]>(`/afe/afes/${afeId}/sow-adjustments`)
}

export function previewAfeAdjustment(afeId: string, data: AfeSowAdjustmentInput): Promise<AfeSowAdjustmentPreview> {
  return api<AfeSowAdjustmentPreview>(`/afe/afes/${afeId}/sow-adjustments/preview`, { method: 'POST', body: body(data) })
}

export function createAfeAdjustment(afeId: string, data: AfeSowAdjustmentInput): Promise<AfeSowAdjustment> {
  return api<AfeSowAdjustment>(`/afe/afes/${afeId}/sow-adjustments`, { method: 'POST', body: body(data) })
}

export function updateAfeAdjustment(adjustmentId: string, data: Partial<AfeSowAdjustmentInput>): Promise<AfeSowAdjustment> {
  return api<AfeSowAdjustment>(`/afe/sow-adjustments/${adjustmentId}`, { method: 'PATCH', body: body(data) })
}

export function approveAfeAdjustment(adjustmentId: string, remarks: string): Promise<AfeSowAdjustment> {
  return api<AfeSowAdjustment>(`/afe/sow-adjustments/${adjustmentId}/approve`, { method: 'POST', body: body({ remarks }) })
}

export function voidAfeAdjustment(adjustmentId: string, remarks: string): Promise<AfeSowAdjustment> {
  return api<AfeSowAdjustment>(`/afe/sow-adjustments/${adjustmentId}/void`, { method: 'POST', body: body({ remarks }) })
}

export function listWellPlanAdjustments(wellId: string, scope?: AdjustmentScope): Promise<WellPlanAdjustment[]> {
  const query = scope ? `?scope=${scope}` : ''
  return api<WellPlanAdjustment[]>(`/rig-well/wells/${wellId}/plan-adjustments${query}`)
}

export function createWellPlanAdjustment(wellId: string, data: WellPlanAdjustmentInput): Promise<WellPlanAdjustment> {
  return api<WellPlanAdjustment>(`/rig-well/wells/${wellId}/plan-adjustments`, { method: 'POST', body: body(data) })
}

export function updateWellPlanAdjustment(adjustmentId: string, data: Partial<WellPlanAdjustmentInput>): Promise<WellPlanAdjustment> {
  return api<WellPlanAdjustment>(`/rig-well/plan-adjustments/${adjustmentId}`, { method: 'PATCH', body: body(data) })
}

export function approveWellPlanAdjustment(adjustmentId: string, remarks: string): Promise<WellPlanAdjustment> {
  return api<WellPlanAdjustment>(`/rig-well/plan-adjustments/${adjustmentId}/approve`, { method: 'POST', body: body({ remarks }) })
}

export function voidWellPlanAdjustment(adjustmentId: string, remarks: string): Promise<WellPlanAdjustment> {
  return api<WellPlanAdjustment>(`/rig-well/plan-adjustments/${adjustmentId}/void`, { method: 'POST', body: body({ remarks }) })
}

export function listEntryAmendments(entryId: string): Promise<DailyCostAmendment[]> {
  return api<DailyCostAmendment[]>(`/daily-cost/entries/${entryId}/amendments`)
}

export function adjustmentDeltaText(value: string | number | null | undefined, currency = ''): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '—'
  const sign = parsed > 0 ? '+' : ''
  const text = `${sign}${parsed.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  return currency ? `${currency} ${text}` : text
}

// Summarises the two-sided revision lists into per-side change counts, so a
// history card can say what the revision did without rendering every line.
export function changeCounts(rows: { change: LineChange }[]): Record<LineChange, number> {
  const counts: Record<LineChange, number> = { kept: 0, modified: 0, added: 0, removed: 0 }
  for (const row of rows) counts[row.change] = (counts[row.change] ?? 0) + 1
  return counts
}

// Pairs the priced before/after estimate lines by their shared pair key
// (carried in `client_key`) and derives the per-line change, so the revision
// history reads every revised value against the value it replaces.
export type PairedSowLine = {
  pair_key: string
  change: LineChange
  before_amount: string | null
  after_amount: string | null
  label: string
}

function lineLabel(kind: 'service' | 'consumable' | 'tangible', line: ServiceLineOut | ConsumableLineOut | TangibleLineOut): string {
  if (kind === 'service') return `${(line as ServiceLineOut).service_code} · ${(line as ServiceLineOut).service_name}`
  if (kind === 'tangible') return `${(line as TangibleLineOut).tangible_code} · ${(line as TangibleLineOut).tangible_name}`
  const consumable = line as ConsumableLineOut
  return consumable.category === 'Drill Bits'
    ? `${consumable.bit_code} · ${consumable.bit_name}`
    : consumable.category
}

export function pairSowLines(
  kind: 'service' | 'consumable' | 'tangible',
  before: (ServiceLineOut | ConsumableLineOut | TangibleLineOut)[],
  after: (ServiceLineOut | ConsumableLineOut | TangibleLineOut)[],
): PairedSowLine[] {
  const rows: PairedSowLine[] = []
  const afterByKey = new Map(after.map(line => [line.client_key ?? line.id ?? '', line]))
  const seen = new Set<string>()
  for (const line of before) {
    const key = line.client_key ?? line.id ?? ''
    const match = afterByKey.get(key)
    seen.add(key)
    const beforeAmount = String(line.amount ?? '0')
    const afterAmount = match ? String(match.amount ?? '0') : null
    const changed = !match
      || Number(beforeAmount) !== Number(afterAmount)
      || (line.remarks || '') !== (match.remarks || '')
    rows.push({
      pair_key: key,
      change: match ? (changed ? 'modified' : 'kept') : 'removed',
      before_amount: beforeAmount,
      after_amount: afterAmount,
      label: lineLabel(kind, match ?? line),
    })
  }
  for (const line of after) {
    const key = line.client_key ?? line.id ?? ''
    if (seen.has(key)) continue
    rows.push({
      pair_key: key,
      change: 'added',
      before_amount: null,
      after_amount: String(line.amount ?? '0'),
      label: lineLabel(kind, line),
    })
  }
  return rows
}

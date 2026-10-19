// AFE SOW adjustments and well plan adjustments: contracts and API helpers.
// Adjustments revise approved estimates and configured plans without rewriting
// them. Only the latest approved revision per AFE (or per well and scope)
// affects cost comparisons.

import { api, body } from './api'

export type SowStatus = 'draft' | 'approved' | 'void'
export type AdjustmentScope = 'drilling' | 'completion'

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

export type AfeSowAdjustmentInput = {
  reason: string
  sow_summary?: string
  adjusted_services_total: string
  adjusted_consumables_total: string
  adjusted_tangibles_total: string
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
  planned_days_after: string
  section_count_after?: number
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

export function listAfeAdjustments(afeId: string): Promise<AfeSowAdjustment[]> {
  return api<AfeSowAdjustment[]>(`/afe/afes/${afeId}/sow-adjustments`)
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

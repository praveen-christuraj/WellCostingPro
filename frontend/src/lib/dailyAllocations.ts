import { DAILY_ONE_TIME_CATEGORIES, deriveClassification, type DailyCostBaseline, type DailyCostReference, type DailyCostServiceInput } from './dailyCost'

export type ActivityAllocation = {
  activity_id: string
  sub_activity_id: string
  hole_section_id: string
  phase_id: string
  hours: string
  actual_depth: string
  actual_depth_unit: 'm' | 'ft'
}

export function allocationErrors(rows: ActivityAllocation[], reference: DailyCostReference, wellId: string, scope: string, timeBased = true): string[] {
  const errors: string[] = []
  if (!rows.length) errors.push('Add at least one activity allocation.')
  rows.forEach((row, index) => {
    if (!reference.sub_activities.some(sub => sub.id === row.sub_activity_id && sub.activity_id === row.activity_id && sub.well_id === wellId && (sub.scope ?? 'drilling') === scope)) errors.push(`Allocation ${index + 1}: choose an activity and matching well sub activity.`)
    if (timeBased && (!Number.isFinite(Number(row.hours)) || Number(row.hours) <= 0)) errors.push(`Allocation ${index + 1}: enter positive working hours.`)
    if (row.actual_depth !== '' && (!Number.isFinite(Number(row.actual_depth)) || Number(row.actual_depth) < 0)) errors.push(`Allocation ${index + 1}: depth must be non-negative.`)
  })
  if (timeBased && rows.reduce((sum, row) => sum + Number(row.hours), 0) > 24 + 1e-10) errors.push('Allocated working hours cannot exceed 24 per service for the day.')
  return errors
}

/** Expand only time-based charges. One-time and section/service charges stay whole. */
export function allocateService(line: DailyCostServiceInput, rows: ActivityAllocation[], baseline: DailyCostBaseline, reference: DailyCostReference): DailyCostServiceInput[] {
  if (!rows.length) {
    if (line.charging_basis === 'Per Section Rate') return [{ ...line, quantity: line.id && line.quantity_unit === 'section' ? line.quantity : '1', quantity_unit: 'section' }]
    if (line.charging_basis === 'Per Service Rate') return [{ ...line, quantity: line.id && line.quantity_unit === 'service' ? line.quantity : '1', quantity_unit: 'service' }]
    if (DAILY_ONE_TIME_CATEGORIES.includes(line.charge_category as typeof DAILY_ONE_TIME_CATEGORIES[number])) return [{ ...line, quantity: '1', quantity_unit: 'unit' }]
    return [line]
  }
  const timed = line.charging_basis === 'Day Rate' && !DAILY_ONE_TIME_CATEGORIES.includes(line.charge_category as typeof DAILY_ONE_TIME_CATEGORIES[number])
  if (timed && rows.length > 1 && line.cost_items?.length) throw new Error('Remove manual cost items before splitting a service by hours; manual totals cannot be duplicated across activities.')
  return (timed ? rows : rows.slice(0, 1)).map((row, index) => {
    const planned = deriveClassification(reference.activities.find(activity => activity.id === row.activity_id)) === 'Planned'
    const sub = reference.sub_activities.find(item => item.id === row.sub_activity_id)
    const currentRate = baseline.service_rates.find(rate => rate.id === line.baseline_service_rate_id)
    const matchingRate = currentRate && baseline.service_rates.find(rate => rate.is_current !== false && rate.service_id === line.service_id && rate.source_afe_line_id === currentRate.source_afe_line_id && rate.charging_basis === line.charging_basis && rate.charge_category === line.charge_category && (!rate.hole_section_id || rate.hole_section_id === row.hole_section_id) && (!rate.phase_id || rate.phase_id === row.phase_id))
    const rate = matchingRate ?? currentRate
    if (rate && ((rate.hole_section_id && rate.hole_section_id !== row.hole_section_id) || (rate.phase_id && rate.phase_id !== row.phase_id))) throw new Error(`The AFE rate for ${rate.service_code} is not valid for an allocation's section/phase.`)
    if (!planned && !sub?.responsible_party?.trim() && !line.vendor_id) throw new Error('NPT / UPA allocations require a responsible party on the sub activity or a vendor.')
    return {
      ...line, id: index === 0 ? line.id : null,
      activity_id: row.activity_id, sub_activity_id: row.sub_activity_id,
      hole_section_id: row.hole_section_id || null, phase_id: row.hole_section_id ? row.phase_id || null : null,
      actual_depth: row.actual_depth || null, actual_depth_unit: row.actual_depth_unit,
      vendor_id: planned ? null : line.vendor_id,
      party_name: planned ? 'Not Applicable' : sub?.responsible_party || line.party_name,
      quantity: timed ? row.hours : line.id && (line.quantity_unit === 'section' || line.quantity_unit === 'service') ? line.quantity : '1', quantity_unit: timed ? 'hours' : line.charging_basis === 'Per Section Rate' ? 'section' : line.charging_basis === 'Per Service Rate' ? 'service' : 'unit',
      baseline_service_rate_id: rate?.id ?? null,
    }
  })
}

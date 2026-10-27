/**
 * Shared unit & FX helpers for WellCostIQ.
 *
 * Standing rules:
 *  - Every depth across well configuration, AFE scope, daily cost sheets,
 *    mud cost sections, and dashboards is standardized to metres (`m`) using
 *    the exact conversion factor `feet / 3.281`.
 *  - `USD` is the default and standard reporting currency across all wells.
 */

export const FEET_PER_METER = 3.281
export const DEFAULT_CURRENCY = 'USD'
export type DepthUnit = 'm' | 'ft'

export function normalizeDepthUnit(unit: string | null | undefined): DepthUnit {
  const cleaned = (unit ?? '').trim().toLowerCase()
  if (cleaned === 'ft' || cleaned === 'feet' || cleaned === 'foot') return 'ft'
  return 'm'
}

export function depthToMeters(
  value: string | number | null | undefined,
  unit: string | null | undefined = 'm',
): number | null {
  if (value === null || value === undefined || value === '') return null
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  const meters = normalizeDepthUnit(unit) === 'ft' ? num / FEET_PER_METER : num
  return Math.round((meters + Number.EPSILON) * 10_000_000_000) / 10_000_000_000
}

export function formatDepthMeters(
  value: string | number | null | undefined,
  unit: string | null | undefined = 'm',
): string {
  const meters = depthToMeters(value, unit)
  if (meters === null) return '—'
  return `${meters.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 10 })} m`
}

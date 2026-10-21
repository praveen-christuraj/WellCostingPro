// Canonical service groups. The order is the order used by the AFE cost
// estimate and Daily Cost reports; the labels mirror
// `backend/app/domain/service_groups.py`.

export const SERVICE_GROUPS = [
  'Rig Operations',
  'Formation Evaluation',
  'Well Services',
  'Land Facilities and Preparation',
  'Miscellaneous Services',
  'Supervisions',
] as const

export type ServiceGroup = typeof SERVICE_GROUPS[number]

const GROUP_RANK = new Map<string, number>(SERVICE_GROUPS.map((group, index) => [group, index]))
const UNCLASSIFIED_RANK = SERVICE_GROUPS.length

/** Unknown or empty groups sort after every canonical group. */
export function serviceGroupRank(group: string | null | undefined): number {
  return GROUP_RANK.get((group ?? '').trim()) ?? UNCLASSIFIED_RANK
}

export function serviceGroupLabel(group: string | null | undefined): string {
  return (group ?? '').trim()
}

export function compareServiceGroups(left: string | null | undefined, right: string | null | undefined): number {
  return serviceGroupRank(left) - serviceGroupRank(right)
}

export function compareServiceCodes(left: string | null | undefined, right: string | null | undefined): number {
  return (left ?? '').localeCompare(right ?? '', undefined, { numeric: true, sensitivity: 'base' })
}

type ServiceSortable = { service_group?: string | null; service_code?: string | null }
type BudgetSortable = { service_group?: string | null; item_code?: string | null }

/** AFE service lines: reporting group first, then natural service code. */
export function sortServicesByGroup<T extends ServiceSortable>(rows: T[]): T[] {
  return [...rows].sort((left, right) =>
    compareServiceGroups(left.service_group, right.service_group)
    || compareServiceCodes(left.service_code, right.service_code))
}

/** Daily Cost budget lines: same order, keyed by the snapshotted item code. */
export function sortBudgetLinesByGroup<T extends BudgetSortable>(rows: T[]): T[] {
  return [...rows].sort((left, right) =>
    compareServiceGroups(left.service_group, right.service_group)
    || compareServiceCodes(left.item_code, right.item_code))
}

/** Contiguous option groups for pickers (Autocomplete/MenuItem headers). */
export function groupServiceOptions<T extends { service_group?: string | null }>(
  options: T[],
): { group: string; options: T[] }[] {
  const groups = new Map<string, T[]>()
  for (const option of options) {
    const key = serviceGroupLabel(option.service_group)
    groups.set(key, [...(groups.get(key) ?? []), option])
  }
  return [...groups.entries()]
    .sort(([left], [right]) => compareServiceGroups(left, right))
    .map(([group, groupOptions]) => ({ group, options: groupOptions }))
}

/**
 * The rig and well a user is currently working on inside Daily Cost Management.
 *
 * The daily cost register, Mud Cost Analysis, the LIH Cost Register and the NDT
 * Inspection Register all record the same rig/well scope. Remembering that scope
 * once per browser and workspace means a shortcut taken from the daily cost
 * register opens the other register already scoped to the well the user is
 * costing. Every page still lets the user change the rig or well, and the change
 * becomes the remembered scope for the pages opened afterwards.
 *
 * The scope is a plain per-workspace localStorage entry (no server round trip),
 * so two workspaces used in one browser never see each other's scope.
 */
export type ActiveScope = { rigId: string; wellId: string }

const EMPTY_SCOPE: ActiveScope = { rigId: '', wellId: '' }
const STORAGE_PREFIX = 'wcp.active-scope'

function storageKey(organizationSlug?: string): string {
  return `${STORAGE_PREFIX}:${organizationSlug?.trim() || 'workspace'}`
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/** The remembered scope, or empty ids when nothing usable is stored. */
export function readActiveScope(organizationSlug?: string): ActiveScope {
  try {
    const raw = localStorage.getItem(storageKey(organizationSlug))
    if (!raw) return { ...EMPTY_SCOPE }
    const parsed = JSON.parse(raw) as Partial<ActiveScope> | null
    return { rigId: text(parsed?.rigId), wellId: text(parsed?.wellId) }
  } catch {
    // Private browsing, a disabled store or a legacy value all mean "nothing remembered".
    return { ...EMPTY_SCOPE }
  }
}

/** Remember the scope for the next page. An empty pair is never written. */
export function writeActiveScope(scope: ActiveScope, organizationSlug?: string): void {
  const next = { rigId: text(scope.rigId), wellId: text(scope.wellId) }
  if (!next.rigId && !next.wellId) return
  try {
    localStorage.setItem(storageKey(organizationSlug), JSON.stringify(next))
  } catch {
    // Remembering the scope is a convenience; failing to store it must never break entry.
  }
}

/**
 * The scope a register was opened with, read from its query string. Links built
 * with `scopeLink` carry both ids; anything missing or malformed is ignored.
 */
export function requestedScope(search: URLSearchParams | string): ActiveScope {
  const params = typeof search === 'string' ? new URLSearchParams(search) : search
  return { rigId: text(params.get('rig_id')), wellId: text(params.get('well_id')) }
}

type ScopeWell = { id: string; rig_id: string }
type ScopeRig = { id: string }

/**
 * The scope a register should adopt from the link that opened it, checked
 * against the rigs and wells the register may actually use. A well wins over a
 * bare rig because it also names its rig; anything unknown is ignored instead of
 * silently pointing the register at a deleted record.
 */
export function resolveRequestedScope(
  requested: ActiveScope, wells: ScopeWell[], rigs: ScopeRig[],
): ActiveScope {
  const well = wells.find(item => item.id === text(requested.wellId))
  if (well) return { rigId: well.rig_id, wellId: well.id }
  const rigId = text(requested.rigId)
  if (rigId && rigs.some(rig => rig.id === rigId)) return { rigId, wellId: '' }
  return { ...EMPTY_SCOPE }
}

/**
 * The rig and well a register should start on. A remembered well that still
 * exists always wins, so the user resumes where they left off. Otherwise the
 * caller's preferred wells are tried in order (the newest record in the register,
 * then the module's own default) and the first available well is the last resort.
 * The rig always follows the chosen well, so the pair can never contradict itself.
 */
export function resolveWorkingScope(
  remembered: ActiveScope, wells: ScopeWell[], rigs: ScopeRig[], preferredWellIds: (string | null | undefined)[] = [],
): ActiveScope {
  let well = wells.find(item => item.id === text(remembered.wellId)) ?? null
  if (!well) {
    for (const id of preferredWellIds) {
      const match = id ? wells.find(item => item.id === id) : undefined
      if (match) { well = match; break }
    }
  }
  if (!well) well = wells[0] ?? null
  if (well) return { rigId: well.rig_id, wellId: well.id }
  const rigId = text(remembered.rigId)
  const nextRigId = rigs.some(item => item.id === rigId) ? rigId : rigs[0]?.id ?? ''
  return { rigId: nextRigId, wellId: '' }
}

/** A register path scoped to the given rig and well, e.g. `/daily-cost/lih-register?rig_id=…&well_id=…`. */
export function scopeLink(path: string, scope: ActiveScope): string {
  const params = new URLSearchParams()
  if (text(scope.rigId)) params.set('rig_id', text(scope.rigId))
  if (text(scope.wellId)) params.set('well_id', text(scope.wellId))
  const query = params.toString()
  if (!query) return path
  return `${path}${path.includes('?') ? '&' : '?'}${query}`
}

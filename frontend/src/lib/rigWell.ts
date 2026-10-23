import { depthToMeters } from './units'

export type Block = {
  id: string
  block_code: string
  block_name: string
  description: string
  well_count: number
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type BlockOption = {
  id: string
  block_code: string
  block_name: string
  description: string
  display_name: string
  well_count: number
}

export type Rig = {
  id: string
  rig_code: string
  rig_name: string
  remarks: string
  well_count: number
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type RigOption = {
  id: string
  rig_code: string
  rig_name: string
  display_name: string
  well_count: number
}

export type WellConfigurationScope = 'drilling' | 'completion'

export type Well = {
  completion_status: 'active' | 'completed'
  completion_config_status: 'draft' | 'configured' | 'final_review'
  /** The scope this row represents when the page lists scope-segregated wells. */
  scope?: WellConfigurationScope
  completion_section_count: number
  id: string
  rig_id: string
  rig_code: string
  rig_name: string
  rig_display: string
  well_code: string
  well_name: string
  well_location: string
  block_id: string
  block_code: string
  block_name: string
  /** Block name, kept flat so printed reports and dashboards read one field. */
  block: string
  objective: string
  remarks: string
  status: 'active' | 'completed'
  config_status: 'draft' | 'configured' | 'final_review'
  depth_unit: 'm' | 'ft'
  completion_depth_unit: 'm' | 'ft'
  standard_depth_unit?: 'm'
  total_depth: string | number | null
  total_depth_m?: string | number | null
  total_days: string | number
  completion_total_depth: string | number | null
  completion_total_depth_m?: string | number | null
  completion_total_days: string | number
  section_count: number
  sub_activity_count: number
  drilling_sub_activity_count: number
  completion_sub_activity_count: number
  drilling_is_deleted: boolean
  drilling_deleted_at: string | null
  drilling_purged: boolean
  completion_is_deleted: boolean
  completion_deleted_at: string | null
  completion_purged: boolean
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
  // Latest approved drilling-scope plan adjustment, when one exists. Null
  // means no approved adjustment, so callers use total_days above.
  adjusted_total_days: string | number | null
  has_plan_adjustment: boolean
  plan_revision: number | null
}

export type WellPhaseDraft = {
  id: string
  phase_id: string
  phase_code: string
  phase_name: string
  days: string | number
  remarks: string
}

export type WellSectionDraft = {
  id: string
  hole_section_id: string
  section_code: string
  section_name: string
  from_depth: string | number
  to_depth: string | number
  from_depth_m?: string | number
  to_depth_m?: string | number
  remarks: string
  total_days: string | number
  phases: WellPhaseDraft[]
}

export type WellConfiguration = {
  scope: WellConfigurationScope
  well_id: string
  well_code: string
  well_name: string
  rig_code: string
  rig_name: string
  status: 'active' | 'completed'
  config_status: 'draft' | 'configured' | 'final_review'
  depth_unit: 'm' | 'ft'
  completion_depth_unit?: 'm' | 'ft'
  standard_depth_unit?: 'm'
  total_depth: string | number | null
  total_depth_m?: string | number | null
  total_days: string | number
  sections: WellSectionDraft[]
}

export type SubActivity = {
  id: string
  well_id: string
  scope: WellConfigurationScope
  sub_activity_code: string
  sub_activity_name: string
  activity_id: string
  responsible_party: string
  description: string
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
  well_code: string
  well_name: string
  rig_id: string
  rig_code: string
  rig_name: string
  activity_code: string
  activity_name: string
  activity_display: string
}

export type DeletedRigWellRecord = {
  id: string
  entity_type: 'block' | 'rig' | 'well' | 'well_sub_activity'
  scope?: WellConfigurationScope | null
  code: string
  name: string
  parent_label: string
  deleted_at: string
  created_at: string
}

export type RigWellActivityCount = { key: string; label: string; count: number }
export type RigWellRecentActivity = {
  id: string
  action: string
  entity_type: string
  entity_label: string
  summary: string
  created_at: string
}

export type RigWellBlockCount = {
  block_id: string
  block_code: string
  block_name: string
  well_count: number
}

export type RigWellOverview = {
  active_blocks: number
  deleted_blocks: number
  block_counts: RigWellBlockCount[]
  active_rigs: number
  deleted_rigs: number
  active_wells: number
  deleted_wells: number
  active_sub_activities: number
  deleted_sub_activities: number
  configured_wells: number
  draft_wells: number
  final_review_wells: number
  completed_wells: number
  activity_counts: RigWellActivityCount[]
  recent_activity: RigWellRecentActivity[]
}

export type ImportResult = { imported_count: number; error_count: number; errors: string[]; success: boolean }
export type MasterActivity = { id: string; code: string; name: string }
export type MasterConfigurationOption = { id: string; code: string; name: string }
export type RigWellConfigurationOptions = {
  hole_sections: MasterConfigurationOption[]
  phases: MasterConfigurationOption[]
}

export type BlockPayload = { block_code: string; block_name: string; description: string }
export type RigPayload = { rig_code: string; rig_name: string; remarks: string }
export type WellPayload = {
  rig_id: string
  block_id: string
  well_code: string
  well_name: string
  well_location: string
  objective: string
  remarks: string
  scopes: WellConfigurationScope[]
}
export type SubActivityPayload = {
  well_id: string
  scope: WellConfigurationScope
  sub_activity_code: string
  sub_activity_name: string
  activity_id: string
  responsible_party: string
  description: string
}

export const BLOCK_IMPORT_HEADERS = ['block_code', 'block_name']
export const BLOCK_IMPORT_OPTIONAL_HEADERS = ['description']
export const RIG_IMPORT_HEADERS = ['rig_code', 'rig_name']
export const RIG_IMPORT_OPTIONAL_HEADERS = ['remarks']
export const WELL_IMPORT_HEADERS = [
  'rig_code', 'block_code', 'well_code', 'well_name', 'well_location', 'objective',
]
export const WELL_IMPORT_OPTIONAL_HEADERS = ['remarks']
export const SUB_ACTIVITY_IMPORT_HEADERS = [
  'sub_activity_code', 'sub_activity_name', 'activity', 'responsible_party', 'description',
]
export const SUB_ACTIVITY_IMPORT_OPTIONAL_HEADERS = ['scope']

export const emptyBlockForm = (): BlockPayload => ({ block_code: '', block_name: '', description: '' })
export const emptyRigForm = (): RigPayload => ({ rig_code: '', rig_name: '', remarks: '' })
export const emptyWellForm = (): WellPayload => ({
  rig_id: '',
  block_id: '',
  well_code: '',
  well_name: '',
  well_location: '',
  objective: '',
  remarks: '',
  scopes: ['drilling', 'completion'],
})
export const emptySubActivityForm = (wellId = '', scope: WellConfigurationScope = 'drilling'): SubActivityPayload => ({
  well_id: wellId,
  scope,
  sub_activity_code: '',
  sub_activity_name: '',
  activity_id: '',
  responsible_party: '',
  description: '',
})

export function activeWellScopes(well: Pick<Well, 'drilling_is_deleted' | 'completion_is_deleted'> | null | undefined): WellConfigurationScope[] {
  if (!well) return []
  const scopes: WellConfigurationScope[] = []
  if (!well.drilling_is_deleted) scopes.push('drilling')
  if (!well.completion_is_deleted) scopes.push('completion')
  return scopes
}

export function scopeLabel(scope: WellConfigurationScope): string {
  return scope === 'completion' ? 'Completion' : 'Drilling'
}

export function formatDepth(
  value: string | number | null | undefined,
  unit: 'm' | 'ft' | string,
  metersOverride?: string | number | null,
): string {
  if (value == null || value === '') return '—'
  const meters = metersOverride != null && metersOverride !== ''
    ? Number(metersOverride)
    : depthToMeters(value, unit)
  if (meters == null || !Number.isFinite(meters)) return '—'
  const formattedMeters = `${meters.toLocaleString(undefined, { maximumFractionDigits: 2 })} m`
  if (unit === 'ft') {
    return `${formattedMeters} (${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} ft)`
  }
  return formattedMeters
}

export function formatDays(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  return `${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} days`
}

export function entityLabel(kind: DeletedRigWellRecord['entity_type']): string {
  if (kind === 'block') return 'Block'
  if (kind === 'rig') return 'Rig'
  if (kind === 'well') return 'Well'
  return 'Well sub activity'
}

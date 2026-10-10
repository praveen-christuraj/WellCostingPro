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

export type Well = {
  id: string
  rig_id: string
  rig_code: string
  rig_name: string
  rig_display: string
  well_code: string
  well_name: string
  well_location: string
  block: string
  objective: string
  remarks: string
  status: 'active' | 'completed'
  config_status: 'draft' | 'configured'
  depth_unit: 'm' | 'ft'
  total_depth: string | number | null
  total_days: string | number
  section_count: number
  sub_activity_count: number
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
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
  remarks: string
  total_days: string | number
  phases: WellPhaseDraft[]
}

export type WellConfiguration = {
  well_id: string
  well_code: string
  well_name: string
  rig_code: string
  rig_name: string
  status: 'active' | 'completed'
  config_status: 'draft' | 'configured'
  depth_unit: 'm' | 'ft'
  total_depth: string | number | null
  total_days: string | number
  sections: WellSectionDraft[]
}

export type SubActivity = {
  id: string
  well_id: string
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
  entity_type: 'rig' | 'well' | 'well_sub_activity'
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

export type RigWellOverview = {
  active_rigs: number
  deleted_rigs: number
  active_wells: number
  deleted_wells: number
  active_sub_activities: number
  deleted_sub_activities: number
  configured_wells: number
  draft_wells: number
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

export type RigPayload = { rig_code: string; rig_name: string; remarks: string }
export type WellPayload = {
  rig_id: string
  well_code: string
  well_name: string
  well_location: string
  block: string
  objective: string
  remarks: string
}
export type SubActivityPayload = {
  well_id: string
  sub_activity_code: string
  sub_activity_name: string
  activity_id: string
  responsible_party: string
  description: string
}

export const RIG_IMPORT_HEADERS = ['rig_code', 'rig_name']
export const RIG_IMPORT_OPTIONAL_HEADERS = ['remarks']
export const WELL_IMPORT_HEADERS = [
  'rig_code', 'well_code', 'well_name', 'well_location', 'block', 'objective',
]
export const WELL_IMPORT_OPTIONAL_HEADERS = ['remarks']
export const SUB_ACTIVITY_IMPORT_HEADERS = [
  'sub_activity_code', 'sub_activity_name', 'activity', 'responsible_party', 'description',
]

export const emptyRigForm = (): RigPayload => ({ rig_code: '', rig_name: '', remarks: '' })
export const emptyWellForm = (): WellPayload => ({
  rig_id: '', well_code: '', well_name: '', well_location: '', block: '', objective: '', remarks: '',
})
export const emptySubActivityForm = (wellId = ''): SubActivityPayload => ({
  well_id: wellId,
  sub_activity_code: '',
  sub_activity_name: '',
  activity_id: '',
  responsible_party: '',
  description: '',
})

export function formatDepth(value: string | number | null | undefined, unit: 'm' | 'ft' | string): string {
  if (value == null || value === '') return '—'
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${unit === 'ft' ? 'ft' : 'm'}`
}

export function formatDays(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  return `${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} days`
}

export function entityLabel(kind: DeletedRigWellRecord['entity_type']): string {
  if (kind === 'rig') return 'Rig'
  if (kind === 'well') return 'Well'
  return 'Well sub activity'
}

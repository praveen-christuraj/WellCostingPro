export type CostingSetGroup = 'services' | 'tangibles' | 'consumables'
export type CostingSetItemKind =
  | 'service'
  | 'tangible'
  | 'mud_chemical'
  | 'cement_additive'
  | 'fuel'
  | 'drill_bit'

export type CostingSetItem = {
  id: string
  item_kind: CostingSetItemKind
  item_id: string
  item_code: string
  item_name: string
  display_name: string
  is_available: boolean
}

export type CostingSet = {
  is_global?: boolean
  owner_id?: string
  id: string
  name: string
  item_group: CostingSetGroup
  description: string
  item_count: number
  items: CostingSetItem[]
  created_at: string
  updated_at: string
}

export type CostingSetOption = {
  item_group: CostingSetGroup
  item_kind: CostingSetItemKind
  item_id: string
  item_code: string
  item_name: string
  display_name: string
  is_available?: boolean
}

export type CostingSetInput = {
  is_global?: boolean
  name: string
  item_group: CostingSetGroup
  description: string
  items: { item_kind: CostingSetItemKind; item_id: string }[]
}

export type CostingSetImportResult = {
  created_sets: number
  updated_sets: number
  imported_items: number
  errors: { row: number; set_name: string; item_code: string; message: string }[]
}

export const COSTING_SET_GROUPS: { value: CostingSetGroup; label: string }[] = [
  { value: 'services', label: 'Services' },
  { value: 'tangibles', label: 'Tangibles' },
  { value: 'consumables', label: 'Consumables' },
]

export const COSTING_SET_ITEM_KIND_LABEL: Record<CostingSetItemKind, string> = {
  service: 'Service',
  tangible: 'Tangible',
  mud_chemical: 'Mud chemical',
  cement_additive: 'Cement additive',
  fuel: 'Fuel',
  drill_bit: 'Drill bit',
}

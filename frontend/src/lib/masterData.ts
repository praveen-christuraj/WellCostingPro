export const MASTER_DATA_MODULES = [
  { key: 'uom', label: 'UOM', title: 'Units of Measurement', hasSymbol: true },
  { key: 'currencies', label: 'Currency', title: 'Currencies', hasSymbol: true },
  { key: 'phases', label: 'Phases', title: 'Phases', hasSymbol: false },
  { key: 'hole-sections', label: 'Hole Sections', title: 'Hole Sections', hasSymbol: false },
  { key: 'activities', label: 'Activities', title: 'Activities', hasSymbol: false },
] as const

export type MasterDataModuleKey = (typeof MASTER_DATA_MODULES)[number]['key']
export type MasterDataModule = (typeof MASTER_DATA_MODULES)[number]

export type MasterDataRecord = {
  id: string
  code: string
  name: string
  symbol: string | null
  description: string
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type MasterDataModuleStats = {
  key: MasterDataModuleKey
  label: string
  active_count: number
  deleted_count: number
}

export type MasterDataActivity = {
  id: string
  action: string
  entity_label: string
  summary: string
  created_at: string
}

export type MasterDataOverview = {
  active_records: number
  deleted_records: number
  module_count: number
  modules: MasterDataModuleStats[]
  recent_activity: MasterDataActivity[]
}

export type DeletedMasterDataRecord = MasterDataRecord & {
  module_key: MasterDataModuleKey
  module_label: string
}

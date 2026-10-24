import type { ImportRow } from './export'

export type NdtScope = 'drilling' | 'completion'
export type NdtEntry = {
  id: string; rig_id: string; rig_code: string; rig_name: string
  well_id: string; well_code: string; well_name: string; scope: NdtScope
  description: string; quantity_received: string; quantity_consumed: string
  quantity_backloaded_good: string; quantity_backloaded_bad: string; remarks: string
  is_deleted: boolean; deleted_at: string | null; created_by: string; updated_by: string
  created_at: string; updated_at: string
}
export type NdtReference = {
  rigs: { id: string; rig_code: string; rig_name: string; display_name: string }[]
  wells: { id: string; rig_id: string; well_code: string; well_name: string; display_name: string; drilling_available: boolean; completion_available: boolean }[]
}
export type NdtLine = {
  key: string; description: string; quantity_received: string; quantity_consumed: string
  quantity_backloaded_good: string; quantity_backloaded_bad: string; remarks: string
}

export const NDT_IMPORT_HEADERS = ['Rig Code', 'Well Code', 'Scope', 'Description', 'Quantity Received', 'Quantity Consumed', 'Backloaded Good', 'Backloaded Bad']
export const NDT_IMPORT_OPTIONAL = ['Remarks']
export const NDT_IMPORT_SAMPLE: ImportRow = {
  'Rig Code': 'RIG-01', 'Well Code': 'WELL-01', Scope: 'Drilling', Description: 'Drill pipe inspection',
  'Quantity Received': '20', 'Quantity Consumed': '18', 'Backloaded Good': '15', 'Backloaded Bad': '3', Remarks: 'Sample row',
}
export const newNdtLine = (): NdtLine => ({
  key: crypto.randomUUID(), description: '', quantity_received: '0', quantity_consumed: '0',
  quantity_backloaded_good: '0', quantity_backloaded_bad: '0', remarks: '',
})
export const quantity = (value: string | number) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 10 })
export const importNdtRow = (row: ImportRow) => ({
  rig_code: row['Rig Code']?.trim(), well_code: row['Well Code']?.trim(), scope: row.Scope?.trim(),
  description: row.Description?.trim(), quantity_received: row['Quantity Received'] || 0,
  quantity_consumed: row['Quantity Consumed'] || 0, quantity_backloaded_good: row['Backloaded Good'] || 0,
  quantity_backloaded_bad: row['Backloaded Bad'] || 0, remarks: row.Remarks?.trim() || '',
})

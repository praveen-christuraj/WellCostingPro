// Configuration and types for Tangibles and Consumables. One FieldDef list drives the
// create/edit forms, the import template and the grid columns, so the three never drift.

export type CatalogueTypeKey = 'tangibles' | 'drill-bits' | 'mud-chemicals' | 'cement-additives' | 'fuel-types'
export type OptionListKey =
  | 'tangible_category'
  | 'tangible_subcategory'
  | 'manufacturer'
  | 'drill_bit_type'
  | 'mud_chemical_group'
  | 'cement_additive_type'

export const TANGIBLE_SCOPES = ['Drilling', 'Completion', 'Others'] as const

export const OPTION_LIST_LABELS: Record<OptionListKey, string> = {
  tangible_category: 'Tangible categories',
  tangible_subcategory: 'Tangible subcategories',
  manufacturer: 'Manufacturers (shared)',
  drill_bit_type: 'Drill bit types',
  mud_chemical_group: 'Mud chemical groups',
  cement_additive_type: 'Cement additive types',
}

export type FieldDef = {
  key: string
  label: string
  kind: 'text' | 'textarea' | 'number' | 'date' | 'choice' | 'option' | 'master'
  section: 'master' | 'rate'
  required?: boolean
  maxLength?: number
  help?: string
  choices?: readonly string[]
  listKey?: OptionListKey
  parentKey?: string
  masterSource?: 'uom' | 'currencies'
  placeholder?: string
}

export type ColumnDef = { key: string; label: string; kind?: 'money' | 'percent' | 'date' | 'text' | 'number'; width?: number; flex?: number }

export type TypeConfig = {
  key: CatalogueTypeKey
  label: string
  singular: string
  entity: string
  codeKey: string
  nameKey: string
  codeLabel: string
  nameLabel: string
  priced: 'uplift' | 'unit'
  fixed: boolean
  fields: FieldDef[]
  columns: ColumnDef[]
  breakdownLabel?: string
  importHeaders: string[]
  importOptional: string[]
  sample: Record<string, string>
  templateName: string
  importHint: string
}

const rateFields = (uplift: boolean): FieldDef[] => [
  { key: 'unit_rate', label: uplift ? 'Rate as per PO' : 'Unit rate', kind: 'number', section: 'rate', required: true, help: uplift ? 'Rate quoted on the purchase order.' : 'Price per unit of measure.' },
  ...(uplift ? [{ key: 'cost_uplift', label: 'Cost uplift %', kind: 'number' as const, section: 'rate' as const, required: true, help: 'Final cost = rate × uplift ÷ 100. Use 100 for no uplift.' }] : []),
  { key: 'currency', label: 'Currency', kind: 'master', section: 'rate', required: true, masterSource: 'currencies', help: 'From Master Data → Currency.' },
  { key: 'po_number', label: 'PO number', kind: 'text', section: 'rate', maxLength: 100 },
  { key: 'effective_date', label: 'Effective date', kind: 'date', section: 'rate', help: 'Date this rate applies from. Defaults to today.' },
]

export const TANGIBLE_CONFIG: TypeConfig = {
  key: 'tangibles',
  label: 'Tangibles',
  singular: 'tangible',
  entity: 'tangible',
  codeKey: 'tangible_code',
  nameKey: 'tangible_name',
  codeLabel: 'Tangible code',
  nameLabel: 'Tangible name',
  priced: 'uplift',
  fixed: false,
  breakdownLabel: 'Category',
  fields: [
    { key: 'tangible_code', label: 'Tangible code', kind: 'text', section: 'master', required: true, maxLength: 50, help: 'Enter manually. Codes are upper-cased and unique in this workspace.' },
    { key: 'tangible_name', label: 'Tangible name', kind: 'text', section: 'master', required: true, maxLength: 200 },
    { key: 'scope', label: 'Scope', kind: 'choice', section: 'master', required: true, choices: TANGIBLE_SCOPES },
    { key: 'category_id', label: 'Category', kind: 'option', section: 'master', required: true, listKey: 'tangible_category', help: 'Type a new category to add it to the list.' },
    { key: 'subcategory_id', label: 'Subcategory', kind: 'option', section: 'master', required: true, listKey: 'tangible_subcategory', parentKey: 'category_id', help: 'Choose a category first. Subcategories belong to one category.' },
    { key: 'manufacturer_id', label: 'Make / manufacturer', kind: 'option', section: 'master', required: true, listKey: 'manufacturer', help: 'Shared with drill bits, mud chemicals and cement additives.' },
    { key: 'uom', label: 'Unit of measure', kind: 'master', section: 'master', masterSource: 'uom', maxLength: 50 },
    { key: 'description', label: 'Description', kind: 'textarea', section: 'master', maxLength: 500 },
    { key: 'remarks', label: 'Remarks', kind: 'textarea', section: 'master', maxLength: 500 },
    ...rateFields(true),
  ],
  columns: [
    { key: 'tangible_code', label: 'CODE', width: 115 },
    { key: 'tangible_name', label: 'NAME', flex: 1.3, width: 190 },
    { key: 'scope', label: 'SCOPE', width: 110 },
    { key: 'category_name', label: 'CATEGORY', width: 150 },
    { key: 'subcategory_name', label: 'SUBCATEGORY', width: 150 },
    { key: 'manufacturer_name', label: 'MAKE', width: 150 },
    { key: 'unit_rate', label: 'RATE AS PER PO', kind: 'money', width: 135 },
    { key: 'cost_uplift', label: 'UPLIFT %', kind: 'percent', width: 105 },
    { key: 'final_cost', label: 'FINAL COST', kind: 'money', width: 130 },
    { key: 'currency', label: 'CCY', width: 80 },
    { key: 'effective_date', label: 'EFFECTIVE', kind: 'date', width: 120 },
    { key: 'current_revision_number', label: 'REV', kind: 'number', width: 80 },
  ],
  importHeaders: ['tangible_code', 'tangible_name', 'scope', 'category', 'subcategory', 'manufacturer', 'unit_rate', 'currency'],
  importOptional: ['uom', 'po_number', 'cost_uplift', 'effective_date', 'description', 'remarks'],
  sample: {
    tangible_code: 'TNG-0001', tangible_name: 'Casing centraliser 9-5/8in', scope: 'Drilling', category: 'Casing Accessories',
    subcategory: 'Centralisers', manufacturer: 'Weatherford', uom: 'EA', po_number: 'PO-4500123', unit_rate: '1250',
    cost_uplift: '100', currency: 'USD', effective_date: '2026-01-31', description: 'Bow spring centraliser', remarks: '',
  },
  templateName: 'tangibles-template.csv',
  importHint: 'Codes are required and entered by you. A blank category, subcategory or make on an existing code keeps its current value. Unknown categories, subcategories and makes are added to the lists automatically. Currency and unit of measure must already exist in Master Data. Dates accept 2026-01-31 or 31/01/2026.',
}

export const DRILL_BIT_CONFIG: TypeConfig = {
  key: 'drill-bits',
  label: 'Drill Bits',
  singular: 'drill bit',
  entity: 'drill_bit',
  codeKey: 'bit_code',
  nameKey: 'bit_name',
  codeLabel: 'Bit code',
  nameLabel: 'Bit name',
  priced: 'uplift',
  fixed: false,
  breakdownLabel: 'Bit type',
  fields: [
    { key: 'bit_code', label: 'Bit code', kind: 'text', section: 'master', required: true, maxLength: 50, help: 'Enter manually. Unique in this workspace.' },
    { key: 'bit_name', label: 'Bit name', kind: 'text', section: 'master', required: true, maxLength: 200 },
    { key: 'bit_type_id', label: 'Bit type', kind: 'option', section: 'master', required: true, listKey: 'drill_bit_type' },
    { key: 'manufacturer_id', label: 'Make / manufacturer', kind: 'option', section: 'master', required: true, listKey: 'manufacturer' },
    { key: 'model_no', label: 'Model no.', kind: 'text', section: 'master', required: true, maxLength: 100 },
    { key: 'size', label: 'Size', kind: 'text', section: 'master', required: true, maxLength: 60, placeholder: '8-1/2 in' },
    { key: 'iadc_code', label: 'IADC code', kind: 'text', section: 'master', maxLength: 20 },
    { key: 'serial_number', label: 'Serial number', kind: 'text', section: 'master', maxLength: 100, help: 'Must be unique across all bits when entered.' },
    { key: 'description', label: 'Description', kind: 'textarea', section: 'master', maxLength: 500 },
    { key: 'remarks', label: 'Remarks', kind: 'textarea', section: 'master', maxLength: 500 },
    ...rateFields(true),
  ],
  columns: [
    { key: 'bit_code', label: 'CODE', width: 110 },
    { key: 'bit_name', label: 'NAME', flex: 1.2, width: 180 },
    { key: 'bit_type_name', label: 'TYPE', width: 115 },
    { key: 'manufacturer_name', label: 'MAKE', width: 140 },
    { key: 'model_no', label: 'MODEL', width: 110 },
    { key: 'size', label: 'SIZE', width: 105 },
    { key: 'serial_number', label: 'SERIAL NO.', width: 125 },
    { key: 'unit_rate', label: 'RATE AS PER PO', kind: 'money', width: 135 },
    { key: 'cost_uplift', label: 'UPLIFT %', kind: 'percent', width: 105 },
    { key: 'final_cost', label: 'FINAL COST', kind: 'money', width: 130 },
    { key: 'currency', label: 'CCY', width: 80 },
    { key: 'effective_date', label: 'EFFECTIVE', kind: 'date', width: 120 },
    { key: 'current_revision_number', label: 'REV', kind: 'number', width: 80 },
  ],
  importHeaders: ['bit_code', 'bit_name', 'bit_type', 'model_no', 'size', 'manufacturer', 'unit_rate', 'currency'],
  importOptional: ['iadc_code', 'serial_number', 'po_number', 'cost_uplift', 'effective_date', 'description', 'remarks'],
  sample: {
    bit_code: 'DB-0001', bit_name: 'PDC bit 8-1/2in', bit_type: 'PDC', model_no: 'M1365', size: '8-1/2 in', iadc_code: 'M423',
    serial_number: 'SN-88421', manufacturer: 'Halliburton', po_number: 'PO-4500456', unit_rate: '85000', cost_uplift: '100',
    currency: 'USD', effective_date: '2026-02-01', description: '', remarks: '',
  },
  templateName: 'drill-bits-template.csv',
  importHint: 'Codes are required and entered by you. A serial number may be used by only one bit. Unknown bit types and makes are added to the lists automatically.',
}

export const MUD_CHEMICAL_CONFIG: TypeConfig = {
  key: 'mud-chemicals',
  label: 'Mud Chemicals',
  singular: 'mud chemical',
  entity: 'mud_chemical',
  codeKey: 'chemical_code',
  nameKey: 'chemical_name',
  codeLabel: 'Chemical code',
  nameLabel: 'Chemical name',
  priced: 'unit',
  fixed: false,
  breakdownLabel: 'Group',
  fields: [
    { key: 'chemical_code', label: 'Chemical code', kind: 'text', section: 'master', required: true, maxLength: 50, help: 'Enter manually. Unique in this workspace.' },
    { key: 'chemical_name', label: 'Chemical name', kind: 'text', section: 'master', required: true, maxLength: 200, help: 'Names must be unique (case-insensitive).' },
    { key: 'group_id', label: 'Group', kind: 'option', section: 'master', required: true, listKey: 'mud_chemical_group' },
    { key: 'manufacturer_id', label: 'Make / manufacturer', kind: 'option', section: 'master', listKey: 'manufacturer' },
    { key: 'part_number', label: 'Part number', kind: 'text', section: 'master', maxLength: 100 },
    { key: 'uom', label: 'Unit of measure', kind: 'master', section: 'master', masterSource: 'uom', maxLength: 50 },
    { key: 'description', label: 'Description', kind: 'textarea', section: 'master', maxLength: 500 },
    { key: 'remarks', label: 'Remarks', kind: 'textarea', section: 'master', maxLength: 500 },
    ...rateFields(false),
  ],
  columns: [
    { key: 'chemical_code', label: 'CODE', width: 115 },
    { key: 'chemical_name', label: 'NAME', flex: 1.2, width: 190 },
    { key: 'group_name', label: 'GROUP', width: 160 },
    { key: 'manufacturer_name', label: 'MAKE', width: 140 },
    { key: 'part_number', label: 'PART NO.', width: 120 },
    { key: 'uom', label: 'UOM', width: 90 },
    { key: 'unit_rate', label: 'UNIT RATE', kind: 'money', width: 125 },
    { key: 'currency', label: 'CCY', width: 80 },
    { key: 'effective_date', label: 'EFFECTIVE', kind: 'date', width: 120 },
    { key: 'current_revision_number', label: 'REV', kind: 'number', width: 80 },
  ],
  importHeaders: ['chemical_code', 'chemical_name', 'group', 'unit_rate', 'currency'],
  importOptional: ['manufacturer', 'part_number', 'uom', 'po_number', 'effective_date', 'description', 'remarks'],
  sample: {
    chemical_code: 'MC-0001', chemical_name: 'Barite', group: 'Weighting agent', manufacturer: 'Baroid', part_number: 'BR-25',
    uom: 'MT', unit_rate: '420', currency: 'USD', po_number: '', effective_date: '2026-01-15', description: '', remarks: '',
  },
  templateName: 'mud-chemicals-template.csv',
  importHint: 'Codes are required and entered by you. Names must be unique. Unknown groups and makes are added to the lists automatically.',
}

export const CEMENT_ADDITIVE_CONFIG: TypeConfig = {
  key: 'cement-additives',
  label: 'Cement Additives',
  singular: 'cement additive',
  entity: 'cement_additive',
  codeKey: 'additive_code',
  nameKey: 'additive_name',
  codeLabel: 'Additive code',
  nameLabel: 'Additive name',
  priced: 'unit',
  fixed: false,
  breakdownLabel: 'Additive type',
  fields: [
    { key: 'additive_code', label: 'Additive code', kind: 'text', section: 'master', required: true, maxLength: 50, help: 'Enter manually. Unique in this workspace.' },
    { key: 'additive_name', label: 'Additive name', kind: 'text', section: 'master', required: true, maxLength: 200, help: 'Names must be unique (case-insensitive).' },
    { key: 'additive_type_id', label: 'Additive type', kind: 'option', section: 'master', required: true, listKey: 'cement_additive_type' },
    { key: 'manufacturer_id', label: 'Make / manufacturer', kind: 'option', section: 'master', listKey: 'manufacturer' },
    { key: 'part_number', label: 'Part number', kind: 'text', section: 'master', maxLength: 100 },
    { key: 'uom', label: 'Unit of measure', kind: 'master', section: 'master', masterSource: 'uom', maxLength: 50 },
    { key: 'description', label: 'Description', kind: 'textarea', section: 'master', maxLength: 500 },
    { key: 'remarks', label: 'Remarks', kind: 'textarea', section: 'master', maxLength: 500 },
    ...rateFields(false),
  ],
  columns: [
    { key: 'additive_code', label: 'CODE', width: 115 },
    { key: 'additive_name', label: 'NAME', flex: 1.2, width: 190 },
    { key: 'additive_type_name', label: 'TYPE', width: 160 },
    { key: 'manufacturer_name', label: 'MAKE', width: 140 },
    { key: 'part_number', label: 'PART NO.', width: 120 },
    { key: 'uom', label: 'UOM', width: 90 },
    { key: 'unit_rate', label: 'UNIT RATE', kind: 'money', width: 125 },
    { key: 'currency', label: 'CCY', width: 80 },
    { key: 'effective_date', label: 'EFFECTIVE', kind: 'date', width: 120 },
    { key: 'current_revision_number', label: 'REV', kind: 'number', width: 80 },
  ],
  importHeaders: ['additive_code', 'additive_name', 'additive_type', 'unit_rate', 'currency'],
  importOptional: ['manufacturer', 'part_number', 'uom', 'po_number', 'effective_date', 'description', 'remarks'],
  sample: {
    additive_code: 'CA-0001', additive_name: 'Calcium chloride', additive_type: 'Accelerator', manufacturer: 'Halliburton',
    part_number: 'CC-50', uom: 'MT', unit_rate: '610', currency: 'USD', po_number: '', effective_date: '2026-01-15', description: '', remarks: '',
  },
  templateName: 'cement-additives-template.csv',
  importHint: 'Codes are required and entered by you. Names must be unique. Unknown additive types and makes are added to the lists automatically.',
}

export const FUEL_CONFIG: TypeConfig = {
  key: 'fuel-types',
  label: 'Fuel',
  singular: 'fuel',
  entity: 'fuel_type',
  codeKey: 'fuel_code',
  nameKey: 'fuel_name',
  codeLabel: 'Fuel code',
  nameLabel: 'Fuel',
  priced: 'unit',
  fixed: true,
  // Fuel only takes a price: no create, edit or PO fields.
  fields: [
    { key: 'unit_rate', label: 'Price per litre', kind: 'number', section: 'rate', required: true, help: 'Enter the new price only when it changes.' },
    { key: 'currency', label: 'Currency', kind: 'master', section: 'rate', required: true, masterSource: 'currencies' },
    { key: 'effective_date', label: 'Effective date', kind: 'date', section: 'rate', help: 'Date the new price applies from. Defaults to today.' },
  ],
  columns: [
    { key: 'fuel_code', label: 'CODE', width: 130 },
    { key: 'fuel_name', label: 'FUEL', flex: 1, width: 220 },
    { key: 'uom', label: 'UOM', width: 90 },
    { key: 'unit_rate', label: 'CURRENT PRICE', kind: 'money', width: 150 },
    { key: 'currency', label: 'CCY', width: 80 },
    { key: 'effective_date', label: 'PRICE EFFECTIVE', kind: 'date', width: 150 },
    { key: 'current_revision_number', label: 'PRICE REVISIONS', kind: 'number', width: 150 },
  ],
  importHeaders: [],
  importOptional: [],
  sample: {},
  templateName: 'fuel-template.csv',
  importHint: '',
}

export const CONSUMABLE_TYPES = [MUD_CHEMICAL_CONFIG, CEMENT_ADDITIVE_CONFIG, FUEL_CONFIG, DRILL_BIT_CONFIG] as const
export const CATALOGUE_TYPES: Record<CatalogueTypeKey, TypeConfig> = {
  tangibles: TANGIBLE_CONFIG,
  'drill-bits': DRILL_BIT_CONFIG,
  'mud-chemicals': MUD_CHEMICAL_CONFIG,
  'cement-additives': CEMENT_ADDITIVE_CONFIG,
  'fuel-types': FUEL_CONFIG,
}

// ----- API shapes -------------------------------------------------------------

export type CatalogueOption = {
  id: string
  list_key: OptionListKey
  list_label: string
  value: string
  parent_id: string | null
  parent_value: string | null
  usage_count: number
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type CatalogueListSummary = {
  key: OptionListKey
  label: string
  parent_key: OptionListKey | null
  parent_label: string | null
  active_count: number
  removed_count: number
  usage_count: number
}

export type RateRevision = {
  id: string
  item_type: string
  item_id: string
  item_code: string
  item_name: string
  revision_number: number
  effective_date: string
  unit_rate: string
  previous_unit_rate: string
  cost_uplift: string | null
  final_cost: string | null
  previous_final_cost: string | null
  currency: string
  uom: string
  po_number: string
  reason: string
  recorded_by: string
  created_at: string
}

export type PricedOverview = {
  active_count: number
  deleted_count: number
  revisions_last_30_days: number
  breakdown_label: string | null
  breakdown: { key: string; label: string; count: number }[]
  recent_revisions: RateRevision[]
}

// A priced record as returned by the API. Field names follow the type's config.
export type PricedRecord = Record<string, unknown> & {
  id: string
  description: string
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
  unit_rate: string
  cost_uplift: string | null
  final_cost: string | null
  currency: string
  po_number?: string
  effective_date: string | null
  current_revision_number: number
}

// ----- form helpers -------------------------------------------------------------

export type FormState = Record<string, string>

export function emptyForm(config: TypeConfig): FormState {
  const state: FormState = {}
  for (const field of config.fields) state[field.key] = field.key === 'cost_uplift' ? '100' : ''
  state.effective_date = todayIso()
  return state
}

export function recordToForm(config: TypeConfig, record: PricedRecord): FormState {
  const state: FormState = {}
  for (const field of config.fields) {
    if (field.section !== 'master') continue
    const value = record[field.key]
    state[field.key] = value === null || value === undefined ? '' : String(value)
  }
  return state
}

export function todayIso(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

// Builds the JSON body for create (section master + rate) or edit (master only) and
// converts blanks: empty optional selections become null, empty dates become null.
export function formToPayload(config: TypeConfig, form: FormState, mode: 'create' | 'edit' | 'revise'): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const field of config.fields) {
    if (mode === 'edit' && field.section === 'rate') continue
    if (mode === 'revise' && field.section === 'master') continue
    const raw = (form[field.key] ?? '').trim()
    if (field.kind === 'number') {
      if (raw !== '') payload[field.key] = raw
    } else if (field.kind === 'date') {
      payload[field.key] = raw === '' ? null : raw
    } else if (field.kind === 'option' || (field.kind === 'master' && field.section === 'master')) {
      payload[field.key] = raw === '' ? null : raw
    } else {
      payload[field.key] = raw
    }
  }
  return payload
}

// Live final cost preview for uplift types: rate x uplift / 100.
export function previewFinalCost(rate: string, uplift: string): string {
  const r = Number(rate)
  const u = Number(uplift)
  if (!Number.isFinite(r) || !Number.isFinite(u) || rate.trim() === '' || uplift.trim() === '') return '—'
  return formatMoney(r * u / 100)
}

export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })
}

export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  return Number.isFinite(n) ? `${n.toLocaleString(undefined, { maximumFractionDigits: 4 })}%` : String(value)
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const [year, month, day] = value.slice(0, 10).split('-')
  return year && month && day ? `${day}/${month}/${year}` : value
}

export function cellValue(column: ColumnDef, record: Record<string, unknown>): string {
  const raw = record[column.key]
  if (column.kind === 'money') return formatMoney(raw as string | null)
  if (column.kind === 'percent') return formatPercent(raw as string | null)
  if (column.kind === 'date') return formatDate(raw as string | null)
  if (raw === null || raw === undefined || raw === '') return '—'
  return String(raw)
}

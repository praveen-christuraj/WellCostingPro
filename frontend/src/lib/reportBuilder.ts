// Report Builder contracts, the blank design and formatting helpers.
// The design is a set of typed rows (columns, filters, groupings…), exactly the
// shape the API validates against the live catalogue.

export type ColumnKind = 'DATA' | 'RELATED' | 'CALCULATED'
export type DataType = 'text' | 'number' | 'date' | 'boolean'
export type Aggregate = 'NONE' | 'SUM' | 'AVG' | 'MIN' | 'MAX' | 'COUNT' | 'COUNT_DISTINCT' | 'FIRST' | 'LAST' | 'PRODUCT'

export type ReportCondition = {
  source_kind: string
  column_name: string
  related_table: string
  related_key_column: string
  operator: string
  value: string
  value2: string
}

export type ReportColumn = {
  key: string
  label: string
  kind: ColumnKind
  column_name: string
  related_table: string
  related_key_column: string
  formula: string
  data_type: DataType
  decimals: number
  prefix: string
  suffix: string
  aggregate: Aggregate
  show_total: boolean
  hidden: boolean
  condition_logic: 'AND' | 'OR'
  width: number
  conditions: ReportCondition[]
}

export type ReportFilter = {
  label: string
  source_kind: string
  column_name: string
  related_table: string
  related_key_column: string
  operator: string
  value: string
  value2: string
}

export type ReportRuntimeFilter = {
  key: string
  label: string
  filter_type: 'text' | 'select' | 'date' | 'number' | 'boolean'
  source_kind: string
  column_name: string
  related_table: string
  related_key_column: string
  operator: string
  required: boolean
  default_value: string
  options: string[]
}

export type ReportGrouping = { kind: 'group' | 'matrix_row' | 'matrix_column'; column_key: string; bucket: string }
export type ReportSort = { column_key: string; direction: 'ASC' | 'DESC' }
export type ReportGrant = { grant_type: 'user' | 'role'; user_id: string; role_id: string; level: 'view' | 'edit' }

export type ReportDesign = {
  name: string
  description: string
  report_type: 'TABULAR' | 'MATRIX'
  source_table: string
  date_basis: 'NONE' | 'CREATED_AT' | 'UPDATED_AT' | 'COLUMN'
  date_column: string
  filter_logic: 'AND' | 'OR'
  show_totals: boolean
  page_size: number
  empty_text: string
  matrix_value_key: string
  matrix_aggregate: Aggregate
  matrix_show_totals: boolean
  visibility: 'private' | 'internal' | 'shared'
  columns: ReportColumn[]
  filters: ReportFilter[]
  runtime_filters: ReportRuntimeFilter[]
  groupings: ReportGrouping[]
  sorts: ReportSort[]
  grants: ReportGrant[]
}

export type ReportGrantLabel = { grant_type: string; id: string; level: string; name: string; detail: string }

export type ReportDefinition = {
  id: string
  name: string
  description: string
  status: 'draft' | 'published'
  version: number
  visibility: string
  report_type: string
  source_table: string
  run_count: number
  last_run_at: string | null
  published_at: string | null
  created_by_display: string
  updated_by_display: string
  created_at: string
  updated_at: string
  can_edit: boolean
  can_delete: boolean
  can_publish: boolean
  can_run: boolean
  grants: ReportGrantLabel[]
  design: ReportDesign
}

export type ReportDefinitionList = { items: ReportDefinition[]; counts: Record<string, number> }

export type ReportRunColumn = { key: string; label: string; data_type: DataType; align: string; decimals: number; width: number }

export type ReportRun = {
  report_type: string
  columns: ReportRunColumn[]
  rows: Record<string, string>[]
  totals: Record<string, string> | null
  grouped: boolean
  matrix: boolean
  total_rows: number
  page: number
  page_size: number
  pages: number
  warnings: string[]
  stats: Record<string, number>
  date_basis: string
  date_from: string
  date_to: string
  notes: string[]
  generated_at: string
}

export type CatalogTable = {
  table: string
  label: string
  group: string
  scope: string
  primary_key: string[]
  column_count: number
  date_columns: string[]
  relation_count: number
  has_created_at: boolean
  has_updated_at: boolean
}

export type CatalogColumn = { column: string; label: string; data_type: DataType }
export type CatalogRelation = { key_column: string; table: string; label: string; columns: CatalogColumn[] }
export type CatalogDetail = CatalogTable & { columns: CatalogColumn[]; relations: CatalogRelation[] }

export type Catalog = {
  tables: CatalogTable[]
  groups: { group: string; tables: string[] }[]
  table_count: number
  relation_help: string
}

export type Starter = {
  key: string
  name: string
  description: string
  report_type: string
  source_table: string
  source_label: string
  column_count: number
  available: boolean
}

export type ReportVersion = {
  id: string
  version: number
  report_name: string
  report_type: string
  source_table: string
  column_count: number
  filter_count: number
  grouping_count: number
  grant_count: number
  status: string
  change_note: string
  changed_by_display: string
  created_at: string
}

export type Lookups = { users: { id: string; name: string; email: string }[]; roles: { id: string; name: string; is_owner: boolean }[] }

export const OPERATORS: { value: string; label: string; needs_value: boolean; second: boolean }[] = [
  { value: 'eq', label: 'is', needs_value: true, second: false },
  { value: 'ne', label: 'is not', needs_value: true, second: false },
  { value: 'contains', label: 'contains', needs_value: true, second: false },
  { value: 'not_contains', label: 'does not contain', needs_value: true, second: false },
  { value: 'starts_with', label: 'starts with', needs_value: true, second: false },
  { value: 'ends_with', label: 'ends with', needs_value: true, second: false },
  { value: 'gt', label: 'is greater than', needs_value: true, second: false },
  { value: 'gte', label: 'is at least', needs_value: true, second: false },
  { value: 'lt', label: 'is less than', needs_value: true, second: false },
  { value: 'lte', label: 'is at most', needs_value: true, second: false },
  { value: 'between', label: 'is between', needs_value: true, second: true },
  { value: 'is_blank', label: 'is blank', needs_value: false, second: false },
  { value: 'is_not_blank', label: 'is not blank', needs_value: false, second: false },
  { value: 'in', label: 'is any of (comma separated)', needs_value: true, second: false },
  { value: 'not_in', label: 'is none of (comma separated)', needs_value: true, second: false },
]

export const BUCKETS: { value: string; label: string }[] = [
  { value: 'VALUE', label: 'As stored' },
  { value: 'DAY', label: 'Day' },
  { value: 'WEEK', label: 'Week' },
  { value: 'MONTH', label: 'Month' },
  { value: 'QUARTER', label: 'Quarter' },
  { value: 'YEAR', label: 'Year' },
]

export function emptyColumn(index = 0): ReportColumn {
  return {
    key: index ? `column_${index + 1}` : 'column_1',
    label: '',
    kind: 'DATA',
    column_name: '',
    related_table: '',
    related_key_column: '',
    formula: '',
    data_type: 'text',
    decimals: 2,
    prefix: '',
    suffix: '',
    aggregate: 'NONE',
    show_total: false,
    hidden: false,
    condition_logic: 'AND',
    width: 0,
    conditions: [],
  }
}

export function emptyDesign(): ReportDesign {
  return {
    name: '',
    description: '',
    report_type: 'TABULAR',
    source_table: '',
    date_basis: 'NONE',
    date_column: '',
    filter_logic: 'AND',
    show_totals: true,
    page_size: 50,
    empty_text: '',
    matrix_value_key: '',
    matrix_aggregate: 'SUM',
    matrix_show_totals: true,
    visibility: 'private',
    columns: [],
    filters: [],
    runtime_filters: [],
    groupings: [],
    sorts: [],
    grants: [],
  }
}

export const EMPTY_RUN: ReportRun = {
  report_type: 'TABULAR', columns: [], rows: [], totals: null, grouped: false, matrix: false,
  total_rows: 0, page: 1, page_size: 50, pages: 1, warnings: [], stats: {}, date_basis: 'NONE',
  date_from: '', date_to: '', notes: [], generated_at: '',
}

/** Server values arrive formatted (1,234.50) for the screen but must export as numbers. */
export function numericValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const cleaned = String(value).replaceAll(',', '').replace(/[^0-9.\-]/g, '')
  const parsed = Number(cleaned)
  return Number.isFinite(parsed) ? parsed : null
}

export function keyFromLabel(label: string, taken: string[]): string {
  const base = label.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'column'
  const safe = /^[a-z]/.test(base) ? base : `c_${base}`
  let candidate = safe.slice(0, 40)
  let index = 2
  while (taken.includes(candidate)) {
    candidate = `${safe.slice(0, 36)}_${index}`
    index += 1
  }
  return candidate
}

export function visibilityLabel(visibility: string): string {
  return ({ private: 'Only me', internal: 'Everyone in this workspace', shared: 'Only the people I name' } as Record<string, string>)[visibility] || visibility
}

export function reportTypeLabel(type: string): string {
  return ({ TABULAR: 'Detail rows', MATRIX: 'Matrix cross-tab' } as Record<string, string>)[type] || type
}

export function aggregateLabel(aggregate: string): string {
  return ({
    NONE: 'No summary', SUM: 'Total', AVG: 'Average', MIN: 'Lowest', MAX: 'Highest',
    COUNT: 'Count of rows', COUNT_DISTINCT: 'Count of distinct values', FIRST: 'First value',
    LAST: 'Last value', PRODUCT: 'Product',
  } as Record<string, string>)[aggregate] || aggregate
}

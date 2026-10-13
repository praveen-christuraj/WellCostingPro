import type { ColDef } from 'ag-grid-community'

// Typed shapes of the Database Browser API (backend/app/api/database_browser.py).
export type ColumnKind = 'text' | 'number' | 'date' | 'boolean'

export type CatalogueItem = {
  name: string
  group: string
  column_count: number
  row_count: number
  scope: string
  primary_key: string[]
  has_timestamps: boolean
}

export type TableCatalogue = {
  items: CatalogueItem[]
  total_tables: number
  total_rows: number
  excluded_tables: number
  hidden_columns: number
}

export type ColumnInfo = {
  position: number
  name: string
  data_type: string
  kind: ColumnKind
  nullable: boolean
  primary_key: boolean
  unique: boolean
  indexed: boolean
  foreign_key: string
  default: string
  max_length: number | null
}

export type IndexInfo = { name: string; columns: string; unique: boolean }

export type TableStructure = {
  name: string
  group: string
  scope: string
  row_count: number
  columns: ColumnInfo[]
  indexes: IndexInfo[]
  hidden_columns: number
}

export type TableRows = {
  name: string
  columns: string[]
  primary_key: string[]
  items: Record<string, unknown>[]
  shown: number
  total: number
  truncated: boolean
  preview_limit: number
}

// Grid rows carry a synthetic key so AG Grid never collapses rows that share a primary key shape.
export type GridRow = Record<string, unknown> & { __rowKey: string }

export const ROW_KEY = '__rowKey'

export const yesNo = (value: boolean) => (value ? 'Yes' : 'No')

export const withRowKeys = (items: Record<string, unknown>[]): GridRow[] =>
  items.map((item, index) => ({ ...item, [ROW_KEY]: String(index) }))

export function numericValue(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

// Sorts numeric columns by value, not by text ("10" after "9"); blanks sort first.
export function numberComparator(a: unknown, b: unknown): number {
  const x = numericValue(a)
  const y = numericValue(b)
  if (x === null && y === null) return 0
  if (x === null) return -1
  if (y === null) return 1
  return x - y
}

export function formatDateValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  const text = String(value)
  const date = new Date(text)
  if (Number.isNaN(date.getTime())) return text
  return /T\d{2}:/.test(text) ? date.toLocaleString() : date.toLocaleDateString()
}

// Column definitions for a table's rows. Headers keep the database column name, so the
// grid, exports and Power BI field names all match one another.
export function rowColumnDefs(columns: Pick<ColumnInfo, 'name' | 'kind'>[]): ColDef<GridRow>[] {
  return columns.map(column => {
    const def: ColDef<GridRow> = { headerName: column.name, field: column.name, minWidth: 140 }
    if (column.kind === 'number') {
      def.comparator = numberComparator
      def.type = 'rightAligned'
      def.minWidth = 120
    }
    if (column.kind === 'date') {
      def.minWidth = 170
      def.valueFormatter = params => formatDateValue(params.value)
    }
    if (column.kind === 'boolean') def.minWidth = 110
    return def
  })
}

export const tableApi = (name: string) => `/database-browser/tables/${encodeURIComponent(name)}`

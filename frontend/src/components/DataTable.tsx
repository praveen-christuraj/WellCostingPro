import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Alert, Box, Button, Collapse, Divider, IconButton, InputAdornment, Menu, MenuItem, Paper, TextField, Typography } from '@mui/material'
import { AddRounded, CloseRounded, DownloadRounded, FilterListRounded, SearchRounded, UploadRounded } from '@mui/icons-material'
import { AgGridReact } from 'ag-grid-react'
import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef, type GridApi } from 'ag-grid-community'
import { useColorMode } from '../context/ThemeContext'
import { control, gridThemeParams } from '../designSystem'
import { exportColumns, exportCsv, exportPdf, exportXlsx } from '../lib/export'
ModuleRegistry.registerModules([AllCommunityModule])

type FieldDef = { field: string; label: string; kind: 'text' | 'date' | 'boolean' }
type Rule = { id: number; field: string; op: string; value: string }
const TEXT_OPS = ['contains', 'equals', 'starts with', 'ends with', 'is empty', 'is not empty']

/**
 * Row-action columns follow one convention across every register: the header is
 * `ACTIONS` (the Database Browser's row link uses `OPEN`). DataTable freezes
 * that column to the right edge of the grid, so its buttons stay on screen
 * while the data columns scroll underneath. A page that sets its own `pinned`
 * (including `pinned: null` to opt out) is left untouched.
 */
const ACTION_HEADERS = new Set(['ACTIONS', 'OPEN'])
function pinActionColumns<T extends object>(columns: ColDef<T>[]): ColDef<T>[] {
  return columns.map(column => {
    const header = typeof column.headerName === 'string' ? column.headerName.trim().toUpperCase() : ''
    if (!ACTION_HEADERS.has(header) || column.pinned !== undefined) return column
    return { ...column, pinned: 'right' as const, lockPinned: true, suppressMovable: true, flex: 0 }
  })
}

/** Space kept free under a full-page grid so its bottom edge clears the fold. */
const FILL_BOTTOM_GAP = 20
/** A full-page grid never collapses below this, even on a short viewport. */
const FILL_MIN_HEIGHT = 288

function fieldDefs<T extends object>(columns: ColDef<T>[]): FieldDef[] {
  return columns
    .filter(c => c.field && c.headerName && c.headerName.toUpperCase() !== 'ACTIONS')
    .map(c => {
      const field = c.field as string
      const kind = /(_at|_date|date$|_on$)/.test(field) ? 'date' : field === 'is_active' ? 'boolean' : 'text'
      return { field, label: c.headerName as string, kind }
    })
}

export function DataTable<T extends object>({ rows, columns, rowKey = 'id', searchPlaceholder = 'Search records...', exportName = 'export', onImport, canExport = true, selectable = false, onSelectionChange, onExport, selectionResetKey, fillHeight = false, fillReserve = 0 }: {
  rows: T[]
  columns: ColDef<T>[]
  // Field that uniquely identifies a row, or a function that builds one from a row record.
  rowKey?: string | ((row: T) => string)
  searchPlaceholder?: string
  exportName?: string
  onImport?: () => void
  canExport?: boolean
  selectable?: boolean
  onSelectionChange?: (selectedRows: T[]) => void
  onExport?: (kind: 'csv' | 'xlsx' | 'pdf', recordCount: number) => Promise<void> | void
  /** Change this value to clear any current row selection in the grid. */
  selectionResetKey?: number | string
  /**
   * Stretch the grid so its bottom edge meets the bottom of the page instead of
   * sizing to the row count. Use on pages whose only (or last) content is this
   * table — the registers (Rigs, Wells, Vendors, …). Leave it off where several
   * tables stack on one page (AFE estimate, daily cost sheet), where it would
   * push the following tables down by a whole screen each.
   */
  fillHeight?: boolean
  /** Extra pixels kept free below a `fillHeight` grid, e.g. for a footnote line under the table. */
  fillReserve?: number
}) {
  const { mode } = useColorMode()
  const gridApi = useRef<GridApi<T> | null>(null)
  const gridWrapRef = useRef<HTMLDivElement | null>(null)
  const [fillPx, setFillPx] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [rules, setRules] = useState<Rule[]>([])
  const [dateField, setDateField] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [exportAnchor, setExportAnchor] = useState<null | HTMLElement>(null)
  const [exportError, setExportError] = useState('')
  const [pageSize, setPageSize] = useState(20)

  useEffect(() => {
    if (selectable && selectionResetKey !== undefined) gridApi.current?.deselectAll()
  }, [selectable, selectionResetKey])

  // Full-page height: size the grid so its bottom edge (in document space)
  // lands at the bottom of the first screenful, leaving FILL_BOTTOM_GAP +
  // fillReserve free. The app root is zoomed (`#root { zoom: 0.875 }`), so
  // viewport measurements (getBoundingClientRect / innerHeight) are converted
  // back to layout pixels with the element's own effective zoom — measured,
  // not hardcoded, so this stays correct if the density zoom ever changes.
  // Re-measures on window resize, after the filters panel finishes collapsing,
  // and whenever the page grows or shrinks above the grid (notices, banners).
  useLayoutEffect(() => {
    if (!fillHeight) return
    const wrap = gridWrapRef.current
    if (!wrap) return
    let frame = 0
    const measure = () => {
      const rect = wrap.getBoundingClientRect()
      if (!rect.height || !wrap.offsetHeight) return
      const zoom = rect.height / wrap.offsetHeight || 1
      const documentTop = rect.top + window.scrollY
      const available = (window.innerHeight - documentTop) / zoom - FILL_BOTTOM_GAP - fillReserve
      const next = Math.max(FILL_MIN_HEIGHT, Math.round(available))
      setFillPx(previous => (previous === next ? previous : next))
    }
    const schedule = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(measure)
    }
    schedule()
    // The filters Collapse animates for ~300ms; measure again once it settles.
    const settle = window.setTimeout(schedule, 350)
    window.addEventListener('resize', schedule)
    const observer = typeof ResizeObserver !== 'undefined' && document.body ? new ResizeObserver(schedule) : null
    if (observer && document.body) observer.observe(document.body)
    return () => {
      cancelAnimationFrame(frame)
      window.clearTimeout(settle)
      window.removeEventListener('resize', schedule)
      observer?.disconnect()
    }
  }, [fillHeight, fillReserve, filtersOpen])

  const fields = useMemo(() => fieldDefs(columns), [columns])
  const dateFields = useMemo(() => fields.filter(f => f.kind === 'date'), [fields])
  const exportCols = useMemo(() => exportColumns(columns), [columns])
  const activeFilters = rules.filter(r => r.value || r.op === 'is empty' || r.op === 'is not empty').length + (dateField && (dateFrom || dateTo) ? 1 : 0)

  const rawValue = (row: T, field: string) => (row as Record<string, unknown>)[field]
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter(row => {
      if (q && !exportCols.some(c => c.value(row).toLowerCase().includes(q))) return false
      for (const rule of rules) {
        const raw = rawValue(row, rule.field)
        const value = String(raw ?? '').toLowerCase()
        const target = rule.value.trim().toLowerCase()
        if (rule.op === 'is empty' && value !== '') return false
        if (rule.op === 'is not empty' && value === '') return false
        if (rule.op === 'contains' && !value.includes(target)) return false
        if (rule.op === 'equals' && value !== target) return false
        if (rule.op === 'starts with' && !value.startsWith(target)) return false
        if (rule.op === 'ends with' && !value.endsWith(target)) return false
      }
      if (dateField && (dateFrom || dateTo)) {
        const value = rawValue(row, dateField)
        if (!value) return false
        const day = new Date(value as string).getTime()
        if (dateFrom && day < new Date(`${dateFrom}T00:00:00`).getTime()) return false
        if (dateTo && day > new Date(`${dateTo}T23:59:59.999`).getTime()) return false
      }
      return true
    })
  }, [rows, search, rules, dateField, dateFrom, dateTo, exportCols])

  // Grid skin comes from the shared design tokens, so it always matches the MUI theme.
  const gridTheme = useMemo(() => themeQuartz.withParams(gridThemeParams(mode)), [mode])
  // Only the grid sees the pinned copy; search/filter/export keep the page's columns.
  const gridColumns = useMemo(() => pinActionColumns(columns), [columns])
  // AG Grid draws the header and the pagination bar inside the same box as the
  // rows, so a content-sized grid needs room for both (the pagination bar is
  // ~44px at the shared grid spacing) on top of the rows it can show.
  const gridChrome = control.gridHeader + 44
  const contentHeight = Math.min(720, Math.max(260, gridChrome + Math.min(visible.length, pageSize) * control.gridRow))
  const gridHeight = fillHeight ? fillPx ?? contentHeight : contentHeight

  const doExport = async (kind: 'csv' | 'xlsx' | 'pdf') => {
    setExportAnchor(null)
    setExportError('')
    const stamp = new Date().toISOString().slice(0, 10)
    const name = `${exportName}-${stamp}`
    try {
      if (onExport) await onExport(kind, visible.length)
      if (kind === 'csv') exportCsv(`${name}.csv`, visible, exportCols)
      if (kind === 'xlsx') await exportXlsx(`${name}.xlsx`, visible, exportCols)
      if (kind === 'pdf') await exportPdf(`${name}.pdf`, exportName, visible, exportCols)
    } catch (error) {
      setExportError(error instanceof Error ? error.message : 'Export could not be completed')
    }
  }

  const updateRule = (id: number, patch: Partial<Rule>) => setRules(rs => rs.map(r => r.id === id ? { ...r, ...patch } : r))
  const addRule = () => setRules(rs => [...rs, { id: Date.now(), field: fields[0]?.field || '', op: 'contains', value: '' }])
  const clearFilters = () => { setRules([]); setDateField(''); setDateFrom(''); setDateTo('') }

  return <Paper variant="outlined" sx={{ borderColor: 'divider', overflow: 'hidden', borderRadius: 2 }}>
    <Box display="flex" justifyContent="space-between" alignItems="center" sx={{ p: 2.2, gap: 2, flexWrap: 'wrap' }}>
      <Box display="flex" alignItems="center" gap={1.2} flexWrap="wrap">
        <TextField placeholder={searchPlaceholder} aria-label={searchPlaceholder} value={search} onChange={e => setSearch(e.target.value)} size="small" sx={{ width: { xs: '100%', sm: 260 } }} InputProps={{ startAdornment: <InputAdornment position="start"><SearchRounded sx={{ color: 'text.secondary', fontSize: 19 }}/></InputAdornment> }}/>
        <Button size="small" startIcon={<FilterListRounded sx={{ fontSize: 18 }}/>} onClick={() => setFiltersOpen(o => !o)} color={activeFilters ? 'primary' : 'inherit'} aria-expanded={filtersOpen}>Filters{activeFilters ? ` (${activeFilters})` : ''}</Button>
        {onImport && <Button size="small" color="inherit" startIcon={<UploadRounded sx={{ fontSize: 18 }}/>} onClick={onImport}>Import</Button>}
        {canExport && <Button size="small" color="inherit" startIcon={<DownloadRounded sx={{ fontSize: 18 }}/>} onClick={e => setExportAnchor(e.currentTarget)}>Export</Button>}
        {canExport && <Menu anchorEl={exportAnchor} open={!!exportAnchor} onClose={() => setExportAnchor(null)}>
          <MenuItem onClick={() => doExport('csv')}>Export as CSV (.csv)</MenuItem>
          <MenuItem onClick={() => doExport('xlsx')}>Export as Excel (.xlsx)</MenuItem>
          <MenuItem onClick={() => doExport('pdf')}>Export as PDF (.pdf)</MenuItem>
        </Menu>}
      </Box>
      <Typography fontSize={12} color="text.secondary" className="tnum" aria-live="polite">{visible.length} of {rows.length} {rows.length === 1 ? 'record' : 'records'}</Typography>
    </Box>
    {exportError && <Alert severity="error" onClose={() => setExportError('')} sx={{ mx: 2.2, mb: 1.5 }}>{exportError}</Alert>}
    <Collapse in={filtersOpen} unmountOnExit>
      <Box sx={{ px: 2.2, pb: 2.2 }}>
        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 2 }}>
          <Box display="flex" justifyContent="space-between" alignItems="center" mb={1.5}>
            <Typography fontWeight={800} fontSize={12} textTransform="uppercase" letterSpacing={0.8}>Filter conditions</Typography>
            <Box display="flex" gap={1}>
              {fields.length > 0 && <Button size="small" startIcon={<AddRounded sx={{ fontSize: 16 }}/>} onClick={addRule}>Add condition</Button>}
              {(rules.length > 0 || dateField) && <Button size="small" color="inherit" startIcon={<CloseRounded sx={{ fontSize: 16 }}/>} onClick={clearFilters}>Clear all</Button>}
            </Box>
          </Box>
          {rules.length === 0 && <Typography fontSize={12} color="text.secondary" mb={1.5}>No conditions. Quick search above covers all columns; add conditions for precise filtering.</Typography>}
          {rules.map(rule => (
            <Box key={rule.id} display="flex" gap={1} alignItems="center" flexWrap="wrap" mb={1}>
              <TextField select size="small" label="Column" value={rule.field} onChange={e => updateRule(rule.id, { field: e.target.value })} sx={{ minWidth: 150 }}>
                {fields.map(f => <MenuItem key={f.field} value={f.field}>{f.label}</MenuItem>)}
              </TextField>
              <TextField select size="small" label="Operator" value={rule.op} onChange={e => updateRule(rule.id, { op: e.target.value })} sx={{ minWidth: 130 }}>
                {TEXT_OPS.map(op => <MenuItem key={op} value={op}>{op}</MenuItem>)}
              </TextField>
              {rule.op !== 'is empty' && rule.op !== 'is not empty' && (
                fields.find(f => f.field === rule.field)?.kind === 'boolean'
                  ? <TextField select size="small" label="Value" value={rule.value} onChange={e => updateRule(rule.id, { value: e.target.value })} sx={{ minWidth: 130 }}>
                      <MenuItem value="true">true</MenuItem><MenuItem value="false">false</MenuItem>
                    </TextField>
                  : <TextField size="small" label="Value" value={rule.value} onChange={e => updateRule(rule.id, { value: e.target.value })} sx={{ minWidth: 170 }}/>
              )}
              <IconButton size="small" aria-label="Remove condition" onClick={() => setRules(rs => rs.filter(r => r.id !== rule.id))}><CloseRounded sx={{ fontSize: 17 }}/></IconButton>
            </Box>
          ))}
          <Divider sx={{ my: 2 }}/>
          <Typography fontWeight={800} fontSize={12} textTransform="uppercase" letterSpacing={0.8} mb={1.5}>Date &amp; date range</Typography>
          <Box display="flex" gap={1} alignItems="center" flexWrap="wrap">
            <TextField select size="small" label="Date column" value={dateField} onChange={e => setDateField(e.target.value)} sx={{ minWidth: 170 }}>
              <MenuItem value="">None</MenuItem>
              {dateFields.map(f => <MenuItem key={f.field} value={f.field}>{f.label}</MenuItem>)}
            </TextField>
            <TextField size="small" type="date" label="From" value={dateFrom} onChange={e => setDateFrom(e.target.value)} disabled={!dateField} InputLabelProps={{ shrink: true }}/>
            <Typography color="text.secondary" fontSize={12}>to</Typography>
            <TextField size="small" type="date" label="To" value={dateTo} onChange={e => setDateTo(e.target.value)} disabled={!dateField} InputLabelProps={{ shrink: true }}/>
          </Box>
        </Box>
      </Box>
    </Collapse>
    <Box ref={gridWrapRef} sx={{ height: gridHeight, width: '100%' }}>
      <AgGridReact<T>
        theme={gridTheme}
        onGridReady={event => { gridApi.current = event.api }}
        rowData={visible}
        columnDefs={gridColumns}
        defaultColDef={{ sortable: true, resizable: true, flex: 1, minWidth: 120 }}
        rowHeight={control.gridRow}
        headerHeight={control.gridHeader}
        pagination
        paginationPageSize={pageSize}
        paginationPageSizeSelector={[20, 50, 100]}
        onPaginationChanged={e => setPageSize(e.api.paginationGetPageSize())}
        rowSelection={selectable ? { mode: 'multiRow', checkboxes: true, headerCheckbox: true, selectAll: 'filtered' } : undefined}
        onSelectionChanged={event => onSelectionChange?.(event.api.getSelectedRows())}
        getRowId={p => {
          const data = p.data as Record<string, unknown>
          const value = typeof rowKey === 'function' ? (rowKey as (row: T) => string)(p.data as T) : data[rowKey]
          return String(value ?? '')
        }}
        overlayNoRowsTemplate='<span class="grid-empty">No records match the current search or filters.</span>'
        suppressCellFocus
      />
    </Box>
  </Paper>
}

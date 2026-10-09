import { useMemo, useState } from 'react'
import { Box, Button, Collapse, Divider, IconButton, InputAdornment, Menu, MenuItem, Paper, TextField, Typography } from '@mui/material'
import { AddRounded, CloseRounded, DownloadRounded, FilterListRounded, SearchRounded, UploadRounded } from '@mui/icons-material'
import { AgGridReact } from 'ag-grid-react'
import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef } from 'ag-grid-community'
import { useColorMode } from '../context/ThemeContext'
import { exportColumns, exportCsv, exportPdf, exportXlsx } from '../lib/export'
ModuleRegistry.registerModules([AllCommunityModule])

type FieldDef = { field: string; label: string; kind: 'text' | 'date' | 'boolean' }
type Rule = { id: number; field: string; op: string; value: string }
const TEXT_OPS = ['contains', 'equals', 'starts with', 'ends with', 'is empty', 'is not empty']

function fieldDefs<T extends object>(columns: ColDef<T>[]): FieldDef[] {
  return columns
    .filter(c => c.field && c.headerName && c.headerName.toUpperCase() !== 'ACTIONS')
    .map(c => {
      const field = c.field as string
      const kind = /(_at|_date|date$|_on$)/.test(field) ? 'date' : field === 'is_active' ? 'boolean' : 'text'
      return { field, label: c.headerName as string, kind }
    })
}

export function DataTable<T extends object>({ rows, columns, searchPlaceholder = 'Search records...', exportName = 'export', onImport }: {
  rows: T[]; columns: ColDef<T>[]; searchPlaceholder?: string; exportName?: string; onImport?: () => void
}) {
  const { mode } = useColorMode()
  const [search, setSearch] = useState('')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [rules, setRules] = useState<Rule[]>([])
  const [dateField, setDateField] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [exportAnchor, setExportAnchor] = useState<null | HTMLElement>(null)
  const [pageSize, setPageSize] = useState(20)

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
        if (dateTo && day > new Date(`${dateTo}T23:59:59`).getTime()) return false
      }
      return true
    })
  }, [rows, search, rules, dateField, dateFrom, dateTo, exportCols])

  const gridTheme = useMemo(() => themeQuartz.withParams(mode === 'dark'
    ? { accentColor: '#8FB8E4', backgroundColor: '#15273B', borderColor: '#27405C', foregroundColor: '#E6EDF5', headerBackgroundColor: '#1B2F48', headerFontWeight: 700, fontFamily: 'DM Sans, sans-serif', fontSize: 12, rowHoverColor: '#1B2F48', spacing: 10, chromeBackgroundColor: '#1B2F48' }
    : { accentColor: '#123A63', backgroundColor: '#ffffff', borderColor: '#E3E9F0', foregroundColor: '#16283F', headerBackgroundColor: '#F4F6F9', headerFontWeight: 700, fontFamily: 'DM Sans, sans-serif', fontSize: 12, rowHoverColor: '#EDF2F8', spacing: 10 }), [mode])

  const doExport = async (kind: 'csv' | 'xlsx' | 'pdf') => {
    setExportAnchor(null)
    const stamp = new Date().toISOString().slice(0, 10)
    const name = `${exportName}-${stamp}`
    if (kind === 'csv') exportCsv(`${name}.csv`, visible, exportCols)
    if (kind === 'xlsx') await exportXlsx(`${name}.xlsx`, visible, exportCols)
    if (kind === 'pdf') await exportPdf(`${name}.pdf`, exportName, visible, exportCols)
  }

  const updateRule = (id: number, patch: Partial<Rule>) => setRules(rs => rs.map(r => r.id === id ? { ...r, ...patch } : r))
  const addRule = () => setRules(rs => [...rs, { id: Date.now(), field: fields[0]?.field || '', op: 'contains', value: '' }])
  const clearFilters = () => { setRules([]); setDateField(''); setDateFrom(''); setDateTo('') }

  return <Paper variant="outlined" sx={{ borderColor: 'divider', overflow: 'hidden', borderRadius: 2 }}>
    <Box display="flex" justifyContent="space-between" alignItems="center" sx={{ p: 2.2, gap: 2, flexWrap: 'wrap' }}>
      <Box display="flex" alignItems="center" gap={1.2} flexWrap="wrap">
        <TextField placeholder={searchPlaceholder} value={search} onChange={e => setSearch(e.target.value)} size="small" sx={{ width: { xs: '100%', sm: 260 } }} InputProps={{ startAdornment: <InputAdornment position="start"><SearchRounded sx={{ color: 'text.secondary', fontSize: 19 }}/></InputAdornment> }}/>
        <Button size="small" startIcon={<FilterListRounded sx={{ fontSize: 18 }}/>} onClick={() => setFiltersOpen(o => !o)} color={activeFilters ? 'primary' : 'inherit'}>Filters{activeFilters ? ` (${activeFilters})` : ''}</Button>
        {onImport && <Button size="small" color="inherit" startIcon={<UploadRounded sx={{ fontSize: 18 }}/>} onClick={onImport}>Import</Button>}
        <Button size="small" color="inherit" startIcon={<DownloadRounded sx={{ fontSize: 18 }}/>} onClick={e => setExportAnchor(e.currentTarget)}>Export</Button>
        <Menu anchorEl={exportAnchor} open={!!exportAnchor} onClose={() => setExportAnchor(null)}>
          <MenuItem onClick={() => doExport('csv')}>Export as CSV (.csv)</MenuItem>
          <MenuItem onClick={() => doExport('xlsx')}>Export as Excel (.xlsx)</MenuItem>
          <MenuItem onClick={() => doExport('pdf')}>Export as PDF (.pdf)</MenuItem>
        </Menu>
      </Box>
      <Typography fontSize={12} color="text.secondary">{visible.length} of {rows.length} {rows.length === 1 ? 'record' : 'records'}</Typography>
    </Box>
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
    <Box sx={{ height: Math.min(720, Math.max(270, 57 + Math.min(visible.length, pageSize) * 55)), width: '100%' }}>
      <AgGridReact<T>
        theme={gridTheme}
        rowData={visible}
        columnDefs={columns}
        defaultColDef={{ sortable: true, resizable: true, flex: 1, minWidth: 120 }}
        rowHeight={55}
        headerHeight={48}
        pagination
        paginationPageSize={pageSize}
        paginationPageSizeSelector={[20, 50, 100]}
        onPaginationChanged={e => setPageSize(e.api.paginationGetPageSize())}
        getRowId={p => (p.data as { id: string }).id}
        overlayNoRowsTemplate="No records found"
        suppressCellFocus
      />
    </Box>
  </Paper>
}

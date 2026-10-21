import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { ArrowBackRounded, CalendarMonthOutlined, RefreshRounded, WaterDropOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, MenuItem, Paper, TextField, Typography } from '@mui/material'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import {
  MUD_COST_LOSS_METRICS, MUD_COST_LOSS_VIEWS, MUD_COST_MUD_TYPES, mudQuantity,
  type MudCostLossReport, type MudCostLossRow, type MudCostLossView, type MudCostReference,
} from '../lib/mudCost'

const ALL = '__all__'

function dateText(value: string) {
  return value ? new Date(`${value}T00:00:00`).toLocaleDateString() : '—'
}

function Stat({ label, value, note, icon }: { label: string; value: string; note: string; icon: ReactNode }) {
  return <Paper variant="outlined" sx={{ p: 1.7, borderRadius: 2, minWidth: 0 }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={10.5} fontWeight={800} letterSpacing={.7} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon">{icon}</Box>
    </Box>
    <Typography fontSize={22} fontWeight={800} my={.6}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11.2}>{note}</Typography>
  </Paper>
}

export default function ConsumptionLossesReport() {
  const { can } = useAuth()
  const canExport = can('daily-cost:export')
  const [reference, setReference] = useState<MudCostReference | null>(null)
  const [rigId, setRigId] = useState('')
  const [wellId, setWellId] = useState('')
  const [sectionId, setSectionId] = useState(ALL)
  const [scope, setScope] = useState(ALL)
  const [mudType, setMudType] = useState(ALL)
  const [view, setView] = useState<MudCostLossView>('daily')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [report, setReport] = useState<MudCostLossReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    api<MudCostReference>('/mud-cost/reference').then(data => {
      if (!active) return
      setReference(data)
      setRigId(current => current || data.rigs.find(rig => !rig.is_deleted)?.id || '')
    }).catch(caught => {
      if (active) setError(caught instanceof Error ? caught.message : 'Report filters could not be loaded')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const rigOptions = reference?.rigs.filter(rig => !rig.is_deleted) ?? []
  const wellOptions = useMemo(
    () => reference?.wells.filter(well => !well.is_deleted && well.rig_id === rigId) ?? [],
    [reference, rigId],
  )
  const selectedWell = wellOptions.find(well => well.id === wellId) ?? null
  const sectionOptions = selectedWell?.sections.filter(section => section.is_current) ?? []

  useEffect(() => {
    if (!rigId) { setWellId(''); return }
    if (!wellOptions.some(well => well.id === wellId)) setWellId(wellOptions[0]?.id ?? '')
  }, [rigId, wellId, wellOptions])
  useEffect(() => {
    if (sectionId !== ALL && !sectionOptions.some(section => section.id === sectionId)) setSectionId(ALL)
  }, [sectionId, sectionOptions])

  const load = useCallback(async () => {
    if (!rigId || !wellId) { setReport(null); return }
    if (dateFrom && dateTo && dateFrom > dateTo) { setError('The start date must not be after the end date.'); return }
    setLoading(true)
    setError('')
    const params = new URLSearchParams({ rig_id: rigId, well_id: wellId, view })
    if (sectionId !== ALL) params.set('section_id', sectionId)
    if (dateFrom && view !== 'inception') params.set('from', dateFrom)
    if (dateTo) params.set('to', dateTo)
    try {
      setReport(await api<MudCostLossReport>(`/mud-cost/consumption-losses?${params}`))
    } catch (caught) {
      setReport(null)
      setError(caught instanceof Error ? caught.message : 'Consumption and losses could not be loaded')
    } finally { setLoading(false) }
  }, [rigId, wellId, sectionId, view, dateFrom, dateTo, refreshKey])
  useEffect(() => { void load() }, [load])

  const rows = useMemo(() => (report?.rows ?? []).filter(row =>
    (scope === ALL || row.section_scope === scope) && (mudType === ALL || row.mud_type === mudType),
  ), [report, scope, mudType])

  const matrixRows = useMemo(() => {
    const sections = new Map<string, MudCostLossRow>()
    for (const row of rows) {
      const key = `${row.section_scope}:${row.hole_section_id}`
      const current = sections.get(key)
      if (!current) sections.set(key, { ...row })
      else {
        const next = { ...current }
        for (const metric of MUD_COST_LOSS_METRICS) {
          next[metric.key] = String(Number(next[metric.key]) + Number(row[metric.key]))
        }
        next.entry_count += row.entry_count
        sections.set(key, next)
      }
    }
    return [...sections.values()].sort((a, b) => a.section_label.localeCompare(b.section_label))
  }, [rows])

  const filteredTotals = useMemo(() => ({
    surface: rows.reduce((sum, row) => sum + Number(row.surface_loss_total), 0),
    other: rows.reduce((sum, row) => sum + Number(row.other_loss_total), 0),
    total: rows.reduce((sum, row) => sum + Number(row.total_losses), 0),
  }), [rows])

  const drill = (row: MudCostLossRow) => {
    setView('daily')
    setSectionId(row.section_id)
    setDateFrom(row.first_entry_date)
    setDateTo(row.last_entry_date)
  }

  const columns = useMemo<ColDef<MudCostLossRow>[]>(() => [
    { headerName: 'PERIOD', field: 'period_label', minWidth: 175 },
    { headerName: 'SECTION', field: 'section_name', minWidth: 170 },
    { headerName: 'SCOPE', field: 'section_scope', minWidth: 115 },
    { headerName: 'MUD TYPE', field: 'mud_type_label', minWidth: 175 },
    ...MUD_COST_LOSS_METRICS.map(metric => ({
      headerName: metric.label.toUpperCase(), field: metric.key, minWidth: metric.group.includes('total') ? 155 : 145,
      valueFormatter: (params: { value: unknown }) => mudQuantity(String(params.value ?? '0')),
    } as ColDef<MudCostLossRow>)),
    { headerName: 'ENTRIES', field: 'entry_count', minWidth: 105 },
    {
      headerName: 'ACTIONS', width: 132, minWidth: 132, sortable: false, filter: false,
      cellRenderer: (params: ICellRendererParams<MudCostLossRow>) => params.data && view !== 'daily'
        ? <Button size="small" onClick={() => drill(params.data!)}>Drill to dates</Button>
        : <Typography color="text.secondary" fontSize={11.5} sx={{ py: 1 }}>Daily detail</Typography>,
    },
  ], [view])

  const auditExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/mud-cost/export-audit', { method: 'POST', body: body({
      module: 'consumption_losses', format, record_count: recordCount,
      rig_id: rigId, well_id: wellId, section_id: sectionId === ALL ? '' : sectionId,
      view, date_from: dateFrom || null, date_to: dateTo || null,
    }) })
  }

  return <>
    <PageHeading
      eyebrow="REPORTS / CONSUMPTION & LOSSES"
      title="Consumption and losses"
      subtitle="Section- and mud-type loss matrix with date-wise, month-wise and required-range drill-through. Surface losses plus Other losses always equal Total losses."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/reports" variant="outlined" startIcon={<ArrowBackRounded/>}>Reports</Button>
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => setRefreshKey(value => value + 1)} disabled={loading}>Refresh</Button>
      </Box>}
    />
    <Paper variant="outlined" sx={{ p: 1.7, borderRadius: 2, mb: 1.7 }}>
      <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' } }}>
        <TextField select size="small" label="Rig" value={rigId} onChange={event => { setRigId(event.target.value); setSectionId(ALL) }}>
          <MenuItem value="">Select rig</MenuItem>{rigOptions.map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Well" value={wellId} onChange={event => { setWellId(event.target.value); setSectionId(ALL) }}>
          <MenuItem value="">Select well</MenuItem>{wellOptions.map(well => <MenuItem key={well.id} value={well.id}>{well.display_name}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Section" value={sectionId} onChange={event => setSectionId(event.target.value)}>
          <MenuItem value={ALL}>All sections</MenuItem>{sectionOptions.map(section => <MenuItem key={section.id} value={section.id}>{section.display_name}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="View" value={view} onChange={event => setView(event.target.value as MudCostLossView)}>
          {MUD_COST_LOSS_VIEWS.map(option => <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Scope" value={scope} onChange={event => setScope(event.target.value)}>
          <MenuItem value={ALL}>All scopes</MenuItem><MenuItem value="drilling">Drilling</MenuItem><MenuItem value="completion">Completion</MenuItem>
        </TextField>
        <TextField select size="small" label="Mud type" value={mudType} onChange={event => setMudType(event.target.value)}>
          <MenuItem value={ALL}>All mud types</MenuItem>{MUD_COST_MUD_TYPES.map(option => <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>)}
        </TextField>
        <TextField size="small" type="date" label="From date" value={dateFrom} disabled={view === 'inception'} onChange={event => setDateFrom(event.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField size="small" type="date" label="To date" value={dateTo} onChange={event => setDateTo(event.target.value)} InputLabelProps={{ shrink: true }}/>
      </Box>
      <Typography color="text.secondary" fontSize={11.2} mt={1}>{MUD_COST_LOSS_VIEWS.find(option => option.value === view)?.help}</Typography>
    </Paper>
    <ErrorMessage message={error}/>
    <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: 'repeat(3, minmax(0, 1fr))' }} gap={1.4} mb={1.7}>
      <Stat label="Surface losses" value={mudQuantity(filteredTotals.surface)} note="Five surface-loss rows" icon={<WaterDropOutlined/>}/>
      <Stat label="Other losses" value={mudQuantity(filteredTotals.other)} note="Five other-loss rows" icon={<WaterDropOutlined/>}/>
      <Stat label="Total losses" value={mudQuantity(filteredTotals.total)} note="Surface + Other losses" icon={<CalendarMonthOutlined/>}/>
    </Box>
    {loading && !report ? <Paper variant="outlined" sx={{ minHeight: 220, display: 'grid', placeItems: 'center', borderRadius: 2 }}><CircularProgress size={28}/></Paper> : <>
      <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, mb: 1.7, overflowX: 'auto' }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} mb={1.1}>
          <Box><Typography fontWeight={800} fontSize={14}>Cumulative loss matrix</Typography><Typography color="text.secondary" fontSize={11.2}>Sections and mud types are columns; loss categories and totals are rows.</Typography></Box>
          <Tag tone="info">{matrixRows.length} section{matrixRows.length === 1 ? '' : 's'}</Tag>
        </Box>
        <Box component="table" sx={{ borderCollapse: 'collapse', width: '100%', minWidth: Math.max(720, matrixRows.length * 155), '& th, & td': { border: '1px solid', borderColor: 'divider', px: 1, py: .75, fontSize: 11.5 }, '& thead th': { bgcolor: 'action.hover' }, '& tbody th': { textAlign: 'left' }, '& td': { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }, '& tr[data-total="true"]': { bgcolor: 'action.hover', fontWeight: 800 } }}>
          <thead><tr><th>Loss measure</th>{matrixRows.map(row => <th key={`${row.section_scope}:${row.hole_section_id}`}>{row.section_name}<Typography component="span" display="block" color="text.secondary" fontSize={10.5}>{row.mud_type_label}</Typography></th>)}</tr></thead>
          <tbody>
            <tr><th colSpan={Math.max(2, matrixRows.length + 1)}>Surface losses</th></tr>
            {MUD_COST_LOSS_METRICS.filter(metric => metric.group === 'surface' || metric.group === 'surface-total').map(metric => <tr key={metric.key} data-total={metric.group === 'surface-total'}><th>{metric.label}</th>{matrixRows.map(row => <td key={`${row.section_scope}:${row.hole_section_id}`}>{mudQuantity(row[metric.key])}</td>)}</tr>)}
            <tr><th colSpan={Math.max(2, matrixRows.length + 1)}>Other losses</th></tr>
            {MUD_COST_LOSS_METRICS.filter(metric => metric.group === 'other' || metric.group === 'other-total').map(metric => <tr key={metric.key} data-total={metric.group === 'other-total'}><th>{metric.label}</th>{matrixRows.map(row => <td key={`${row.section_scope}:${row.hole_section_id}`}>{mudQuantity(row[metric.key])}</td>)}</tr>)}
            {MUD_COST_LOSS_METRICS.filter(metric => metric.group === 'grand-total').map(metric => <tr key={metric.key} data-total="true"><th>{metric.label}</th>{matrixRows.map(row => <td key={`${row.section_scope}:${row.hole_section_id}`}>{mudQuantity(row[metric.key])}</td>)}</tr>)}
            {!matrixRows.length && <tr><td colSpan={2}><Alert severity="info">No loss records match these filters.</Alert></td></tr>}
          </tbody>
        </Box>
      </Paper>
      <DataTable rows={rows} columns={columns} rowKey="id" searchPlaceholder="Search period, section, scope, mud type or loss value…" exportName={`consumption-losses-${view}`} canExport={canExport} onExport={canExport ? auditExport : undefined}/>
      <Typography color="text.secondary" fontSize={11.2} mt={1}>Period: {dateFrom ? dateText(dateFrom) : 'Inception'} to {dateTo ? dateText(dateTo) : 'latest entry'} · {rows.reduce((sum, row) => sum + row.entry_count, 0)} source entries.</Typography>
    </>}
  </>
}

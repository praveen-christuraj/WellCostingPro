import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import {
  AddRounded, DeleteForeverOutlined, DeleteOutlineRounded, EventNoteOutlined,
  FactCheckOutlined, FilterAltOffOutlined, InsightsOutlined, Inventory2Outlined, RestoreRounded,
  RefreshRounded, TaskAltOutlined, WarningAmberRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, MenuItem, Paper, TextField, Typography, useTheme,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import {
  dailyMoney, DAILY_COST_STATUSES, displayDate, entryQuery, localToday,
  type DailyCostDay, type DailyCostEntry, type DailyCostOverview, type DailyCostReference,
  type DailyCostStatus,
} from '../lib/dailyCost'

type PendingAction = { kind: 'delete' | 'restore' | 'purge'; rows: DailyCostEntry[] }

function StatCard({ label, value, hint, icon, tone = 'default' }: {
  label: string; value: string | number; hint: string; icon: ReactNode; tone?: 'default' | 'warning'
}) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2, borderRadius: 2, minWidth: 0 }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={10.5} fontWeight={800} letterSpacing={.75} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon" sx={tone === 'warning' ? { color: 'warning.dark', bgcolor: 'warning.light' } : undefined}>{icon}</Box>
    </Box>
    <Typography className="stat-value" sx={{ fontSize: 25, my: 1, overflowWrap: 'anywhere' }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11.3}>{hint}</Typography>
  </Paper>
}

function prettyCurrencyMap(map: Record<string, string>): string {
  const items = Object.entries(map)
  return items.length ? items.map(([code, value]) => dailyMoney(value, code)).join(' · ') : '—'
}

function isValidCostDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

export default function DailyCostManagement() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const theme = useTheme()
  const [params, setParams] = useSearchParams()
  const deletedView = params.get('view') === 'deleted'
  const [overview, setOverview] = useState<DailyCostOverview | null>(null)
  const [rows, setRows] = useState<DailyCostEntry[]>([])
  const [reference, setReference] = useState<DailyCostReference | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<DailyCostEntry[]>([])
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [actionError, setActionError] = useState('')
  const [actionBusy, setActionBusy] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [wellId, setWellId] = useState('')
  const [afeId, setAfeId] = useState('')
  const [costDate, setCostDate] = useState(localToday())
  const [remarks, setRemarks] = useState('')
  const [chartCurrency, setChartCurrency] = useState('')
  const [filterWell, setFilterWell] = useState('')
  const [filterAfe, setFilterAfe] = useState('')
  const [filterStatus, setFilterStatus] = useState<'' | DailyCostStatus>('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const filterQuery = entryQuery({
    well_id: filterWell, afe_id: filterAfe, status: filterStatus, from: dateFrom, to: dateTo,
  })
  const filtersActive = Boolean(filterWell || filterAfe || filterStatus || dateFrom || dateTo)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    setSelected([])
    try {
      const [overviewData, entries, ref] = await Promise.all([
        api<DailyCostOverview>('/daily-cost/overview'),
        api<DailyCostEntry[]>(deletedView ? '/daily-cost/entries/deleted' : `/daily-cost/entries${filterQuery}`),
        api<DailyCostReference>('/daily-cost/reference'),
      ])
      setOverview(overviewData)
      setRows(entries)
      setReference(ref)
      const currencies = Object.keys(overviewData.actual_to_date_by_currency)
      setChartCurrency(current => currencies.includes(current) ? current : currencies[0] ?? '')
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : 'Daily Cost Management could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [deletedView, filterQuery])

  useEffect(() => { void load() }, [load])

  const wells = useMemo(() => reference?.wells.filter(well => well.status === 'active' && well.config_status === 'configured') ?? [], [reference])
  const selectedWell = wells.find(well => well.id === wellId)
  const afes = useMemo(() => reference?.afes.filter(afe => afe.well_id === wellId) ?? [], [reference, wellId])
  const selectedAfe = afes.find(afe => afe.id === afeId)
  const createDateValid = isValidCostDate(costDate)
  const selectedDuplicate = rows.find(row => row.well_id === wellId && row.afe_id === afeId && row.cost_date === costDate)
  // Configuring the well sub activity in Rig & Well Management is mandatory
  // before daily cost entry: every line is recorded under an Activity + Sub activity.
  const wellSubActivities = useMemo(() => reference?.sub_activities.filter(item => item.well_id === wellId) ?? [], [reference, wellId])
  const missingSubActivities = Boolean(selectedWell) && wellSubActivities.length === 0

  useEffect(() => {
    if (!createOpen || !reference) return
    if (!wellId && wells.length) setWellId(wells[0].id)
    if (wellId && !afes.some(afe => afe.id === afeId)) setAfeId(afes[0]?.id ?? '')
  }, [createOpen, reference, wellId, afeId, wells, afes])

  const openCreate = () => {
    setCreateError('')
    setRemarks('')
    setCostDate(localToday())
    const firstWell = wells[0]
    const firstAfe = reference?.afes.find(item => item.well_id === firstWell?.id)
    setWellId(firstWell?.id ?? '')
    setAfeId(firstAfe?.id ?? '')
    setCreateOpen(true)
  }

  const createEntry = async () => {
    if (!selectedWell || !selectedAfe) {
      setCreateError('Choose a configured well and a saved AFE estimate.')
      return
    }
    if (missingSubActivities) {
      setCreateError('Configure the well sub activities for this well in Rig & Well Management before entering daily costs.')
      return
    }
    if (!isValidCostDate(costDate)) {
      setCreateError('Enter a valid cost date before creating the daily sheet.')
      return
    }
    const existing = rows.find(row => row.well_id === selectedWell.id && row.afe_id === selectedAfe.id && row.cost_date === costDate)
    if (existing) {
      setCreateError(`A daily cost sheet already exists for ${displayDate(costDate)} under ${selectedAfe.afe_code}. Open the existing sheet above instead.`)
      return
    }
    setCreating(true)
    setCreateError('')
    try {
      const created = await api<DailyCostDay>('/daily-cost/entries', {
        method: 'POST', body: body({ well_id: selectedWell.id, afe_id: selectedAfe.id, cost_date: costDate, remarks }),
      })
      setCreateOpen(false)
      navigate(`/daily-cost/entries/${created.entry.id}`)
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'The daily cost sheet could not be created'
      setCreateError(message)
      if (message.toLowerCase().includes('already exists')) void load()
    } finally {
      setCreating(false)
    }
  }

  const act = async () => {
    if (!pending) return
    setActionBusy(true)
    setActionError('')
    try {
      const ids = pending.rows.map(row => row.id)
      if (pending.kind === 'delete') {
        if (ids.length === 1) await api(`/daily-cost/entries/${ids[0]}`, { method: 'DELETE' })
        else await api('/daily-cost/entries/bulk-delete', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} sheet${ids.length === 1 ? '' : 's'} moved to Deleted Entries.`)
      } else if (pending.kind === 'restore') {
        if (ids.length === 1) await api(`/daily-cost/entries/${ids[0]}/restore`, { method: 'POST' })
        else await api('/daily-cost/entries/bulk-restore', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} sheet${ids.length === 1 ? '' : 's'} restored to the register.`)
      } else if (ids.length === 1) {
        await api(`/daily-cost/entries/${ids[0]}/permanent`, { method: 'DELETE' })
        setNotice('Daily cost sheet permanently deleted.')
      } else {
        await api('/daily-cost/entries/bulk-permanent-delete', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} sheets permanently deleted.`)
      }
      setPending(null)
      await load()
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'The requested action could not be completed')
    } finally {
      setActionBusy(false)
    }
  }

  const exportAudit = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/daily-cost/export-audit', { method: 'POST', body: body({
      module: deletedView ? 'deleted' : 'entries', format, record_count: recordCount, include_deleted: deletedView,
    }) })
  }

  // Daily basis: running actual for the same AFE, oldest sheet first, so a cost
  // accountant can read each day against the budget left at that point.
  const cumulativeById = useMemo(() => {
    const running = new Map<string, number>()
    const result = new Map<string, string>()
    const ordered = [...rows].sort((left, right) => left.cost_date.localeCompare(right.cost_date))
    for (const row of ordered) {
      const total = (running.get(row.afe_id) ?? 0) + Number(row.total_cost)
      running.set(row.afe_id, total)
      result.set(row.id, total.toFixed(2))
    }
    return result
  }, [rows])

  const columns = useMemo<ColDef<DailyCostEntry>[]>(() => [
    { headerName: 'DATE', field: 'cost_date', minWidth: 125, width: 130, valueFormatter: params => displayDate(String(params.value ?? '')) },
    { headerName: 'DAILY SHEET', field: 'daily_cost_code', minWidth: 230, flex: 1.1 },
    { headerName: 'WELL', field: 'well_code', minWidth: 150, valueGetter: params => `${params.data?.well_code ?? ''} · ${params.data?.well_name ?? ''}` },
    { headerName: 'AFE', field: 'afe_code', minWidth: 165, valueGetter: params => `${params.data?.afe_code ?? ''} · ${params.data?.afe_name ?? ''}` },
    { headerName: 'DAILY TOTAL', field: 'total_cost', minWidth: 160, valueFormatter: params => dailyMoney(String(params.value ?? '0'), params.data?.standard_currency) },
    { headerName: 'LINES', field: 'services_count', minWidth: 105, valueGetter: params => {
      const row = params.data
      return row ? row.services_count + row.consumables_count + row.tangibles_count : 0
    } },
    { headerName: 'UPA / NPT', field: 'upa_total', minWidth: 160, valueGetter: params => params.data
      ? `${dailyMoney(params.data.upa_total, params.data.standard_currency)} / ${dailyMoney(params.data.npt_total, params.data.standard_currency)}` : '—' },
    { headerName: 'ACTUAL TO DATE', field: 'id', minWidth: 165, valueGetter: params => params.data ? dailyMoney(cumulativeById.get(params.data.id) ?? '0', params.data.standard_currency) : '—',
      cellRenderer: (params: ICellRendererParams<DailyCostEntry>) => {
        const row = params.data
        if (!row) return null
        const value = Number(cumulativeById.get(row.id) ?? 0)
        return <Typography fontSize={12} fontWeight={700} color={value > 0 ? 'text.primary' : 'text.secondary'}>{dailyMoney(value, row.standard_currency)}</Typography>
      } },
    { headerName: 'STATUS', field: 'status', minWidth: 120, cellRenderer: (params: ICellRendererParams<DailyCostEntry>) => <Tag tone={params.value === 'submitted' ? 'success' : 'info'}>{DAILY_COST_STATUSES[params.value as 'draft' | 'submitted'] ?? String(params.value ?? '')}</Tag> },
    { headerName: 'ACTIONS', field: 'id', minWidth: deletedView ? 205 : 170, width: deletedView ? 215 : 180, sortable: false,
      cellRenderer: (params: ICellRendererParams<DailyCostEntry>) => {
        const record = params.data
        if (!record) return null
        return <Box display="flex" alignItems="center" height="100%" gap={.35}>
          <Button size="small" component={RouterLink} to={`/daily-cost/entries/${record.id}`}>Open</Button>
          {deletedView ? <>
            {can('daily-cost:restore') && <Button size="small" onClick={() => { setActionError(''); setPending({ kind: 'restore', rows: [record] }) }}>Restore</Button>}
            {can('daily-cost:permanent-delete') && <Button size="small" color="error" aria-label={`Permanently delete ${record.daily_cost_code}`} onClick={() => { setActionError(''); setPending({ kind: 'purge', rows: [record] }) }}><DeleteForeverOutlined sx={{ fontSize: 17 }}/></Button>}
          </> : can('daily-cost:delete') && record.status === 'draft' && <Button size="small" color="error" aria-label={`Move ${record.daily_cost_code} to Deleted Entries`} onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: [record] }) }}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></Button>}
        </Box>
      },
    },
  ], [can, deletedView, cumulativeById])

  const currencies = Object.keys(overview?.actual_to_date_by_currency ?? {})
  const chartRows = overview?.trend.filter(point => point.currency === chartCurrency) ?? []
  const chartOption: EChartsOption = {
    animation: false,
    grid: { left: 16, right: 18, top: 24, bottom: 35, containLabel: true },
    legend: { top: 0, textStyle: { color: theme.palette.text.secondary }, itemWidth: 12, itemHeight: 8 },
    tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => dailyMoney(Number(value), chartCurrency) },
    xAxis: { type: 'category', data: chartRows.map(point => point.cost_date.slice(5)), axisLabel: { color: theme.palette.text.secondary }, axisLine: { lineStyle: { color: theme.palette.divider } } },
    yAxis: { type: 'value', axisLabel: { color: theme.palette.text.secondary }, splitLine: { lineStyle: { color: theme.palette.divider } } },
    series: [
      { name: 'Actual', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, itemStyle: { color: theme.palette.primary.main }, lineStyle: { width: 2.5 }, areaStyle: { color: `${theme.palette.primary.main}20` }, data: chartRows.map(point => Number(point.actual)) },
      { name: 'UPA', type: 'line', smooth: true, symbolSize: 4, itemStyle: { color: theme.palette.warning.main }, lineStyle: { width: 1.7 }, data: chartRows.map(point => Number(point.upa)) },
      { name: 'NPT', type: 'line', smooth: true, symbolSize: 4, itemStyle: { color: theme.palette.error.main }, lineStyle: { width: 1.7 }, data: chartRows.map(point => Number(point.npt)) },
    ],
  }

  const pendingCount = pending?.rows.length ?? 0
  const actionTitle = pending?.kind === 'delete'
    ? `Move ${pendingCount === 1 ? pending?.rows[0].daily_cost_code : `${pendingCount} sheets`} to Deleted Entries?`
    : pending?.kind === 'restore'
      ? `Restore ${pendingCount === 1 ? pending?.rows[0].daily_cost_code : `${pendingCount} sheets`}?`
      : `Permanently delete ${pendingCount === 1 ? pending?.rows[0].daily_cost_code : `${pendingCount} sheets`}?`
  const actionSubtitle = pending?.kind === 'delete'
    ? 'Only Draft daily sheets can be deleted. Their rates, charges and audit records remain recoverable.'
    : pending?.kind === 'restore'
      ? 'Restoring returns the sheets to the active register. A duplicate well, AFE and date will be rejected.'
      : 'Permanent deletion removes the daily sheets and their item lines. Immutable AFE and rate baselines are retained. This cannot be undone.'

  return <>
    <PageHeading
      eyebrow={deletedView ? 'DAILY COST MANAGEMENT / DELETED ENTRIES' : 'DAILY COST MANAGEMENT / WELL DAY ACTUALS'}
      title={deletedView ? 'Deleted daily sheets' : 'Daily Cost Management'}
      subtitle={deletedView
        ? 'Restore a recoverable sheet or permanently remove an obsolete record.'
        : 'Capture well-day service, consumable and tangible actuals against locked AFE budgets and rate revisions.'}
      action={<Box display="flex" gap={1} flexWrap="wrap">
        {!deletedView && can('daily-cost:read') && <Button
          variant="outlined" startIcon={<InsightsOutlined/>}
          component={RouterLink}
          to={filterWell ? `/daily-cost/analysis/${filterWell}` : '/daily-cost/analysis'}
        >Well cost analysis</Button>}
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</Button>
        {deletedView
          ? <Button variant="outlined" startIcon={<EventNoteOutlined/>} onClick={() => { setParams({}); setNotice('') }}>Active register</Button>
          : can('daily-cost:read') && <Button variant="outlined" startIcon={<RestoreRounded/>} onClick={() => { setParams({ view: 'deleted' }); setNotice('') }}>Deleted entries{overview?.deleted_entries ? ` · ${overview.deleted_entries}` : ''}</Button>}
        {!deletedView && can('daily-cost:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate} disabled={!wells.length || !reference?.afes.length}>New daily sheet</Button>}
      </Box>}
    />
    <ErrorMessage message={loadError}/>
    {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}

    {!deletedView && <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2, mb: 1.8 }}>
      <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', lg: '1.3fr 1.3fr .8fr .8fr .8fr auto' } }} alignItems="center">
        <TextField select label="Filter by well" value={filterWell} onChange={event => {
          const next = event.target.value
          setFilterWell(next)
          setFilterAfe('')
        }} helperText="Daily basis for one well">
          <MenuItem value="">All wells</MenuItem>
          {(reference?.wells ?? []).map(well => <MenuItem key={well.id} value={well.id}>{well.well_code} · {well.well_name}</MenuItem>)}
        </TextField>
        <TextField select label="Filter by AFE" value={filterAfe} onChange={event => setFilterAfe(event.target.value)} disabled={!reference?.afes.length}>
          <MenuItem value="">All AFEs</MenuItem>
          {(reference?.afes ?? []).filter(afe => !filterWell || afe.well_id === filterWell)
            .map(afe => <MenuItem key={afe.id} value={afe.id}>{afe.display_name}</MenuItem>)}
        </TextField>
        <TextField select label="Status" value={filterStatus} onChange={event => setFilterStatus(event.target.value as '' | DailyCostStatus)}>
          <MenuItem value="">All</MenuItem>
          <MenuItem value="draft">Draft</MenuItem>
          <MenuItem value="submitted">Submitted</MenuItem>
        </TextField>
        <TextField type="date" label="Cost date from" value={dateFrom} onChange={event => setDateFrom(event.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField type="date" label="to" value={dateTo} onChange={event => setDateTo(event.target.value)} InputLabelProps={{ shrink: true }}/>
        <Button variant="outlined" startIcon={<FilterAltOffOutlined/>} onClick={() => {
          setFilterWell(''); setFilterAfe(''); setFilterStatus(''); setDateFrom(''); setDateTo('')
        }} disabled={!filtersActive}>Clear</Button>
      </Box>
      {filtersActive && <Alert severity="info" sx={{ mt: 1.3, py: .4 }}>
        Showing {rows.length} daily sheet{rows.length === 1 ? '' : 's'} for the selected filters.
        {dateFrom && dateTo && dateFrom > dateTo ? ' The start date is after the end date, so no sheet can match.' : ''}
      </Alert>}
    </Paper>}

    {!deletedView && overview && <>
      {overview.over_budget_afes > 0 && <Alert severity="warning" icon={<WarningAmberRounded/>} sx={{ mb: 2 }}>
        {overview.over_budget_afes} AFE{overview.over_budget_afes === 1 ? ' has' : 's have'} actual-to-date costs above the locked budget. Review remaining balances in the daily sheets.
      </Alert>}
      <Box display="grid" gap={1.4} mb={2} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' } }}>
        <StatCard label="Active daily sheets" value={overview.active_entries} hint={`${overview.draft_entries} Draft · ${overview.submitted_entries} Submitted`} icon={<EventNoteOutlined fontSize="small"/>}/>
        <StatCard label="AFE budgets tracked" value={overview.active_baselines} hint={`${overview.wells_tracked} wells with daily activity`} icon={<Inventory2Outlined fontSize="small"/>}/>
        <StatCard label="AFE planned" value={prettyCurrencyMap(overview.total_planned_by_currency)} hint="Frozen estimate totals, once per AFE" icon={<TaskAltOutlined fontSize="small"/>}/>
        <StatCard label="Actual to date" value={prettyCurrencyMap(overview.actual_to_date_by_currency)} hint="Active sheets across tracked AFEs" icon={<FactCheckOutlined fontSize="small"/>} tone={overview.over_budget_afes ? 'warning' : 'default'}/>
      </Box>
      <Box display="grid" gap={1.7} mb={2} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.15fr) minmax(360px, .85fr)' } }}>
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, minWidth: 0 }}>
          <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" mb={1.2}>
            <Box><Typography fontWeight={800} fontSize={15}>Actual spend · last 30 days</Typography><Typography color="text.secondary" fontSize={11.5} mt={.25}>Daily actuals with UPA and NPT separated for visibility.</Typography></Box>
            {currencies.length > 1 && <TextField select size="small" label="Currency" value={chartCurrency} onChange={event => setChartCurrency(event.target.value)} sx={{ minWidth: 115 }}>{currencies.map(code => <MenuItem key={code} value={code}>{code}</MenuItem>)}</TextField>}
          </Box>
          {chartRows.length
            ? <Box height={230}><ReactECharts option={chartOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={7} textAlign="center">Daily trend will appear when sheets are recorded in the last 30 days.</Typography>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, minWidth: 0 }}>
          <Typography fontWeight={800} fontSize={15}>Budget by cost group</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25} mb={1}>Group totals are kept in each AFE's standard currency; balances include all active sheets.</Typography>
          <Box sx={{ overflowX: 'auto' }}>
            <Box component="table" sx={{ borderCollapse: 'collapse', width: '100%', minWidth: 440, '& th': { textAlign: 'left', color: 'text.secondary', fontSize: 10, letterSpacing: .6, fontWeight: 800, py: 1, borderBottom: '1px solid', borderColor: 'divider' }, '& td': { py: 1.15, borderBottom: '1px solid', borderColor: 'divider', fontSize: 12 } }}>
              <thead><tr><th>CURRENCY / GROUP</th><th>AFE PLANNED</th><th>ACTUAL</th><th>REMAINING</th></tr></thead>
              <tbody>{overview.groups.map((group, index) => <tr key={`${group.currency}-${group.cost_group}-${index}`}>
                <td><Typography fontSize={12} fontWeight={700}>{group.cost_group}</Typography><Typography fontSize={10.5} color="text.secondary">{group.currency}</Typography></td>
                <td>{dailyMoney(group.planned, group.currency)}</td><td>{dailyMoney(group.actual, group.currency)}</td>
                <td><Typography color={Number(group.balance) < 0 ? 'error.main' : 'success.main'} fontSize={12} fontWeight={700}>{dailyMoney(group.balance, group.currency)}</Typography></td>
              </tr>)}</tbody>
            </Box>
          </Box>
          <Box display="flex" justifyContent="space-between" gap={1} mt={1.2}>
            <Typography fontSize={11} color="text.secondary">Remaining AFE balance</Typography>
            <Typography fontSize={11} fontWeight={800}>{prettyCurrencyMap(overview.remaining_by_currency)}</Typography>
          </Box>
        </Paper>
      </Box>
      {overview.recent_activity.length > 0 && <Paper variant="outlined" sx={{ px: 2, py: 1.4, borderRadius: 2, mb: 2 }}>
        <Typography fontWeight={800} fontSize={13} mb={.4}>Recent activity</Typography>
        <Box display="grid" gap={.65} sx={{ gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)' } }}>
          {overview.recent_activity.slice(0, 4).map(item => <Typography key={item.id} fontSize={11.5} color="text.secondary" noWrap title={item.summary}>{new Date(item.created_at).toLocaleString()} · {item.summary || `${item.action} ${item.entity_label}`}</Typography>)}
        </Box>
      </Paper>}
    </>}

    {loading && !rows.length ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <>
      {selected.length > 0 && <Paper variant="outlined" sx={{ p: 1.4, borderRadius: 2, mb: 1.5, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography fontSize={12} fontWeight={700} mr="auto">{selected.length} sheet{selected.length === 1 ? '' : 's'} selected</Typography>
        {deletedView ? <>
          {can('daily-cost:restore') && <Button size="small" startIcon={<RestoreRounded/>} onClick={() => { setActionError(''); setPending({ kind: 'restore', rows: selected }) }}>Restore selected</Button>}
          {can('daily-cost:permanent-delete') && <Button size="small" color="error" startIcon={<DeleteForeverOutlined/>} onClick={() => { setActionError(''); setPending({ kind: 'purge', rows: selected }) }}>Delete permanently</Button>}
        </> : can('daily-cost:delete') && <>
          {selected.some(row => row.status !== 'draft') && <Typography fontSize={11} color="warning.dark">Submitted sheets must be reopened before deleting.</Typography>}
          <Button size="small" color="error" startIcon={<DeleteOutlineRounded/>} disabled={selected.some(row => row.status !== 'draft')} onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: selected }) }}>Move to Deleted Entries</Button>
        </>}
      </Paper>}
      <DataTable
        rows={rows}
        columns={columns}
        rowKey="id"
        searchPlaceholder={deletedView ? 'Search deleted sheets by date, well, AFE or code…' : 'Search sheets by date, well, AFE, amount or status…'}
        exportName={deletedView ? 'daily-cost-deleted' : 'daily-cost-register'}
        canExport={can('daily-cost:export')}
        onExport={can('daily-cost:export') ? exportAudit : undefined}
        selectable={deletedView ? can('daily-cost:restore') || can('daily-cost:permanent-delete') : can('daily-cost:delete')}
        onSelectionChange={setSelected}
      />
      {!loading && rows.length === 0 && <Typography color="text.secondary" fontSize={12} mt={1.2}>
        {deletedView ? 'There are no deleted daily sheets.' : 'No daily sheets yet. Start from a saved AFE estimate on a configured well.'}
      </Typography>}
    </>}

    <FormDialog open={createOpen} title="Start a daily cost sheet" subtitle="The first sheet locks the AFE estimate, FX factors, well plan, service rates and Master Data catalogue prices for this well/AFE." onClose={() => setCreateOpen(false)} onSubmit={() => void createEntry()} busy={creating} submitLabel="Create daily sheet" submitDisabled={!selectedAfe || !selectedWell || !createDateValid || Boolean(selectedDuplicate) || missingSubActivities}>
      <Box display="grid" gap={1.6}>
        {!wells.length && <Alert severity="warning">Create and sign off a well plan in Rig &amp; Well Management before starting daily cost tracking.</Alert>}
        <TextField select required label="Configured well" value={wellId} onChange={event => {
          const next = event.target.value
          setWellId(next)
          setAfeId(reference?.afes.find(item => item.well_id === next)?.id ?? '')
        }} disabled={!wells.length}>
          {wells.map(well => {
            const rig = reference?.rigs.find(item => item.id === well.rig_id)
            return <MenuItem key={well.id} value={well.id}>{well.well_code} · {well.well_name} — {rig?.rig_code ?? 'Rig'}</MenuItem>
          })}
        </TextField>
        {missingSubActivities && <Alert severity="warning" sx={{ py: 0 }} action={<Button component={RouterLink} to="/rig-well/sub-activities" size="small" color="inherit" onClick={() => setCreateOpen(false)}>Open well sub activities</Button>}>
          Configuring the well sub activity in Rig &amp; Well Management is mandatory for daily cost entry. Add the well's sub activities first — every cost line is recorded under an Activity and Sub activity.
        </Alert>}
        <TextField select required label="Saved AFE estimate" value={afeId} onChange={event => setAfeId(event.target.value)} disabled={!afes.length}>
          {afes.map(afe => <MenuItem key={afe.id} value={afe.id}>{afe.display_name}</MenuItem>)}
        </TextField>
        {selectedAfe && <Alert severity="info" sx={{ py: 0 }}>AFE status: {selectedAfe.status}. Budget baseline: {dailyMoney(selectedAfe.total_cost, selectedAfe.standard_currency)}. Subsequent estimate or Master Data changes will not rewrite this locked baseline.</Alert>}
        {selectedDuplicate && <Alert severity="warning" sx={{ py: 0 }} action={<Button component={RouterLink} to={`/daily-cost/entries/${selectedDuplicate.id}`} size="small" color="inherit" onClick={() => setCreateOpen(false)}>Open existing</Button>}>
          A sheet already exists for this well, AFE and date. Open it to review or continue editing instead of creating a duplicate.
        </Alert>}
        <TextField required type="date" label="Cost date" value={costDate} onChange={event => { setCostDate(event.target.value); setCreateError('') }} error={Boolean(costDate) && !createDateValid} helperText={Boolean(costDate) && !createDateValid ? 'Enter a real calendar date.' : 'Each well + AFE + date can have one sheet.'} InputLabelProps={{ shrink: true }}/>
        <TextField label="Shift / day remarks" value={remarks} onChange={event => setRemarks(event.target.value)} multiline minRows={2} inputProps={{ maxLength: 1000 }}/>
        <ErrorMessage message={createError}/>
      </Box>
    </FormDialog>

    <FormDialog open={Boolean(pending)} title={actionTitle ?? 'Confirm action'} subtitle={actionSubtitle} onClose={() => { if (!actionBusy) setPending(null) }} onSubmit={() => void act()} busy={actionBusy} submitLabel={pending?.kind === 'purge' ? 'Delete permanently' : pending?.kind === 'restore' ? 'Restore' : 'Move to Deleted Entries'}>
      <Box display="grid" gap={1.2}>
        {pending?.kind === 'purge' && <Alert severity="warning">Permanent deletion cannot be undone. The AFE budget and well rate snapshots are retained for audit.</Alert>}
        <ErrorMessage message={actionError}/>
      </Box>
    </FormDialog>
  </>
}

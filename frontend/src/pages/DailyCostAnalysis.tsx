import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import {
  AccountBalanceWalletOutlined, AnalyticsOutlined, CalendarMonthOutlined, DownloadOutlined,
  PrintOutlined, RefreshRounded, ReportProblemOutlined, SavingsOutlined, TimelineOutlined, TrendingUpRounded,
  WarningAmberRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, FormControlLabel, MenuItem, Paper, Switch, Tab, Tabs,
  TextField, Typography, useTheme,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, PageHeading, Tag, useUnsavedChangesGuard } from '../components/Common'
import { WellCostPrintDialog } from '../components/daily-cost/WellCostPrintDialog'
import { WellProgressPanel } from '../components/daily-cost/WellProgressPanel'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import {
  dailyMoney, displayDate, DAILY_COST_STATUSES, type DailyCostDailyRow, type DailyCostFactorGroup,
  type DailyCostFactorRow, type DailyCostWellOption, type DailyCostWellSummary, type WellProgressScope,
} from '../lib/dailyCost'
import { formatDepthMeters } from '../lib/units'

function StatCard({ label, value, hint, icon, tone = 'default' }: {
  label: string; value: string; hint: string; icon: ReactNode; tone?: 'default' | 'warning' | 'good'
}) {
  const toneColor = tone === 'warning' ? 'warning.main' : tone === 'good' ? 'success.main' : 'text.primary'
  return <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, minWidth: 0 }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={10.5} fontWeight={800} letterSpacing={.75} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon">{icon}</Box>
    </Box>
    <Typography sx={{ fontSize: 22, my: .8, color: toneColor, fontWeight: 800, overflowWrap: 'anywhere' }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11.2}>{hint}</Typography>
  </Paper>
}

const FACTOR_TABS: { dimension: DailyCostFactorGroup['dimension']; label: string }[] = [
  { dimension: 'cost_group', label: 'Cost group' },
  { dimension: 'classification', label: 'Planned / UPA / NPT' },
  { dimension: 'section', label: 'Hole section' },
  { dimension: 'phase', label: 'Phase' },
  { dimension: 'activity', label: 'Activity' },
  { dimension: 'sub_activity', label: 'Sub activity' },
  { dimension: 'party', label: 'Responsible party' },
  { dimension: 'item', label: 'Service & items' },
  { dimension: 'rate_source', label: 'Rate source' },
  { dimension: 'currency', label: 'Currency' },
]

function factorColumns(group: DailyCostFactorGroup, currency: string): ColDef<DailyCostFactorRow>[] {
  const columns: ColDef<DailyCostFactorRow>[] = [
    { headerName: 'CODE', field: 'code', minWidth: 130, width: 150 },
    { headerName: group.dimension === 'party' ? 'PARTY' : 'NAME', field: 'name', minWidth: 190, flex: 1.1 },
    { headerName: 'DETAIL', field: 'detail', minWidth: 150, flex: 1 },
  ]
  if (group.dimension === 'cost_group' || group.dimension === 'section') {
    columns.push({ headerName: 'AFE PLANNED', field: 'planned', minWidth: 150, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) })
    columns.push({
      headerName: 'BALANCE', field: 'balance', minWidth: 150,
      cellRenderer: (params: ICellRendererParams<DailyCostFactorRow>) => {
        const value = Number(params.data?.balance ?? 0)
        return <Typography fontSize={12} fontWeight={700} color={value < 0 ? 'error.main' : 'success.main'}>{dailyMoney(value, currency)}</Typography>
      },
    })
  }
  columns.push({ headerName: 'ACTUAL', field: 'amount', minWidth: 150, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) })
  columns.push({
    headerName: 'SHARE', field: 'share', minWidth: 120,
    valueFormatter: params => `${Number(params.value ?? 0).toFixed(1)}%`,
  })
  if (group.dimension !== 'currency') {
    columns.push({ headerName: 'QUANTITY', field: 'quantity', minWidth: 120, valueFormatter: params => Number(params.value ?? 0).toLocaleString() })
  }
  return columns
}

export default function DailyCostAnalysis() {
  const { wellId = '' } = useParams()
  const { can } = useAuth()
  const navigate = useNavigate()
  const theme = useTheme()
  const [wells, setWells] = useState<DailyCostWellOption[]>([])
  const [summary, setSummary] = useState<DailyCostWellSummary | null>(null)
  // Register milestones (spud / progress completion) with their day counts.
  const [progress, setProgress] = useState<WellProgressScope[]>([])
  const [progressDirty, setProgressDirty] = useState(false)
  const progressSaveRef = useRef<(() => Promise<boolean>) | null>(null)
  const [selectedWell, setSelectedWell] = useState(wellId)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [includeDraft, setIncludeDraft] = useState(true)
  const [printOpen, setPrintOpen] = useState(false)
  const [tab, setTab] = useState(0)
  const requestVersion = useRef(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  useEffect(() => { setSelectedWell(wellId) }, [wellId])

  const loadWells = useCallback(async () => {
    try {
      setWells(await api<DailyCostWellOption[]>('/daily-cost/wells'))
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : 'Tracked wells could not be loaded')
    }
  }, [])

  const load = useCallback(async () => {
    const version = ++requestVersion.current
    setLoadError('')
    setSummary(null)
    if (!selectedWell) { setProgress([]); setLoading(false); return }
    if (dateFrom && dateTo && dateFrom > dateTo) { setLoading(false); return }
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (dateFrom) params.set('from', dateFrom)
      if (dateTo) params.set('to', dateTo)
      params.set('include_draft', String(includeDraft))
      const result = await api<DailyCostWellSummary>(`/daily-cost/wells/${selectedWell}/cost-summary?${params.toString()}`)
      if (version === requestVersion.current) {
        setSummary(result)
        setProgress(result.progress)
      }
    } catch (caught) {
      if (version !== requestVersion.current) return
      setLoadError(caught instanceof Error ? caught.message : 'The well cost analysis could not be loaded')
      setSummary(null)
    } finally {
      if (version === requestVersion.current) setLoading(false)
    }
  }, [selectedWell, dateFrom, dateTo, includeDraft])

  useEffect(() => { void loadWells() }, [loadWells])
  useEffect(() => { void load() }, [load])

  const currency = summary?.totals.currency ?? ''
  const factorGroups = summary?.factors ?? []
  const activeGroup = factorGroups[Math.min(tab, Math.max(0, factorGroups.length - 1))]

  const progressOption: EChartsOption = useMemo(() => {
    if (!summary) return {}
    const days = summary.daily.map(row => row.cost_date.slice(5))
    const plannedLine = summary.daily.map((_row, index) => Number(summary.totals.planned) * ((index + 1) / Math.max(1, summary.daily.length)))
    const adjustedLine = summary.totals.adjusted_planned != null
      ? summary.daily.map((_row, index) => Number(summary.totals.adjusted_planned) * ((index + 1) / Math.max(1, summary.daily.length)))
      : null
    return {
      animation: false,
      grid: { left: 14, right: 18, top: 26, bottom: 32, containLabel: true },
      legend: { top: 0, textStyle: { color: theme.palette.text.secondary }, itemWidth: 12, itemHeight: 8 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: value => dailyMoney(Number(value), currency),
      },
      xAxis: { type: 'category', data: days, axisLabel: { color: theme.palette.text.secondary }, axisLine: { lineStyle: { color: theme.palette.divider } } },
      yAxis: { type: 'value', axisLabel: { color: theme.palette.text.secondary }, splitLine: { lineStyle: { color: theme.palette.divider } } },
      series: [
        {
          name: 'Cumulative actual', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
          itemStyle: { color: theme.palette.primary.main }, lineStyle: { width: 2.5 },
          areaStyle: { color: `${theme.palette.primary.main}20` },
          data: summary.daily.map(row => Number(row.cumulative)),
        },
        {
          name: 'Daily actual', type: 'bar', barMaxWidth: 16,
          itemStyle: { color: `${theme.palette.primary.main}55` }, data: summary.daily.map(row => Number(row.total)),
        },
        {
          name: 'AFE straight-line plan', type: 'line', symbol: 'none',
          lineStyle: { width: 1.6, type: 'dashed', color: theme.palette.warning.main },
          itemStyle: { color: theme.palette.warning.main }, data: plannedLine,
        },
        ...(adjustedLine ? [{
          name: 'Adjusted straight-line plan', type: 'line' as const, symbol: 'none',
          lineStyle: { width: 1.6, type: 'dashed' as const, color: theme.palette.success.main },
          itemStyle: { color: theme.palette.success.main }, data: adjustedLine,
        }] : []),
      ],
    }
  }, [summary, currency, theme])

  const groupOption: EChartsOption = useMemo(() => {
    if (!summary) return {}
    return {
      animation: false,
      grid: { left: 14, right: 18, top: 26, bottom: 32, containLabel: true },
      legend: { top: 0, textStyle: { color: theme.palette.text.secondary }, itemWidth: 12, itemHeight: 8 },
      tooltip: { trigger: 'axis', valueFormatter: value => dailyMoney(Number(value), currency) },
      xAxis: { type: 'category', data: summary.daily.map(row => row.cost_date.slice(5)), axisLabel: { color: theme.palette.text.secondary }, axisLine: { lineStyle: { color: theme.palette.divider } } },
      yAxis: { type: 'value', axisLabel: { color: theme.palette.text.secondary }, splitLine: { lineStyle: { color: theme.palette.divider } } },
      series: [
        { name: 'Services', type: 'bar', stack: 'day', itemStyle: { color: theme.palette.primary.main }, data: summary.daily.map(row => Number(row.services)) },
        { name: 'Consumables', type: 'bar', stack: 'day', itemStyle: { color: theme.palette.secondary.main }, data: summary.daily.map(row => Number(row.consumables)) },
        { name: 'Tangibles', type: 'bar', stack: 'day', itemStyle: { color: theme.palette.info.main }, data: summary.daily.map(row => Number(row.tangibles)) },
        { name: 'Other expenses', type: 'bar', stack: 'day', itemStyle: { color: theme.palette.warning.main }, data: summary.daily.map(row => Number(row.other_expenses)) },
        { name: 'NPT', type: 'line', symbolSize: 5, itemStyle: { color: theme.palette.error.main }, data: summary.daily.map(row => Number(row.npt)) },
      ],
    }
  }, [summary, currency, theme])

  const recordExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/daily-cost/export-audit', {
      method: 'POST',
      body: body({ module: 'budget-comparison', format, record_count: recordCount, include_deleted: false }),
    })
  }

  const hasAdjustment = summary?.totals.has_adjustment ?? false

  const dailyColumns: ColDef<DailyCostDailyRow>[] = [
    { headerName: 'DATE', field: 'cost_date', minWidth: 140, width: 150, valueFormatter: params => displayDate(String(params.value ?? '')) },
    { headerName: 'ACTUAL DEPTH (m)', field: 'actual_depth', minWidth: 145, valueFormatter: params => formatDepthMeters(params.data?.actual_depth, 'm') },
    { headerName: 'SERVICES', field: 'services', minWidth: 140, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) },
    { headerName: 'CONSUMABLES', field: 'consumables', minWidth: 140, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) },
    { headerName: 'TANGIBLES', field: 'tangibles', minWidth: 135, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) },
    {
      headerName: 'OTHER EXPENSES', field: 'other_expenses', minWidth: 155,
      valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency),
      cellRenderer: (params: ICellRendererParams<DailyCostDailyRow>) => Number(params.data?.other_expenses ?? 0) > 0
        ? <Typography fontSize={12} fontWeight={700} color="warning.main">{dailyMoney(String(params.value ?? '0'), currency)}</Typography>
        : <Typography fontSize={12} color="text.secondary">—</Typography>,
    },
    { headerName: 'DAY TOTAL', field: 'total', minWidth: 145, cellRenderer: (params: ICellRendererParams<DailyCostDailyRow>) => <Typography fontSize={12} fontWeight={800}>{dailyMoney(String(params.value ?? '0'), currency)}</Typography> },
    ...(currency.toUpperCase() !== 'USD' ? [{
      headerName: 'DAY USD (STD)', field: 'total_usd' as const, minWidth: 145,
      valueFormatter: (params: { value?: unknown }) => dailyMoney(String(params.value ?? '0'), 'USD'),
    } satisfies ColDef<DailyCostDailyRow>] : []),
    { headerName: 'UPA', field: 'upa', minWidth: 125, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) },
    { headerName: 'NPT', field: 'npt', minWidth: 125, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) },
    { headerName: 'CUMULATIVE', field: 'cumulative', minWidth: 150, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) },
    {
      headerName: 'AFE BALANCE', field: 'budget_balance', minWidth: 150,
      cellRenderer: (params: ICellRendererParams<DailyCostDailyRow>) => {
        const value = Number(params.data?.budget_balance ?? 0)
        return <Typography fontSize={12} fontWeight={700} color={value < 0 ? 'error.main' : 'success.main'}>{dailyMoney(value, currency)}</Typography>
      },
    },
    ...(hasAdjustment ? [{
      headerName: 'ADJ AFE BALANCE', field: 'adjusted_budget_balance' as const, minWidth: 160,
      headerTooltip: 'Adjusted AFE amount less cumulative actual to date',
      cellRenderer: (params: ICellRendererParams<DailyCostDailyRow>) => {
        const raw = params.data?.adjusted_budget_balance
        if (raw == null) return <Typography fontSize={12} color="text.secondary">—</Typography>
        const value = Number(raw)
        return <Typography fontSize={12} fontWeight={700} color={value < 0 ? 'error.main' : 'success.main'}>{dailyMoney(value, currency)}</Typography>
      },
    } satisfies ColDef<DailyCostDailyRow>] : []),
    {
      headerName: 'SHEETS', field: 'sheets', minWidth: 110,
      cellRenderer: (params: ICellRendererParams<DailyCostDailyRow>) => {
        const row = params.data
        if (!row) return null
        return <Box display="flex" gap={.4}><Tag tone={row.status === 'submitted' ? 'success' : row.status === 'draft' ? 'info' : 'warning'}>{DAILY_COST_STATUSES[row.status === 'mixed' ? 'draft' : row.status]}</Tag><Typography fontSize={11.5} color="text.secondary">{row.sheets}</Typography></Box>
      },
    },
  ]

  const canExport = can('daily-cost:export')

  // Unsaved-changes protection (convention 15) for the progress date entries.
  const leaveGuard = useUnsavedChangesGuard({
    when: progressDirty,
    onSave: () => (progressSaveRef.current?.() ?? Promise.resolve(true)),
    title: 'Leave with unsaved progress dates?',
    message: 'The Well Spud Date & Time or Progress Completed Date & Time entries are not saved yet. Save them before leaving, or discard them deliberately.',
  })

  return <>
    <PageHeading
      eyebrow="DAILY COST MANAGEMENT / WELL COST ANALYSIS"
      title="Well cost analysis"
      subtitle="Every AFE and daily sheet for one well, costed day by day and cut by activity, section, party, rate source and currency."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        {canExport && <Button variant="outlined" startIcon={<PrintOutlined/>} disabled={!selectedWell} onClick={() => setPrintOpen(true)}>Print well costing sheet</Button>}
        <Button component={RouterLink} to="/daily-cost" variant="outlined" startIcon={<CalendarMonthOutlined/>}>Daily register</Button>
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={loading || !selectedWell}>{loading ? 'Refreshing…' : 'Refresh'}</Button>
      </Box>}
    />
    <WellCostPrintDialog open={printOpen} onClose={() => setPrintOpen(false)} wells={wells} initialWellId={selectedWell}/>
    <ErrorMessage message={loadError}/>

    <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, mb: 1.8 }}>
      <Box display="grid" gap={1.4} sx={{ gridTemplateColumns: { xs: '1fr', md: '1.4fr 1fr 1fr auto' } }} alignItems="center">
        <TextField select label="Well" value={selectedWell} onChange={event => {
          setSelectedWell(event.target.value)
          navigate(event.target.value ? `/daily-cost/analysis/${event.target.value}` : '/daily-cost/analysis')
        }} helperText={summary ? `${summary.well.rig_code} · ${summary.well.rig_name}` : 'Only wells with daily costs are listed'}>
          <MenuItem value="">Select one well</MenuItem>
          {wells.map(well => <MenuItem key={well.id} value={well.id}>{well.well_code} · {well.well_name}</MenuItem>)}
        </TextField>
        <TextField type="date" label="Cost date from" value={dateFrom} onChange={event => setDateFrom(event.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField type="date" label="to" value={dateTo} onChange={event => setDateTo(event.target.value)} InputLabelProps={{ shrink: true }}/>
        <Box display="flex" alignItems="center" gap={1}>
          <FormControlLabel control={<Switch checked={includeDraft} onChange={event => setIncludeDraft(event.target.checked)}/>} label={<Typography fontSize={12}>Include drafts</Typography>}/>
          {(dateFrom || dateTo) && <Button size="small" onClick={() => { setDateFrom(''); setDateTo('') }}>Clear dates</Button>}
        </Box>
      </Box>
      {dateFrom && dateTo && dateFrom > dateTo && <Alert severity="error" sx={{ mt: 1.3 }}>The start date is after the end date. Swap them to analyse this period.</Alert>}
    </Paper>

    {progress.length > 0 && selectedWell && <WellProgressPanel
      wellId={selectedWell} scopes={progress} canEdit={can('daily-cost:update')}
      asOfLabel="today"
      onSaved={report => setProgress(report.scopes)}
      onDirtyChange={setProgressDirty} saveRef={progressSaveRef}
    />}

    {loading && !summary && <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>}

    {!loading && !summary && !loadError && <Paper variant="outlined" sx={{ p: 3, borderRadius: 2, textAlign: 'center' }}>
      <Typography fontWeight={800} fontSize={15}>{wells.length ? 'Select a well to view its costs' : 'No daily costs are tracked yet'}</Typography>
      <Typography color="text.secondary" fontSize={12.5} mt={.6} mb={1.8}>
        {wells.length ? 'Choose one well above. Costs and AFE budgets are never combined across wells.' : 'Start a daily cost sheet from the Daily Cost register for a configured well and a saved AFE estimate.'}
      </Typography>
      <Button component={RouterLink} to="/daily-cost" variant="contained" startIcon={<CalendarMonthOutlined/>}>Open the daily register</Button>
    </Paper>}

    {summary && <>
      {summary.warnings.map(warning => <Alert key={warning.code} severity={warning.severity} icon={warning.severity === 'info' ? undefined : <WarningAmberRounded/>} sx={{ mb: 1.4 }}>{warning.message}</Alert>)}

      <Box display="grid" gap={1.3} mb={1.8} sx={{ gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(4, 1fr)', lg: hasAdjustment ? 'repeat(8, 1fr)' : 'repeat(7, 1fr)' } }}>
        <StatCard label="AFE planned" value={dailyMoney(summary.totals.planned, currency)} hint={`${summary.afes.length} AFE locked on this well`} icon={<AccountBalanceWalletOutlined fontSize="small"/>}/>
        {hasAdjustment && summary.totals.adjusted_planned != null && <StatCard label="Adjusted AFE" value={dailyMoney(summary.totals.adjusted_planned, currency)} hint={`${summary.totals.adjusted_used_percent ?? '—'}% of the adjusted AFE spent`} icon={<AccountBalanceWalletOutlined fontSize="small"/>}/>}
        <StatCard label="Actual to date" value={dailyMoney(summary.totals.actual, currency)} hint={`${summary.totals.used_percent}% of the locked AFE`} icon={<TrendingUpRounded fontSize="small"/>}/>
        <StatCard label="Other expenses" value={dailyMoney(summary.totals.other_expenses, currency)} hint="LIH and similar charges deducted from the AFE" tone={Number(summary.totals.other_expenses) > 0 ? 'warning' : 'default'} icon={<ReportProblemOutlined fontSize="small"/>}/>
        <StatCard label="Remaining balance" value={dailyMoney(summary.totals.balance, currency)} hint={Number(summary.totals.balance) < 0 ? 'Over the AFE budget' : 'Planned less actual to date'} tone={Number(summary.totals.balance) < 0 ? 'warning' : 'good'} icon={<SavingsOutlined fontSize="small"/>}/>
        <StatCard label="Average per day" value={dailyMoney(summary.totals.average_per_day, currency)} hint={`${summary.totals.recorded_days} recorded of ${summary.totals.elapsed_days} elapsed days`} icon={<TimelineOutlined fontSize="small"/>}/>
        <StatCard label="UPA to date" value={dailyMoney(summary.totals.upa, currency)} hint="Unplanned activity charges" tone={Number(summary.totals.upa) > 0 ? 'warning' : 'default'} icon={<AnalyticsOutlined fontSize="small"/>}/>
        <StatCard label="NPT to date" value={dailyMoney(summary.totals.npt, currency)} hint="Non-productive time charges" tone={Number(summary.totals.npt) > 0 ? 'warning' : 'default'} icon={<AnalyticsOutlined fontSize="small"/>}/>
      </Box>

      <Box display="grid" gap={1.6} mb={1.8} sx={{ gridTemplateColumns: { xs: '1fr', lg: '1.15fr .85fr' } }}>
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, minWidth: 0 }}>
          <Typography fontWeight={800} fontSize={15}>Daily actuals against the AFE</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25}>
            Running total from the first recorded day, with the straight-line AFE plan for the same period.
          </Typography>
          {summary.daily.length
            ? <Box height={250} mt={1}><ReactECharts option={progressOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={6} textAlign="center">No daily sheets match this filter.</Typography>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, minWidth: 0 }}>
          <Typography fontWeight={800} fontSize={15}>Cost group by day</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25}>Services, consumables, tangibles and other expenses stacked per well-day, with NPT overlaid.</Typography>
          {summary.daily.length
            ? <Box height={250} mt={1}><ReactECharts option={groupOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={6} textAlign="center">No daily sheets match this filter.</Typography>}
        </Paper>
      </Box>

      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, mb: 1.8 }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" mb={1}>
          <Typography fontWeight={800} fontSize={15}>AFE position on this well</Typography>
          <Typography color="text.secondary" fontSize={11.5}>
            Planned days {Number(summary.totals.planned_days).toLocaleString()}
            {summary.totals.adjusted_planned_days != null && <> · Adjusted {Number(summary.totals.adjusted_planned_days).toLocaleString()}</>}
            {' '}· Actual {summary.totals.recorded_days} recorded day{summary.totals.recorded_days === 1 ? '' : 's'}
            {' '}· first day {displayDate(summary.totals.first_day)} · last day {displayDate(summary.totals.last_day)}
            {summary.totals.days_to_budget ? ` · at this burn rate the AFE lasts ${summary.totals.days_to_budget} more days` : ''}
          </Typography>
        </Box>
        <Box sx={{ overflowX: 'auto' }}>
          <Box component="table" sx={{ borderCollapse: 'collapse', width: '100%', minWidth: 720, '& th': { textAlign: 'left', color: 'text.secondary', fontSize: 10, letterSpacing: .6, fontWeight: 800, py: 1, borderBottom: '1px solid', borderColor: 'divider' }, '& td': { py: 1.1, borderBottom: '1px solid', borderColor: 'divider', fontSize: 12 } }}>
            <thead><tr><th>AFE</th><th>STATUS</th><th>SHEETS</th><th align="right">PLANNED</th>{hasAdjustment && <th align="right">ADJUSTED</th>}<th align="right">ACTUAL</th><th align="right">OTHER EXPENSES</th><th align="right">BALANCE</th>{hasAdjustment && <th align="right">ADJ BALANCE</th>}<th align="right">DAYS</th></tr></thead>
            <tbody>{summary.afes.map(afe => <tr key={afe.afe_id}>
              <td><Typography fontSize={12} fontWeight={700}>{afe.afe_code}</Typography><Typography fontSize={10.5} color="text.secondary">{afe.afe_name}</Typography></td>
              <td><Tag tone={afe.over_budget ? 'warning' : 'info'}>{afe.afe_status}</Tag></td>
              <td>{afe.sheets} · {displayDate(afe.first_day)} → {displayDate(afe.last_day)}</td>
              <td align="right">{dailyMoney(afe.planned_total, afe.currency)}</td>
              {hasAdjustment && <td align="right">{afe.adjusted_planned_total != null ? dailyMoney(afe.adjusted_planned_total, afe.currency) : <Typography fontSize={12} color="text.secondary">—</Typography>}</td>}
              <td align="right">{dailyMoney(afe.actual, afe.currency)}</td>
              <td align="right">{Number(afe.other_expenses) > 0 ? <Typography fontSize={12} fontWeight={700} color="warning.main">− {dailyMoney(afe.other_expenses, afe.currency)}</Typography> : <Typography fontSize={12} color="text.secondary">—</Typography>}</td>
              <td align="right"><Typography fontSize={12} fontWeight={700} color={Number(afe.balance) < 0 ? 'error.main' : 'success.main'}>{dailyMoney(afe.balance, afe.currency)}</Typography></td>
              {hasAdjustment && <td align="right">{afe.adjusted_balance != null ? <Typography fontSize={12} fontWeight={700} color={Number(afe.adjusted_balance) < 0 ? 'error.main' : 'success.main'}>{dailyMoney(afe.adjusted_balance, afe.currency)}</Typography> : <Typography fontSize={12} color="text.secondary">—</Typography>}</td>}
              <td align="right">{afe.days_recorded}</td>
            </tr>)}</tbody>
          </Box>
        </Box>
      </Paper>

      <Box mb={1.8}>
        <DataTable
          rows={summary.daily}
          columns={dailyColumns}
          rowKey="cost_date"
          searchPlaceholder="Search a well-day by date, total, UPA or NPT…"
          exportName={`well-cost-daily-${summary.well.well_code}`}
          canExport={canExport}
          onExport={canExport ? recordExport : undefined}
        />
      </Box>

      <Paper variant="outlined" sx={{ borderRadius: 2, mb: 1.8, overflow: 'hidden' }}>
        <Box sx={{ px: 2, pt: 1.6, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Typography fontWeight={800} fontSize={15}>Cost factors</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25} mb={.8}>
            The same ledger cut by each factor captured on the daily sheets.
          </Typography>
          <Tabs value={Math.min(tab, Math.max(0, FACTOR_TABS.length - 1))} onChange={(_event, value) => setTab(value)} variant="scrollable" scrollButtons allowScrollButtonsMobile>
            {FACTOR_TABS.map(item => <Tab key={item.dimension} label={item.label}/>)}
          </Tabs>
        </Box>
        <Box p={1.4}>
          {activeGroup ? <>
            <Typography color="text.secondary" fontSize={11.5} mb={1}>
              {activeGroup.label} · {activeGroup.rows.length} {activeGroup.rows.length === 1 ? 'row' : 'rows'} totalling {dailyMoney(activeGroup.total, activeGroup.dimension === 'currency' ? '' : activeGroup.currency)}
            </Typography>
            <DataTable
              rows={activeGroup.rows}
              columns={factorColumns(activeGroup, activeGroup.currency)}
              rowKey="key"
              searchPlaceholder={`Search ${activeGroup.label.toLowerCase()}…`}
              exportName={`well-cost-${activeGroup.dimension}-${summary.well.well_code}`}
              canExport={canExport}
              onExport={canExport ? recordExport : undefined}
            />
          </> : <Typography color="text.secondary" fontSize={12.5} py={2}>No factor data for this filter.</Typography>}
        </Box>
      </Paper>

      <Box>
        <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" mb={1}>
          <Box>
            <Typography fontWeight={800} fontSize={15}>AFE budget reconciliation</Typography>
            <Typography color="text.secondary" fontSize={11.5}>Each locked AFE budget line against the actuals recorded under it.</Typography>
          </Box>
          {canExport && <Button size="small" startIcon={<DownloadOutlined/>} disabled={!summary.budget_lines.length}
            onClick={() => void recordExport('pdf', summary.budget_lines.length)}>Export reconciliation</Button>}
        </Box>
        <DataTable
          rows={summary.budget_lines}
          columns={[
            { headerName: 'BUDGET LINE', field: 'item_code', minWidth: 160, valueGetter: params => String(params.data?.item_code || params.data?.item_name || 'Unbudgeted actual') },
            { headerName: 'NAME', field: 'item_name', minWidth: 200, flex: 1 },
            { headerName: 'GROUP', field: 'cost_group', minWidth: 130 },
            { headerName: 'PLANNED', field: 'planned', minWidth: 150, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) },
            { headerName: 'ACTUAL', field: 'actual_to_date', minWidth: 150, valueFormatter: params => dailyMoney(String(params.value ?? '0'), currency) },
            {
              headerName: 'BALANCE', field: 'balance', minWidth: 150,
              cellRenderer: (params: ICellRendererParams<DailyCostWellSummary['budget_lines'][number]>) => {
                const value = Number(params.data?.balance ?? 0)
                return <Typography fontSize={12} fontWeight={700} color={value < 0 ? 'error.main' : 'success.main'}>{dailyMoney(value, currency)}</Typography>
              },
            },
          ] as ColDef<DailyCostWellSummary['budget_lines'][number]>[]}
          rowKey="budget_key"
          searchPlaceholder="Search a budget line by code, name or group…"
          exportName={`well-cost-budget-${summary.well.well_code}`}
          canExport={canExport}
          onExport={canExport ? recordExport : undefined}
        />
      </Box>
    </>}
    {/* Intercepts navigation, the back button and tab close while progress dates are unsaved. */}
    {leaveGuard}
  </>
}
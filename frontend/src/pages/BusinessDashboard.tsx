import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import {
  AccountBalanceWalletOutlined, AlignVerticalBottomRounded, ArrowForwardRounded, CalendarMonthOutlined,
  DescriptionOutlined, DownloadDoneRounded, EventBusyOutlined, InsightsOutlined, LayersOutlined,
  PrecisionManufacturingOutlined, RefreshRounded, ReportProblemOutlined, ScheduleOutlined, SpeedOutlined,
  StraightenRounded, TerrainOutlined, TrendingUpRounded, WarningAmberRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, Divider, FormControlLabel, LinearProgress, MenuItem, Paper,
  Switch, Tab, Tabs, TextField, Tooltip, Typography, useTheme,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { DrillThroughPanel } from '../components/business-dashboard/DrillThroughPanel'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import {
  AFE_STATUS_LABELS, EMPTY_FILTERS, compactMoney, count, dashboardQuery, decimal, displayDate,
  displayDateTime, money, percent, presetRange,
  type BusinessDashboard as BusinessDashboardData, type DashboardAfeRow, type DashboardFilters,
  type DashboardRigRow, type DashboardWellRow, type Money,
} from '../lib/businessDashboard'

type Tone = 'default' | 'warning' | 'error' | 'good'

function KpiCard({ label, value, hint, icon, tone = 'default', onClick, title }: {
  label: string
  value: string
  hint: string
  icon: ReactNode
  tone?: Tone
  onClick?: () => void
  title?: string
}) {
  const color = tone === 'error' ? 'error.main' : tone === 'warning' ? 'warning.main' : tone === 'good' ? 'success.main' : 'text.primary'
  return <Paper
    variant="outlined"
    className="stat-card"
    onClick={onClick}
    role={onClick ? 'button' : undefined}
    tabIndex={onClick ? 0 : undefined}
    onKeyDown={onClick ? event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick() } } : undefined}
    title={title}
    sx={{ p: 1.8, borderRadius: 2, minWidth: 0, cursor: onClick ? 'pointer' : 'default' }}
  >
    <Box display="flex" alignItems="flex-start" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={10.5} fontWeight={800} letterSpacing={.75} textTransform="uppercase" lineHeight={1.35}>{label}</Typography>
      <Box className="table-icon" sx={{ width: 26, height: 26, flex: '0 0 auto' }}>{icon}</Box>
    </Box>
    <Typography sx={{ fontSize: 20, my: .8, color, fontWeight: 800, fontFamily: 'Manrope', overflowWrap: 'anywhere' }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11} lineHeight={1.4}>{hint}</Typography>
  </Paper>
}

function BalanceCell({ value, currency }: { value: Money; currency: string }) {
  const negative = value !== null && Number(value) < 0
  return <Typography component="span" fontSize={12} fontWeight={700} color={negative ? 'error.main' : 'text.primary'}>{money(value, currency)}</Typography>
}

function DepthCell({ row }: { row: DashboardWellRow }) {
  const value = row.depth_progress_percent === null ? null : Math.min(100, Math.max(0, Number(row.depth_progress_percent)))
  return <Box minWidth={130} py={.6}>
    <Box display="flex" justifyContent="space-between" gap={1}>
      <Typography fontSize={11.5} fontWeight={700}>{percent(row.depth_progress_percent)}</Typography>
      <Typography fontSize={10.5} color="text.secondary">
        {decimal(row.actual_depth, 0)} / {decimal(row.planned_depth, 0)} m
      </Typography>
    </Box>
    <LinearProgress
      variant="determinate"
      value={value ?? 0}
      aria-label={`Depth progress ${percent(row.depth_progress_percent)}`}
      sx={{
        mt: .5, height: 5, borderRadius: 3, bgcolor: 'divider',
        '& .MuiLinearProgress-bar': { transition: 'none', bgcolor: value !== null && value >= 100 ? 'success.main' : 'primary.main' },
      }}
    />
  </Box>
}

export default function BusinessDashboard() {
  const { can } = useAuth()
  const theme = useTheme()
  const [filters, setFilters] = useState<DashboardFilters>(EMPTY_FILTERS)
  const [data, setData] = useState<BusinessDashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState(0)
  const [drillWell, setDrillWell] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null)
  const requestVersion = useRef(0)
  const [filtersOpen, setFiltersOpen] = useState(false)

  const load = useCallback(async (silent = false) => {
    const version = ++requestVersion.current
    if (!silent) setLoading(true)
    setError('')
    try {
      const query = dashboardQuery(filters)
      const result = await api<BusinessDashboardData>(`/dashboard/business${query ? `?${query}` : ''}`)
      if (version !== requestVersion.current) return
      setData(result)
      setRefreshedAt(new Date())
    } catch (caught) {
      if (version !== requestVersion.current) return
      setError(caught instanceof Error ? caught.message : 'The business dashboard could not be loaded')
    } finally {
      if (version === requestVersion.current) setLoading(false)
    }
  }, [filters])

  useEffect(() => { void load() }, [load])

  // "Real time" here means the page re-reads the ledger on a fixed interval;
  // the switch is off by default so a shared screen is not hammering the API.
  useEffect(() => {
    if (!autoRefresh) return
    const timer = window.setInterval(() => { void load(true) }, 60_000)
    return () => window.clearInterval(timer)
  }, [autoRefresh, load])

  const setFilter = <K extends keyof DashboardFilters>(key: K, value: DashboardFilters[K]) => {
    setFilters(previous => {
      const next = { ...previous, [key]: value }
      // Keep dependent pickers honest: a new rig clears a well from another rig.
      if (key === 'rig' && previous.well) {
        const well = data?.filters.wells.find(item => item.id === previous.well)
        if (well && well.rig_id !== value) next.well = ''
      }
      if (key === 'well' && value) {
        const well = data?.filters.wells.find(item => item.id === value)
        if (well) next.rig = well.rig_id
      }
      return next
    })
  }

  const currency = data?.currency || filters.currency
  const caps = data?.capabilities ?? { plan: false, budget: false, actuals: false }
  const canExport = can('rig-well:export') || can('afe:export') || can('daily-cost:export')

  const wellOptions = useMemo(() => (data?.filters.wells ?? []).filter(well => !filters.rig || well.rig_id === filters.rig), [data, filters.rig])
  const afeOptions = useMemo(() => (data?.filters.afes ?? []).filter(afe =>
    (!filters.rig || afe.rig_id === filters.rig) && (!filters.well || afe.well_id === filters.well)
  ), [data, filters.rig, filters.well])

  // ---- chart data ------------------------------------------------------------
  const chartWells = useMemo(() => [...(data?.wells ?? [])]
    .filter(row => Number(row.effective_afe_amount ?? row.actual_amount ?? 0) > 0)
    .sort((a, b) => Number(b.effective_afe_amount ?? b.actual_amount ?? 0) - Number(a.effective_afe_amount ?? a.actual_amount ?? 0))
    .slice(0, 10), [data])

  const daysWells = useMemo(() => [...(data?.wells ?? [])]
    .sort((a, b) => Number(b.actual_days ?? 0) - Number(a.actual_days ?? 0))
    .slice(0, 10), [data])

  const axis = useMemo(() => ({
    text: theme.palette.text.secondary,
    line: theme.palette.divider,
  }), [theme])

  const costOption: EChartsOption = useMemo(() => {
    const rows = [...chartWells].reverse()
    const series: EChartsOption['series'] = []
    if (caps.budget) {
      series.push({
        name: 'AFE amount', type: 'bar', barMaxWidth: 12,
        itemStyle: { color: `${theme.palette.primary.main}55` },
        data: rows.map(row => Number(row.afe_amount ?? 0)),
      })
      if (rows.some(row => row.has_sow_adjustment)) {
        series.push({
          name: 'SOW adjusted', type: 'bar', barMaxWidth: 12,
          itemStyle: { color: theme.palette.info.main },
          data: rows.map(row => row.sow_adjusted_amount === null ? '-' : Number(row.sow_adjusted_amount)),
        })
      }
    }
    if (caps.actuals) {
      series.push({
        name: 'Actual cost', type: 'bar', barMaxWidth: 12,
        itemStyle: { color: theme.palette.primary.main },
        data: rows.map(row => Number(row.actual_amount ?? 0)),
      })
    }
    return {
      animation: false,
      grid: { left: 8, right: 26, top: 30, bottom: 8, containLabel: true },
      legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        valueFormatter: value => (value === '-' ? '—' : money(String(value ?? 0), currency)),
      },
      xAxis: { type: 'value', axisLabel: { color: axis.text, fontSize: 10.5 }, splitLine: { lineStyle: { color: axis.line } } },
      yAxis: {
        type: 'category',
        data: rows.map(row => row.well_code),
        axisLabel: { color: axis.text, fontSize: 10.5, width: 110, overflow: 'truncate' },
        axisLine: { lineStyle: { color: axis.line } },
      },
      series,
    }
  }, [chartWells, caps, currency, theme, axis])

  const daysOption: EChartsOption = useMemo(() => {
    const rows = [...daysWells].reverse()
    return {
      animation: false,
      grid: { left: 8, right: 30, top: 30, bottom: 8, containLabel: true },
      legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        valueFormatter: value => `${Number(value ?? 0).toLocaleString()} d`,
      },
      xAxis: { type: 'value', axisLabel: { color: axis.text, fontSize: 10.5 }, splitLine: { lineStyle: { color: axis.line } } },
      yAxis: {
        type: 'category',
        data: rows.map(row => row.well_code),
        axisLabel: { color: axis.text, fontSize: 10.5, width: 110, overflow: 'truncate' },
        axisLine: { lineStyle: { color: axis.line } },
      },
      series: caps.actuals ? [
        {
          name: 'Productive days', type: 'bar', stack: 'days', barMaxWidth: 16,
          itemStyle: { color: theme.palette.success.main },
          data: rows.map(row => Math.max((row.actual_days ?? 0) - (row.npt_days ?? 0) - (row.upa_days ?? 0), 0)),
        },
        {
          name: 'UPA days', type: 'bar', stack: 'days', barMaxWidth: 16,
          itemStyle: { color: theme.palette.warning.main },
          data: rows.map(row => row.upa_days ?? 0),
        },
        {
          name: 'NPT days', type: 'bar', stack: 'days', barMaxWidth: 16,
          itemStyle: { color: theme.palette.error.main },
          data: rows.map(row => row.npt_days ?? 0),
        },
        ...(caps.plan ? [{
          name: 'Planned days', type: 'scatter' as const, symbol: 'diamond', symbolSize: 11,
          itemStyle: { color: theme.palette.primary.main },
          data: rows.map(row => Number(row.planned_days ?? 0)),
        }] : []),
      ] : [],
    }
  }, [daysWells, caps, theme, axis])

  const trendOption: EChartsOption = useMemo(() => {
    const rows = data?.daily ?? []
    return {
      animation: false,
      grid: { left: 12, right: 16, top: 30, bottom: 26, containLabel: true },
      legend: { top: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      tooltip: { trigger: 'axis', valueFormatter: value => money(String(value ?? 0), currency) },
      xAxis: {
        type: 'category',
        data: rows.map(row => row.cost_date.slice(5)),
        axisLabel: { color: axis.text, fontSize: 10.5 },
        axisLine: { lineStyle: { color: axis.line } },
      },
      yAxis: { type: 'value', axisLabel: { color: axis.text, fontSize: 10.5 }, splitLine: { lineStyle: { color: axis.line } } },
      series: [
        {
          name: 'Daily actual', type: 'bar', barMaxWidth: 14,
          itemStyle: { color: `${theme.palette.primary.main}88` },
          data: rows.map(row => Number(row.actual)),
        },
        {
          name: 'Cumulative actual', type: 'line', smooth: true, symbol: 'none',
          itemStyle: { color: theme.palette.primary.main }, lineStyle: { width: 2.2 },
          areaStyle: { color: `${theme.palette.primary.main}16` },
          data: rows.map(row => Number(row.cumulative)),
        },
      ],
    }
  }, [data, currency, theme, axis])

  const mixOption: EChartsOption = useMemo(() => {
    const colors = [
      theme.palette.primary.main,
      theme.palette.info.main,
      theme.palette.secondary.main,
      theme.palette.warning.main,
    ]
    const rows = (data?.cost_groups ?? []).filter(row => Number(row.actual ?? 0) > 0)
    return {
      animation: false,
      tooltip: { trigger: 'item', valueFormatter: value => money(String(value ?? 0), currency) },
      legend: { bottom: 0, textStyle: { color: axis.text }, itemWidth: 12, itemHeight: 8 },
      series: [{
        type: 'pie',
        radius: ['50%', '74%'],
        center: ['50%', '43%'],
        label: { show: false },
        itemStyle: { borderColor: theme.palette.background.paper, borderWidth: 2 },
        data: rows.map((row, index) => ({
          name: row.label, value: Number(row.actual ?? 0), itemStyle: { color: colors[index % colors.length] },
        })),
      }],
    }
  }, [data, currency, theme, axis])

  const depthOption: EChartsOption = useMemo(() => {
    const rows = [...(data?.wells ?? [])]
      .filter(row => row.depth_progress_percent !== null)
      .sort((a, b) => Number(a.depth_progress_percent ?? 0) - Number(b.depth_progress_percent ?? 0))
      .slice(-10)
    return {
      animation: false,
      grid: { left: 8, right: 48, top: 8, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (params: unknown) => {
          const items = params as { dataIndex: number }[]
          const row = rows[items[0]?.dataIndex ?? 0]
          if (!row) return ''
          return `${row.well_code}<br/>${percent(row.depth_progress_percent)} · ${decimal(row.actual_depth, 0)} of ${decimal(row.planned_depth, 0)} m`
        },
      },
      xAxis: { type: 'value', max: 100, axisLabel: { color: axis.text, fontSize: 10.5, formatter: '{value}%' }, splitLine: { lineStyle: { color: axis.line } } },
      yAxis: {
        type: 'category',
        data: rows.map(row => row.well_code),
        axisLabel: { color: axis.text, fontSize: 10.5, width: 110, overflow: 'truncate' },
        axisLine: { lineStyle: { color: axis.line } },
      },
      series: [{
        type: 'bar', barMaxWidth: 14,
        itemStyle: {
          color: (params: { dataIndex: number }) => Number(rows[params.dataIndex]?.depth_progress_percent ?? 0) >= 100
            ? theme.palette.success.main : theme.palette.primary.main,
          borderRadius: [0, 3, 3, 0],
        },
        label: { show: true, position: 'right', color: axis.text, fontSize: 10.5, formatter: '{c}%' },
        data: rows.map(row => Number(row.depth_progress_percent ?? 0)),
      }],
    }
  }, [data, theme, axis])

  const drillFromChart = (params: { dataIndex?: number }, rows: { well_id: string }[]) => {
    const row = rows[params.dataIndex ?? -1]
    if (row) setDrillWell(row.well_id)
  }

  // ---- table columns ---------------------------------------------------------
  const wellColumns: ColDef<DashboardWellRow>[] = useMemo(() => {
    const columns: ColDef<DashboardWellRow>[] = [
      { headerName: 'RIG', field: 'rig_code', minWidth: 110, flex: 0.6 },
      {
        headerName: 'WELL', field: 'well_code', minWidth: 190, flex: 1.2,
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box minWidth={0}>
          <Typography fontSize={12.5} fontWeight={700} noWrap>{params.data.well_code}</Typography>
          <Typography fontSize={10.5} color="text.secondary" noWrap>{params.data.well_name}</Typography>
        </Box>,
      },
      {
        headerName: 'STATUS', field: 'status', minWidth: 130, flex: 0.7,
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Tag tone={params.data.status === 'completed' ? 'info' : 'success'}>
          {params.data.status === 'completed' ? 'Completed' : 'Active'}
        </Tag>,
      },
    ]
    if (caps.plan) {
      columns.push({
        headerName: 'PLANNED DAYS', field: 'planned_days', minWidth: 140, flex: 0.7,
        headerTooltip: 'Planned days from the well configuration (drilling + configured completion). An approved plan adjustment replaces the configured count.',
        valueFormatter: params => decimal(String(params.value ?? ''), 2),
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box>
          <Typography fontSize={12.5} fontWeight={700}>{decimal(params.data.planned_days, 2)}</Typography>
          <Typography fontSize={10} color="text.secondary">{decimal(params.data.drilling_planned_days, 2)} drilling{params.data.completion_planned_days ? ` · ${decimal(params.data.completion_planned_days, 2)} completion` : ''}</Typography>
        </Box>,
      })
    }
    if (caps.actuals) {
      columns.push({
        headerName: 'ACTUAL DAYS', field: 'actual_days', minWidth: 140, flex: 0.8,
        headerTooltip: 'Calendar days from the first to the last day of the cost register, including any missing sheet inside that span.',
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box>
          <Typography fontSize={12.5} fontWeight={700}>{count(params.data.actual_days)} <Typography component="span" fontSize={10} color="text.secondary">days</Typography></Typography>
          <Typography fontSize={10} color="text.secondary">{count(params.data.recorded_days)} recorded · {count(params.data.sheets)} sheets</Typography>
        </Box>,
      })
      columns.push({
        headerName: 'NPT / UPA', field: 'npt_days', minWidth: 120, flex: 0.65,
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box display="flex" gap={.5} alignItems="center">
          <Tag tone="error">{count(params.data.npt_days)} NPT</Tag>
          <Tag tone="warning">{count(params.data.upa_days)} UPA</Tag>
        </Box>,
      })
    }
    if (caps.plan && caps.actuals) {
      columns.push({
        headerName: 'DEPTH PROGRESS', field: 'depth_progress_percent', minWidth: 190, flex: 1,
        headerTooltip: 'Deepest configured hole section carrying recorded daily cost, against the deepest planned section.',
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data ? <DepthCell row={params.data}/> : null,
      })
    }
    if (caps.budget) {
      columns.push({
        headerName: 'AFE AMOUNT', field: 'afe_amount', minWidth: 145, flex: 0.8,
        headerTooltip: 'Saved AFE estimate total in the selected currency.',
        valueFormatter: params => money(String(params.value ?? ''), currency),
      })
      columns.push({
        headerName: 'SOW ADJUSTED', field: 'sow_adjusted_amount', minWidth: 145, flex: 0.8,
        headerTooltip: 'Latest approved SOW adjustment. Blank means no approved adjustment exists.',
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && (params.data.sow_adjusted_amount === null
          ? <Typography fontSize={12} color="text.secondary">—</Typography>
          : <Box>
            <Typography fontSize={12} fontWeight={700}>{money(params.data.sow_adjusted_amount, currency)}</Typography>
            <Typography fontSize={10} color="text.secondary">Effective {money(params.data.effective_afe_amount, currency)}</Typography>
          </Box>),
      })
    }
    if (caps.actuals) {
      columns.push({
        headerName: 'ACTUAL AMOUNT', field: 'actual_amount', minWidth: 145, flex: 0.8,
        valueFormatter: params => money(String(params.value ?? ''), currency),
      })
    }
    if (caps.budget && caps.actuals) {
      columns.push({
        headerName: 'AFE BALANCE', field: 'afe_balance', minWidth: 145, flex: 0.8,
        cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box>
          <BalanceCell value={params.data.afe_balance} currency={currency}/>
          <Typography fontSize={10} color="text.secondary">{percent(params.data.utilisation_percent)} used</Typography>
        </Box>,
      })
    }
    columns.push({
      headerName: 'ACTIONS', field: 'well_id', minWidth: 130, flex: 0.6, sortable: false,
      cellRenderer: (params: ICellRendererParams<DashboardWellRow>) => params.data && <Box display="flex" gap={.5}>
        <Button size="small" onClick={() => setDrillWell(params.data!.well_id)}>Drill in</Button>
      </Box>,
    })
    return columns
  }, [caps, currency])

  const afeColumns: ColDef<DashboardAfeRow>[] = useMemo(() => {
    const columns: ColDef<DashboardAfeRow>[] = [
      {
        headerName: 'AFE', field: 'afe_code', minWidth: 190, flex: 1.2,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Box minWidth={0}>
          <Typography fontSize={12.5} fontWeight={700} noWrap>{params.data.afe_code}</Typography>
          <Typography fontSize={10.5} color="text.secondary" noWrap>{params.data.afe_name}</Typography>
        </Box>,
      },
      { headerName: 'WELL', field: 'well_code', minWidth: 120, flex: 0.7 },
      { headerName: 'RIG', field: 'rig_code', minWidth: 100, flex: 0.55 },
      { headerName: 'TYPE', field: 'afe_type', minWidth: 110, flex: 0.6 },
      {
        headerName: 'STATUS', field: 'status', minWidth: 115, flex: 0.6,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Tag tone={params.data.status === 'approval' ? 'success' : params.data.status === 'review' ? 'warning' : params.data.status === 'submitted' ? 'info' : 'neutral'}>
          {AFE_STATUS_LABELS[params.data.status] ?? params.data.status}
        </Tag>,
      },
      { headerName: 'CUR', field: 'currency', minWidth: 80, flex: 0.4 },
      {
        headerName: 'AFE AMOUNT', field: 'afe_amount', minWidth: 140, flex: 0.8,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && (params.data.conversion_pending
          ? <Tag tone="warning">Conversion pending</Tag>
          : <Typography fontSize={12}>{money(params.data.afe_amount, params.data.currency)}</Typography>),
      },
      {
        headerName: 'SOW ADJUSTED', field: 'sow_adjusted_amount', minWidth: 135, flex: 0.8,
        valueFormatter: params => money(String(params.value ?? ''), currency),
      },
      {
        headerName: 'ACTUAL', field: 'actual_amount', minWidth: 135, flex: 0.8,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Typography fontSize={12}>{money(params.data.actual_amount, params.data.currency)}</Typography>,
      },
      {
        headerName: 'BALANCE', field: 'afe_balance', minWidth: 135, flex: 0.8,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <BalanceCell value={params.data.afe_balance} currency={params.data.currency}/>,
      },
      {
        headerName: 'DAYS', field: 'actual_days', minWidth: 130, flex: 0.65,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Box>
          <Typography fontSize={12}>{count(params.data.actual_days)} <Typography component="span" fontSize={10} color="text.secondary">days</Typography></Typography>
          <Typography fontSize={10} color="text.secondary">{count(params.data.npt_days)} NPT · {count(params.data.upa_days)} UPA</Typography>
        </Box>,
      },
      {
        headerName: 'ACTIONS', field: 'afe_id', minWidth: 165, flex: 0.75, sortable: false,
        cellRenderer: (params: ICellRendererParams<DashboardAfeRow>) => params.data && <Box display="flex" gap={.5}>
          <Button size="small" onClick={() => setDrillWell(params.data!.well_id)}>Drill in</Button>
          {can('afe:read') && <Button size="small" component={RouterLink} to={`/afe/estimate/${params.data.afe_id}`}>AFE</Button>}
        </Box>,
      },
    ]
    return columns
  }, [can, currency])

  const rigColumns: ColDef<DashboardRigRow>[] = useMemo(() => {
    const columns: ColDef<DashboardRigRow>[] = [
      {
        headerName: 'RIG', field: 'rig_code', minWidth: 190, flex: 1.1,
        cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Box>
          <Typography fontSize={12.5} fontWeight={700}>{params.data.rig_code}</Typography>
          <Typography fontSize={10.5} color="text.secondary">{params.data.rig_name}</Typography>
        </Box>,
      },
      {
        headerName: 'WELLS', field: 'wells', minWidth: 140, flex: 0.7,
        cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Box>
          <Typography fontSize={12.5} fontWeight={700}>{count(params.data.wells)}</Typography>
          <Typography fontSize={10} color="text.secondary">{count(params.data.active_wells)} active · {count(params.data.completed_wells)} completed</Typography>
        </Box>,
      },
    ]
    if (caps.plan) columns.push({ headerName: 'PLANNED DAYS', field: 'planned_days', minWidth: 130, flex: 0.7, valueFormatter: params => decimal(String(params.value ?? ''), 2) })
    if (caps.actuals) columns.push({
      headerName: 'ACTUAL DAYS', field: 'actual_days', minWidth: 135, flex: 0.7,
      cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Box>
        <Typography fontSize={12.5} fontWeight={700}>{count(params.data.actual_days)}</Typography>
        <Typography fontSize={10} color="text.secondary">{count(params.data.recorded_days)} recorded · {count(params.data.draft_sheets)} draft sheets</Typography>
      </Box>,
    })
    if (caps.actuals) columns.push({
      headerName: 'NPT / UPA', field: 'npt_days', minWidth: 120, flex: 0.6,
      cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Typography fontSize={12}>{count(params.data.npt_days)} / {count(params.data.upa_days)}</Typography>,
    })
    if (caps.budget) columns.push({ headerName: 'AFE AMOUNT', field: 'afe_amount', minWidth: 145, flex: 0.8, valueFormatter: params => money(String(params.value ?? ''), currency) })
    if (caps.actuals) columns.push({ headerName: 'ACTUAL AMOUNT', field: 'actual_amount', minWidth: 145, flex: 0.8, valueFormatter: params => money(String(params.value ?? ''), currency) })
    if (caps.budget && caps.actuals) columns.push({
      headerName: 'AFE BALANCE', field: 'afe_balance', minWidth: 145, flex: 0.8,
      cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <BalanceCell value={params.data.afe_balance} currency={currency}/>,
    })
    if (caps.plan && caps.actuals) columns.push({
      headerName: 'DEPTH (m)', field: 'planned_depth', minWidth: 160, flex: 0.85,
      cellRenderer: (params: ICellRendererParams<DashboardRigRow>) => params.data && <Typography fontSize={11.5}>
        {decimal(params.data.actual_depth, 0)} / {decimal(params.data.planned_depth, 0)} m
      </Typography>,
    })
    return columns
  }, [caps, currency])

  const recordExport = async (kind: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/dashboard/business/export-audit', {
      method: 'POST',
      body: body({ format: kind, record_count: recordCount }),
    })
  }

  const alerts = data?.alerts ?? []

  return <>
    <PageHeading
      eyebrow="BUSINESS / DASHBOARD"
      title="Operations dashboard"
      subtitle="Rig and well plans, AFE budgets, SOW adjustments, actual cost, NPT/UPA time and depth progress in one live view. Filter it, open a well, and follow a figure back to the records behind it."
      action={<Box display="flex" alignItems="center" gap={1.2} flexWrap="wrap">
        <FormControlLabel
          control={<Switch size="small" checked={autoRefresh} onChange={event => setAutoRefresh(event.target.checked)}/>}
          label={<Typography fontSize={11.5}>Auto refresh</Typography>}
          sx={{ mr: .5 }}
        />
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </Button>
      </Box>}
    />

    <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, mb: 2 }}>
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap" mb={1.2}>
        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
          <CalendarMonthOutlined sx={{ fontSize: 17, color: 'text.secondary' }}/>
          <Typography fontWeight={800} fontSize={12} textTransform="uppercase" letterSpacing={.8}>Filters</Typography>
          <Typography color="text.secondary" fontSize={11.5}>
            {filters.from || filters.to
              ? `${filters.from ? displayDate(filters.from) : 'start'} → ${filters.to ? displayDate(filters.to) : 'today'}`
              : 'All cost dates'}
            {` · ${currency || 'no currency'} · ${filters.includeDraft ? 'draft and submitted sheets' : 'submitted sheets only'}`}
          </Typography>
        </Box>
        <Box display="flex" gap={.75} flexWrap="wrap">
          {(['all', '7d', '30d', 'month', 'quarter'] as const).map(preset => <Button
            key={preset}
            size="small"
            variant="text"
            onClick={() => { const range = presetRange(preset); setFilters(previous => ({ ...previous, from: range.from, to: range.to })) }}
          >{preset === 'all' ? 'All time' : preset === '7d' ? 'Last 7 days' : preset === '30d' ? 'Last 30 days' : preset === 'month' ? 'This month' : 'This quarter'}</Button>)}
          <Button size="small" color="inherit" onClick={() => setFiltersOpen(open => !open)} aria-expanded={filtersOpen}>{filtersOpen ? 'Hide criteria' : 'Advanced criteria'}</Button>
          <Button size="small" color="inherit" onClick={() => setFilters(EMPTY_FILTERS)}>Reset</Button>
        </Box>
      </Box>
      <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0,1fr))', md: 'repeat(4, minmax(0,1fr))', xl: 'repeat(6, minmax(0,1fr))' } }}>
        <TextField size="small" type="date" label="From" value={filters.from} onChange={event => setFilter('from', event.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField size="small" type="date" label="To" value={filters.to} onChange={event => setFilter('to', event.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField select size="small" label="Currency" value={filters.currency || currency} onChange={event => setFilter('currency', event.target.value)} helperText="Amounts are never mixed across currencies">
          {(data?.filters.currencies ?? (currency ? [currency] : [])).map(code => <MenuItem key={code} value={code}>{code}</MenuItem>)}
        </TextField>
        <FormControlLabel
          control={<Switch size="small" checked={filters.includeDraft} onChange={event => setFilter('includeDraft', event.target.checked)}/>}
          label={<Typography fontSize={11.5}>Include draft sheets</Typography>}
          sx={{ mt: .4 }}
        />
        {filtersOpen && <>
          <TextField select size="small" label="Rig" value={filters.rig} onChange={event => setFilter('rig', event.target.value)}>
            <MenuItem value="">All rigs</MenuItem>
            {(data?.filters.rigs ?? []).map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.code} — {rig.name}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Well" value={filters.well} onChange={event => setFilter('well', event.target.value)}>
            <MenuItem value="">All wells</MenuItem>
            {wellOptions.map(well => <MenuItem key={well.id} value={well.id}>{well.code} — {well.name}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="AFE" value={filters.afe} onChange={event => setFilter('afe', event.target.value)} disabled={!caps.budget}>
            <MenuItem value="">All AFEs</MenuItem>
            {afeOptions.map(afe => <MenuItem key={afe.id} value={afe.id}>{afe.code} — {afe.name}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="AFE type" value={filters.afeType} onChange={event => setFilter('afeType', event.target.value)} disabled={!caps.budget}>
            <MenuItem value="">Both types</MenuItem>
            {(data?.filters.afe_types ?? []).map(type => <MenuItem key={type} value={type}>{type}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Well status" value={filters.status} onChange={event => setFilter('status', event.target.value)}>
            <MenuItem value="">Any status</MenuItem>
            <MenuItem value="active">Active</MenuItem>
            <MenuItem value="completed">Completed</MenuItem>
          </TextField>
        </>}
      </Box>
      <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" mt={1.4} sx={{ borderTop: '1px solid', borderColor: 'divider', pt: 1.2 }}>
        <Tag tone="success">Live</Tag>
        <Typography color="text.secondary" fontSize={11.5} className="tnum" aria-live="polite">
          {refreshedAt ? `Updated ${displayDateTime(refreshedAt.toISOString())}` : 'Loading…'}
          {autoRefresh ? ' · refreshes every 60 seconds' : ''}
          {data ? ` · ${count(data.kpis.wells)} wells · ${count(data.kpis.afes)} AFEs · ${count(data.kpis.rigs)} rigs` : ''}
        </Typography>
        <Box flex={1}/>
        {data && !caps.budget && <Typography color="text.secondary" fontSize={11}>AFE figures are shown only to users with AFE read access.</Typography>}
        {data && !caps.actuals && <Typography color="text.secondary" fontSize={11}>Actual cost figures are shown only to users with daily cost read access.</Typography>}
        {data && !caps.plan && <Typography color="text.secondary" fontSize={11}>Planned days and depth need rig and well read access.</Typography>}
      </Box>
    </Paper>

    <ErrorMessage message={error}/>

    {alerts.length > 0 && <Box display="grid" gap={1} mb={2} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0,1fr))' } }}>
      {alerts.map(alert => <Alert
        key={`${alert.kind}-${alert.title}`}
        severity={alert.severity}
        icon={alert.severity === 'error' ? <ReportProblemOutlined/> : alert.severity === 'warning' ? <WarningAmberRounded/> : <SpeedOutlined/>}
        action={alert.well_id ? <Button size="small" onClick={() => setDrillWell(alert.well_id!)}>Open</Button> : undefined}
        sx={{ alignItems: 'flex-start', '& .MuiAlert-message': { minWidth: 0 } }}
      >
        <Typography fontSize={12.5} fontWeight={700}>{alert.title}</Typography>
        <Typography fontSize={11.5} lineHeight={1.45}>{alert.detail}</Typography>
      </Alert>)}
    </Box>}

    {loading && !data && <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>}

    {data && (data.kpis.wells ?? 0) === 0 && <Paper variant="outlined" sx={{ p: 3, borderRadius: 2, textAlign: 'center' }}>
      <Typography fontWeight={800} fontSize={16}>No wells match the current filters</Typography>
      <Typography color="text.secondary" fontSize={12.5} mt={.8} mb={2}>
        Clear the filters, or create the rig, well and configuration that the dashboard summarises.
      </Typography>
      <Box display="flex" gap={1} justifyContent="center" flexWrap="wrap">
        <Button variant="outlined" onClick={() => setFilters(EMPTY_FILTERS)}>Reset filters</Button>
        {can('rig-well:read') && <Button component={RouterLink} to="/rig-well/wells" variant="contained" endIcon={<ArrowForwardRounded/>}>Well register</Button>}
      </Box>
    </Paper>}

    {data && (data.kpis.wells ?? 0) > 0 && <>
      <Box display="grid" gap={1.4} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', md: 'repeat(3, minmax(0,1fr))', xl: 'repeat(6, minmax(0,1fr))' } }}>
        <KpiCard
          label="Wells in scope"
          value={count(data.kpis.wells)}
          hint={`${count(data.kpis.active_wells)} active · ${count(data.kpis.completed_wells)} completed${caps.plan ? ` · ${count(data.kpis.configured_wells)} configured` : ''}`}
          icon={<LayersOutlined fontSize="small"/>}
        />
        <KpiCard
          label="Planned days"
          value={decimal(data.kpis.planned_days, 2)}
          hint={caps.plan ? 'From the well configuration' : 'Needs rig and well read access'}
          icon={<ScheduleOutlined fontSize="small"/>}
          title="Planned days from Well Configuration (drilling + configured completion), with any approved plan adjustment applied."
        />
        <KpiCard
          label="Actual days"
          value={decimal(data.kpis.actual_days)}
          hint={caps.actuals ? `${count(data.kpis.recorded_days)} recorded · ${data.kpis.day_variance === null ? '—' : `${Number(data.kpis.day_variance) >= 0 ? '+' : ''}${decimal(data.kpis.day_variance, 1)} vs plan`}` : 'Needs daily cost read access'}
          icon={<AlignVerticalBottomRounded fontSize="small"/>}
          tone={data.kpis.day_variance !== null && Number(data.kpis.day_variance) > 0 ? 'warning' : 'default'}
          title="Calendar days from the first to the last day of each well's cost register, summed across wells."
        />
        <KpiCard
          label="NPT / UPA days"
          value={`${decimal(data.kpis.npt_days)} / ${decimal(data.kpis.upa_days)}`}
          hint={caps.actuals ? `${compactMoney(data.kpis.npt_amount, currency)} NPT · ${compactMoney(data.kpis.upa_amount, currency)} UPA` : 'Needs daily cost read access'}
          icon={<EventBusyOutlined fontSize="small"/>}
          tone={data.kpis.npt_days ? 'error' : 'default'}
          title="Distinct cost dates on which a line classified NPT (non-productive time) or UPA (unplanned activity) was recorded."
        />
        <KpiCard
          label="AFE amount"
          value={money(data.kpis.afe_amount, currency)}
          hint={caps.budget ? `${count(data.kpis.afes)} AFEs${data.kpis.conversion_pending_afes ? ` · ${data.kpis.conversion_pending_afes} pending conversion` : ''}` : 'Needs AFE read access'}
          icon={<DescriptionOutlined fontSize="small"/>}
        />
        <KpiCard
          label="SOW adjusted"
          value={money(data.kpis.sow_adjusted_amount, currency)}
          hint={caps.budget ? `Effective plan ${compactMoney(data.kpis.effective_afe_amount, currency)}` : 'Needs AFE read access'}
          icon={<DownloadDoneRounded fontSize="small"/>}
          title="Latest approved AFE SOW adjustment. Where none exists, the saved AFE amount is the effective plan."
        />
        <KpiCard
          label="Actual amount"
          value={money(data.kpis.actual_amount, currency)}
          hint={caps.actuals ? `${count(data.kpis.wells_with_actuals)} wells tracked · ${compactMoney(data.kpis.other_expenses_amount, currency)} other` : 'Needs daily cost read access'}
          icon={<AccountBalanceWalletOutlined fontSize="small"/>}
        />
        <KpiCard
          label="AFE balance"
          value={money(data.kpis.afe_balance, currency)}
          hint={caps.budget && caps.actuals ? `${percent(data.kpis.utilisation_percent)} of the effective plan used` : 'Needs AFE and daily cost access'}
          icon={<TrendingUpRounded fontSize="small"/>}
          tone={data.kpis.afe_balance !== null && Number(data.kpis.afe_balance) < 0 ? 'error' : 'good'}
          title="Effective AFE amount (SOW adjusted, otherwise the saved estimate) less recorded actual cost."
        />
        <KpiCard
          label="Depth progress"
          value={percent(data.kpis.depth_progress_percent)}
          hint={`${decimal(data.kpis.actual_depth, 0)} of ${decimal(data.kpis.planned_depth, 0)} m`}
          icon={<TerrainOutlined fontSize="small"/>}
          title="Actual depth from the daily cost register (standardized in meters, ft ÷ 3.281) against planned well depth in meters across all wells."
        />
        <KpiCard
          label="Rigs in scope"
          value={count(data.kpis.rigs)}
          hint={caps.plan ? `${count(data.kpis.draft_wells)} wells still in configuration draft` : '—'}
          icon={<PrecisionManufacturingOutlined fontSize="small"/>}
        />
        <KpiCard
          label="Over budget"
          value={`${count(data.kpis.over_budget_wells)} / ${count(data.kpis.over_budget_afes)}`}
          hint="Wells / AFEs above their effective plan"
          icon={<ReportProblemOutlined fontSize="small"/>}
          tone={data.kpis.over_budget_wells ? 'error' : 'good'}
        />
        <KpiCard
          label="Cost position"
          value={compactMoney(data.kpis.actual_amount, currency)}
          hint={caps.actuals ? `${count(data.kpis.recorded_days)} recording days · ${compactMoney(data.kpis.upa_amount, currency)} unplanned` : 'Needs daily cost read access'}
          icon={<InsightsOutlined fontSize="small"/>}
        />
      </Box>

      <Box display="grid" gap={2} mt={2} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.05fr) minmax(0, 1fr)' } }}>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Box display="flex" justifyContent="space-between" alignItems="flex-start" gap={1}>
            <Box>
              <Typography fontWeight={800} fontFamily="Manrope" fontSize={15}>AFE against actual cost</Typography>
              <Typography color="text.secondary" fontSize={11.5} mt={.35}>Top wells by effective plan. Click a bar to drill into the well.</Typography>
            </Box>
            <Tag tone={data.kpis.over_budget_wells ? 'error' : 'success'}>{data.kpis.over_budget_wells ? `${data.kpis.over_budget_wells} over` : 'Within plan'}</Tag>
          </Box>
          {chartWells.length
            ? <Box height={286} mt={1}><ReactECharts
              option={costOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}
              onEvents={{ click: (params: { dataIndex?: number }) => drillFromChart(params, chartWells) }}
            /></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={7} textAlign="center">No AFE or actual cost to chart yet.</Typography>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Box display="flex" justifyContent="space-between" alignItems="flex-start" gap={1}>
            <Box>
              <Typography fontWeight={800} fontFamily="Manrope" fontSize={15}>Planned days against actual time</Typography>
              <Typography color="text.secondary" fontSize={11.5} mt={.35}>Actual days split into productive, UPA and NPT. The marker is the plan.</Typography>
            </Box>
            <Tag tone="info">Time</Tag>
          </Box>
          {daysWells.length
            ? <Box height={286} mt={1}><ReactECharts
              option={daysOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}
              onEvents={{ click: (params: { dataIndex?: number }) => drillFromChart(params, daysWells) }}
            /></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={7} textAlign="center">No plan or recorded days to chart yet.</Typography>}
        </Paper>
      </Box>

      <Box display="grid" gap={2} mt={2} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr)' } }}>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Typography fontWeight={800} fontFamily="Manrope" fontSize={15}>Cumulative actual cost</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.35} mb={1}>Every cost date in the filtered range, in {currency || 'the selected currency'}.</Typography>
          {data.daily.length
            ? <Box height={264}><ReactECharts option={trendOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={6} textAlign="center">No recorded cost in this range.</Typography>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Typography fontWeight={800} fontFamily="Manrope" fontSize={15}>Actual cost mix</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.35} mb={1}>Where the recorded money went.</Typography>
          {data.cost_groups.some(row => Number(row.actual ?? 0) > 0)
            ? <Box height={264}><ReactECharts option={mixOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={6} textAlign="center">No recorded cost yet.</Typography>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Box display="flex" justifyContent="space-between" alignItems="flex-start">
            <Box>
              <Typography fontWeight={800} fontFamily="Manrope" fontSize={15}>Depth progress</Typography>
              <Typography color="text.secondary" fontSize={11.5} mt={.35}>Deepest section carrying cost against the plan.</Typography>
            </Box>
            <StraightenRounded sx={{ fontSize: 18, color: 'text.secondary' }}/>
          </Box>
          {data.wells.some(row => row.depth_progress_percent !== null)
            ? <Box height={264} mt={.5}><ReactECharts option={depthOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
            : <Typography color="text.secondary" fontSize={12.5} py={6} textAlign="center">No depth progress available.</Typography>}
        </Paper>
      </Box>

      <Box display="grid" gap={2} mt={2} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 2fr) minmax(0, 1fr)' } }}>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Typography fontWeight={800} fontFamily="Manrope" fontSize={15}>Cost group reconciliation</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.35} mb={1}>AFE planned against recorded actual, by cost group.</Typography>
          <Box sx={{ overflowX: 'auto' }}>
            <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <Box component="thead">
                <Box component="tr">
                  {['Group', 'AFE planned', 'Actual', 'Balance', 'Share'].map(label => <Box component="th" key={label} sx={{
                    textAlign: label === 'Group' ? 'left' : 'right', py: .9, px: 1, borderBottom: '1px solid', borderColor: 'divider',
                    fontSize: 10, letterSpacing: .6, textTransform: 'uppercase', color: 'text.secondary',
                  }}>{label}</Box>)}
                </Box>
              </Box>
              <Box component="tbody">
                {data.cost_groups.map(row => <Box component="tr" key={row.key}>
                  <Box component="td" sx={{ py: .8, px: 1, borderBottom: '1px solid', borderColor: 'divider', fontWeight: 600 }}>{row.label}</Box>
                  <Box component="td" sx={{ py: .8, px: 1, borderBottom: '1px solid', borderColor: 'divider', textAlign: 'right' }}>{money(row.planned, currency)}</Box>
                  <Box component="td" sx={{ py: .8, px: 1, borderBottom: '1px solid', borderColor: 'divider', textAlign: 'right' }}>{money(row.actual, currency)}</Box>
                  <Box component="td" sx={{ py: .8, px: 1, borderBottom: '1px solid', borderColor: 'divider', textAlign: 'right' }}>
                    <BalanceCell value={row.balance} currency={currency}/>
                  </Box>
                  <Box component="td" sx={{ py: .8, px: 1, borderBottom: '1px solid', borderColor: 'divider', textAlign: 'right' }}>{percent(row.share)}</Box>
                </Box>)}
              </Box>
            </Box>
          </Box>
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Typography fontWeight={800} fontFamily="Manrope" fontSize={15}>Time classification</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.35} mb={1}>Days and cost recorded under each classification.</Typography>
          {data.classification.map(row => <Box key={row.key} sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1 }}>
            <Box display="flex" justifyContent="space-between" alignItems="center" gap={1}>
              <Tag tone={row.key === 'NPT' ? 'error' : row.key === 'UPA' ? 'warning' : 'success'}>{row.key}</Tag>
              <Typography fontSize={11.5} color="text.secondary">{count(row.days)} days</Typography>
            </Box>
            <Box display="flex" justifyContent="space-between" mt={.6}>
              <Typography fontSize={12.5} fontWeight={700}>{money(row.actual, currency)}</Typography>
              <Typography fontSize={11} color="text.secondary">{percent(row.share)} of cost</Typography>
            </Box>
          </Box>)}
          {caps.actuals && (data.kpis.other_expenses_amount !== null && Number(data.kpis.other_expenses_amount) > 0) && <Box mt={1.2}>
            <Divider/>
            <Box display="flex" justifyContent="space-between" mt={1}>
              <Typography fontSize={11.5} color="text.secondary">Other expenses (unbudgeted)</Typography>
              <Typography fontSize={12} fontWeight={700} color="warning.main">{money(data.kpis.other_expenses_amount, currency)}</Typography>
            </Box>
          </Box>}
        </Paper>
      </Box>

      <Box mt={2.5}>
        <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap" mb={1}>
          <Box>
            <Typography fontWeight={800} fontFamily="Manrope" fontSize={15}>Register drill-through</Typography>
            <Typography color="text.secondary" fontSize={11.5} mt={.35}>
              Each row carries its own search, advanced filters, date range, 20/50/100 paging and CSV/XLSX/PDF export. Use Drill in for the record-level panel.
            </Typography>
          </Box>
          {caps.actuals && can('daily-cost:read') && <Button component={RouterLink} to="/daily-cost/analysis" size="small" endIcon={<ArrowForwardRounded/>}>Well cost analysis</Button>}
        </Box>
        <Tabs value={tab} onChange={(_event, value: number) => setTab(value)} sx={{ mb: 1.5 }}>
          <Tab label={`Wells (${data.wells.length})`}/>
          {caps.budget && <Tab label={`AFEs (${data.afes.length})`}/>}
          <Tab label={`Rigs (${data.rigs.length})`}/>
        </Tabs>
        {tab === 0 && <DataTable
          rows={data.wells}
          columns={wellColumns}
          rowKey="well_id"
          searchPlaceholder="Search wells, rigs, locations..."
          exportName="business-dashboard-wells"
          canExport={canExport}
          onExport={recordExport}
        />}
        {tab === 1 && caps.budget && <DataTable
          rows={data.afes}
          columns={afeColumns}
          rowKey="afe_id"
          searchPlaceholder="Search AFEs, wells, rigs, statuses..."
          exportName="business-dashboard-afes"
          canExport={canExport}
          onExport={recordExport}
        />}
        {tab === 2 && <DataTable
          rows={data.rigs}
          columns={rigColumns}
          rowKey="rig_id"
          searchPlaceholder="Search rigs..."
          exportName="business-dashboard-rigs"
          canExport={canExport}
          onExport={recordExport}
        />}
      </Box>

      <Box display="flex" gap={2} flexWrap="wrap" mt={1.5} alignItems="center">
        <Typography color="text.secondary" fontSize={11}>
          Planned days and AFE amounts are plan-level figures; the date range narrows the cost register only.
        </Typography>
        <Box flex={1}/>
        <Tooltip title="Amounts are grouped by the AFE standard currency, never converted silently.">
          <Typography color="text.secondary" fontSize={11} sx={{ textDecoration: 'underline dotted', cursor: 'help' }}>Currency: {currency || 'not set'}</Typography>
        </Tooltip>
      </Box>
    </>}

    <DrillThroughPanel wellId={drillWell} filters={filters} onClose={() => setDrillWell('')}/>
  </>
}

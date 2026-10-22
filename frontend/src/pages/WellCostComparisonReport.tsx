import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { AccountBalanceWalletOutlined, ArrowBackRounded, DownloadOutlined, RefreshRounded, ScheduleOutlined, TrendingUpRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, PageHeading } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { Afe } from '../lib/afe'
import type { DailyCostEntry } from '../lib/dailyCost'
import type { LihCostEntry } from '../lib/lihCost'
import { formatDepth, type Well } from '../lib/rigWell'
import { formatDepthMeters } from '../lib/units'

type CostRow = {
  id: string
  rig_name: string
  well_name: string
  well_code: string
  block: string
  afe_amount: string
  sow_adjustment: string
  actual_cost: string
  lih_cost: string
  actual_including_lih: string
  actual_usd: string
  afe_balance: string
  costs_incurred: string
  planned_depth_m: string
  actual_depth_m: string
  planned_days: number
  adjusted_planned_days: number | null
  actual_days: number | null
  first_cost_date: string
}

type CurrencyAmounts = Map<string, number>
type Sources = { wells: Well[]; afes: Afe[]; entries: DailyCostEntry[]; lih: LihCostEntry[] }

function addAmount(amounts: CurrencyAmounts, currency: string, value: string | number | null | undefined) {
  if (value == null || value === '') return
  const key = currency.trim() || 'Currency not specified'
  amounts.set(key, (amounts.get(key) ?? 0) + Number(value))
}

function amountText(amounts: CurrencyAmounts, hasRecords: boolean, pending = false): string {
  if (!hasRecords) return '—'
  if (pending) return 'Pending conversion'
  if (!amounts.size) return '—'
  return [...amounts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([currency, value]) => `${currency} ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`)
    .join(' · ')
}

function daySpan(first: string, last: string): number {
  const start = Date.parse(`${first}T00:00:00Z`)
  const end = Date.parse(`${last}T00:00:00Z`)
  return Math.max(1, Math.floor((end - start) / 86_400_000) + 1)
}

function StatCard({ label, value, note, icon }: { label: string; value: string; note: string; icon: ReactNode }) {
  return <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, minWidth: 0 }}>
    <Box display="flex" justifyContent="space-between" alignItems="center" gap={1}>
      <Typography color="text.secondary" fontSize={10.5} fontWeight={800} letterSpacing={.75} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon">{icon}</Box>
    </Box>
    <Typography sx={{ fontSize: 23, my: .8, fontWeight: 800, overflowWrap: 'anywhere' }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11.2}>{note}</Typography>
  </Paper>
}

export default function WellCostComparisonReport() {
  const { can } = useAuth()
  const [sources, setSources] = useState<Sources>({ wells: [], afes: [], entries: [], lih: [] })
  const [loading, setLoading] = useState(true)
  const [loadErrors, setLoadErrors] = useState<string[]>([])
  const [refreshKey, setRefreshKey] = useState(0)

  const canReadAfe = can('afe:read')
  const canReadDaily = can('daily-cost:read')
  const canExport = can('rig-well:export')
    && (!canReadAfe || can('afe:export'))
    && (!canReadDaily || can('daily-cost:export'))

  const load = useCallback(async () => {
    setLoading(true)
    setLoadErrors([])
    const [wellsResult, afesResult, entriesResult, lihResult] = await Promise.allSettled([
      api<Well[]>('/rig-well/wells'),
      canReadAfe ? api<Afe[]>('/afe/afes') : Promise.resolve([] as Afe[]),
      canReadDaily ? api<DailyCostEntry[]>('/daily-cost/entries') : Promise.resolve([] as DailyCostEntry[]),
      // LIH is a separate register, so it is read alongside the daily actuals
      // and deducted from the AFE in this comparison too.
      canReadDaily ? api<LihCostEntry[]>('/lih-cost/entries') : Promise.resolve([] as LihCostEntry[]),
    ])
    const errors: string[] = []
    const wells = wellsResult.status === 'fulfilled' ? wellsResult.value : []
    if (wellsResult.status === 'rejected') errors.push(`Well register: ${wellsResult.reason instanceof Error ? wellsResult.reason.message : 'could not be loaded'}`)
    const afes = afesResult.status === 'fulfilled' ? afesResult.value : []
    if (afesResult.status === 'rejected') errors.push(`AFE totals: ${afesResult.reason instanceof Error ? afesResult.reason.message : 'could not be loaded'}`)
    const entries = entriesResult.status === 'fulfilled' ? entriesResult.value : []
    if (entriesResult.status === 'rejected') errors.push(`Daily actuals: ${entriesResult.reason instanceof Error ? entriesResult.reason.message : 'could not be loaded'}`)
    const lih = lihResult.status === 'fulfilled' ? lihResult.value : []
    if (lihResult.status === 'rejected') errors.push(`LIH cost register: ${lihResult.reason instanceof Error ? lihResult.reason.message : 'could not be loaded'}`)
    setSources({ wells, afes, entries, lih })
    setLoadErrors(errors)
    setLoading(false)
  }, [canReadAfe, canReadDaily, refreshKey])

  useEffect(() => { void load() }, [load])

  const rows = useMemo<CostRow[]>(() => {
    const afesByWell = new Map<string, Afe[]>()
    for (const afe of sources.afes) {
      if (afe.is_deleted) continue
      const group = afesByWell.get(afe.well_id) ?? []
      group.push(afe)
      afesByWell.set(afe.well_id, group)
    }
    const lihByWell = new Map<string, LihCostEntry[]>()
    for (const entry of sources.lih) {
      if (entry.is_deleted) continue
      const group = lihByWell.get(entry.well_id) ?? []
      group.push(entry)
      lihByWell.set(entry.well_id, group)
    }
    const actualByWell = new Map<string, DailyCostEntry[]>()
    for (const entry of sources.entries) {
      if (entry.is_deleted) continue
      const group = actualByWell.get(entry.well_id) ?? []
      group.push(entry)
      actualByWell.set(entry.well_id, group)
    }

    return sources.wells.map(well => {
      const afes = afesByWell.get(well.id) ?? []
      const entries = actualByWell.get(well.id) ?? []
      const afeAmounts: CurrencyAmounts = new Map()
      const effectiveAmounts: CurrencyAmounts = new Map()
      const adjustmentAmounts: CurrencyAmounts = new Map()
      const actualAmounts: CurrencyAmounts = new Map()
      let pendingConversion = false
      for (const afe of afes) {
        if (afe.conversion_pending || afe.total_cost == null) pendingConversion = true
        else {
          addAmount(afeAmounts, afe.standard_currency, afe.total_cost)
          // The effective budget is the approved adjusted total where one
          // exists, otherwise the original AFE total. Balance and % incurred
          // are measured against it.
          const effective = afe.has_sow_adjustment && afe.adjusted_total != null ? afe.adjusted_total : afe.total_cost
          addAmount(effectiveAmounts, afe.standard_currency, effective)
          if (afe.has_sow_adjustment && afe.adjusted_total != null) {
            addAmount(adjustmentAmounts, afe.standard_currency, Number(afe.adjusted_total) - Number(afe.total_cost))
          }
        }
      }
      for (const entry of entries) addAmount(actualAmounts, entry.standard_currency, entry.total_cost)
      const lihAmounts: CurrencyAmounts = new Map()
      for (const entry of lihByWell.get(well.id) ?? []) addAmount(lihAmounts, entry.currency, entry.total_cost)

      const afeAmount = amountText(afeAmounts, afes.length > 0, pendingConversion)
      const sowAdjustment = adjustmentAmounts.size
        ? [...adjustmentAmounts.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([currency, value]) => {
            const sign = value > 0 ? '+' : ''
            return `${currency} ${sign}${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
          })
          .join(' · ')
        : '—'
      const actualCost = amountText(actualAmounts, entries.length > 0)
      const lihCost = amountText(lihAmounts, lihAmounts.size > 0)
      // Actual including LIH, per currency, for the comparison column.
      const combinedAmounts: CurrencyAmounts = new Map(actualAmounts)
      for (const [currency, value] of lihAmounts) combinedAmounts.set(currency, (combinedAmounts.get(currency) ?? 0) + value)
      const actualIncludingLih = amountText(combinedAmounts, combinedAmounts.size > 0)
      const matchingCurrency = effectiveAmounts.size === 1 && actualAmounts.size <= 1
        && (actualAmounts.size === 0 || [...effectiveAmounts.keys()][0] === [...actualAmounts.keys()][0])
      let balance = '—'
      let incurred = '—'
      if (afes.length && !pendingConversion && matchingCurrency) {
        const currency = [...effectiveAmounts.keys()][0]
        const planned = effectiveAmounts.get(currency) ?? 0
        // LIH reduces the AFE available before the actual cost is measured, and
        // is itself part of the actual spend.
        const actual = actualAmounts.get(currency) ?? 0
        const lihInCurrency = lihAmounts.get(currency) ?? 0
        balance = `${currency} ${(planned - lihInCurrency - actual).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        incurred = planned > 0 ? `${((actual + lihInCurrency) / planned * 100).toFixed(1)}%` : '—'
      }

      const dates = entries.map(entry => String(entry.cost_date)).sort()
      const firstDate = dates[0] ?? ''
      const lastDate = dates.at(-1) ?? ''
      const totalUsd = entries.reduce((sum, entry) => sum + Number(entry.total_cost_usd ?? entry.total_cost ?? 0), 0)
      const latestDepthEntry = [...entries]
        .filter(entry => entry.actual_depth != null && entry.actual_depth !== '')
        .sort((a, b) => String(a.cost_date).localeCompare(String(b.cost_date)))
        .at(-1)
      return {
        id: well.id,
        rig_name: well.rig_name,
        well_name: well.well_name,
        well_code: well.well_code,
        block: well.block || '—',
        afe_amount: canReadAfe ? afeAmount : 'Not available',
        sow_adjustment: canReadAfe ? sowAdjustment : 'Not available',
        actual_cost: canReadDaily ? actualCost : 'Not available',
        lih_cost: canReadDaily ? lihCost : 'Not available',
        actual_including_lih: canReadDaily ? actualIncludingLih : 'Not available',
        actual_usd: canReadDaily
          ? entries.length > 0
            ? `USD ${totalUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : '—'
          : 'Not available',
        afe_balance: canReadAfe && canReadDaily ? balance : 'Not available',
        costs_incurred: canReadAfe && canReadDaily ? incurred : 'Not available',
        planned_depth_m: formatDepth(well.total_depth, well.depth_unit, well.total_depth_m),
        actual_depth_m: canReadDaily ? formatDepthMeters(latestDepthEntry?.actual_depth, 'm') : 'Not available',
        planned_days: Number(well.total_days ?? 0),
        adjusted_planned_days: well.has_plan_adjustment && well.adjusted_total_days != null
          ? Number(well.adjusted_total_days)
          : null,
        actual_days: firstDate ? daySpan(firstDate, lastDate) : null,
        first_cost_date: firstDate,
      }
    })
  }, [sources, canReadAfe, canReadDaily])

  const auditExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    const audits: Promise<unknown>[] = [api('/rig-well/export-audit', {
      method: 'POST', body: body({ module: 'wells', format, record_count: recordCount, include_deleted: false }),
    })]
    if (canReadAfe) audits.push(api('/afe/export-audit', {
      method: 'POST', body: body({ module: 'estimates', format, record_count: recordCount, include_deleted: false }),
    }))
    if (canReadDaily) audits.push(api('/daily-cost/export-audit', {
      method: 'POST', body: body({ module: 'budget-comparison', format, record_count: recordCount, include_deleted: false }),
    }))
    await Promise.all(audits)
  }

  const columns = useMemo<ColDef<CostRow>[]>(() => [
    { headerName: 'RIG', field: 'rig_name', minWidth: 155 },
    {
      headerName: 'WELL', field: 'well_name', minWidth: 185, flex: 1.15,
      cellRenderer: (params: ICellRendererParams<CostRow>) => {
        const row = params.data
        if (!row) return null
        return <Button component={RouterLink} to={`/daily-cost/analysis/${row.id}`} size="small" sx={{ justifyContent: 'flex-start', px: 0, minWidth: 0, fontWeight: 700 }}>
          {row.well_name || row.well_code}
        </Button>
      },
    },
    { headerName: 'BLOCK', field: 'block', minWidth: 115 },
    { headerName: 'AFE AMOUNT', field: 'afe_amount', minWidth: 190, headerTooltip: 'Original approved AFE amount' },
    {
      headerName: 'SOW ADJ.', field: 'sow_adjustment', minWidth: 165,
      headerTooltip: 'Approved SOW adjustment (Adjusted AFE − Original AFE). A plus means scope was added.',
    },
    { headerName: 'ACTUAL COST', field: 'actual_cost', minWidth: 190 },
    {
      headerName: 'LIH COST', field: 'lih_cost', minWidth: 165,
      headerTooltip: 'LIH Cost Register cost: deducted from the AFE and added to the actual cost',
    },
    {
      headerName: 'ACTUAL INCL. LIH', field: 'actual_including_lih', minWidth: 185,
      headerTooltip: 'Daily actual cost plus the LIH Cost Register cost',
    },
    { headerName: 'ACTUAL USD (STD)', field: 'actual_usd', minWidth: 175, headerTooltip: 'Standardized USD actual cost across all wells' },
    { headerName: 'AFE BALANCE', field: 'afe_balance', minWidth: 190, headerTooltip: 'Adjusted AFE amount less the LIH cost and the actual cost' },
    { headerName: '% COSTS INCURRED', field: 'costs_incurred', minWidth: 155, headerTooltip: 'Actual cost plus LIH as a share of the adjusted AFE amount' },
    { headerName: 'PLANNED DEPTH (m)', field: 'planned_depth_m', minWidth: 160 },
    { headerName: 'ACTUAL DEPTH (m)', field: 'actual_depth_m', minWidth: 155 },
    { headerName: 'PLANNED DAYS', field: 'planned_days', minWidth: 135, headerTooltip: 'Original planned days', valueFormatter: params => Number(params.value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 }) },
    {
      headerName: 'ADJ PLANNED DAYS', field: 'adjusted_planned_days', minWidth: 160,
      headerTooltip: 'Adjusted planned days from the approved plan adjustment',
      valueFormatter: params => params.value == null ? '—' : Number(params.value).toLocaleString(undefined, { maximumFractionDigits: 2 }),
    },
    { headerName: 'ACTUAL DAYS', field: 'actual_days', minWidth: 125, valueFormatter: params => params.value == null ? '—' : Number(params.value).toLocaleString() },
    { headerName: 'FIRST COST DATE', field: 'first_cost_date', minWidth: 155, valueFormatter: params => params.value ? new Date(`${params.value}T00:00:00`).toLocaleDateString() : '—' },
  ], [])

  const wellsWithAfe = rows.filter(row => row.afe_amount !== '—' && row.afe_amount !== 'Not available').length
  const wellsWithActual = rows.filter(row => row.actual_cost !== '—' && row.actual_cost !== 'Not available').length
  const wellsConfigured = sources.wells.filter(well => well.config_status === 'configured').length

  return <>
    <PageHeading
      eyebrow="REPORTS / WELL-WISE COST COMPARISONS"
      title="Well-wise cost comparisons"
      subtitle="Compare well plans, AFE budgets and actual daily costs. Actual days span the first through the latest daily cost date."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/reports" variant="outlined" startIcon={<ArrowBackRounded/>}>Reports</Button>
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => setRefreshKey(value => value + 1)} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</Button>
      </Box>}
    />
    {loadErrors.map(error => <ErrorMessage key={error} message={error}/>)}
    {!canReadAfe && <Alert severity="info" sx={{ mb: 2 }}>AFE figures are hidden because your role does not include AFE read access.</Alert>}
    {!canReadDaily && <Alert severity="info" sx={{ mb: 2 }}>Daily actual costs are hidden because your role does not include daily cost read access.</Alert>}
    <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }} gap={1.5} mb={2}>
      <StatCard label="Wells listed" value={loading ? '—' : rows.length.toLocaleString()} note="Active wells in the register" icon={<AccountBalanceWalletOutlined/>}/>
      <StatCard label="With an AFE" value={loading ? '—' : wellsWithAfe.toLocaleString()} note="Wells with current AFE records" icon={<DownloadOutlined/>}/>
      <StatCard label="With actual costs" value={loading ? '—' : wellsWithActual.toLocaleString()} note="Wells with daily cost entries" icon={<TrendingUpRounded/>}/>
      <StatCard label="Configured plans" value={loading ? '—' : wellsConfigured.toLocaleString()} note="Wells with planned days configured" icon={<ScheduleOutlined/>}/>
    </Box>
    <Alert severity="info" sx={{ mb: 2 }}>
      AFE and actual amounts are grouped by currency. Balance and cost-incurred percentage are calculated only when the well has a single AFE currency that matches its actual-cost currency.
      Where an approved SOW adjustment exists, the balance is the adjusted AFE amount less actual cost.
      LIH Cost Register cost is added to the actual cost and deducted from the AFE before the balance and the percentage are calculated.
    </Alert>
    {loading
      ? <Paper variant="outlined" sx={{ minHeight: 220, display: 'grid', placeItems: 'center', borderRadius: 2 }}><CircularProgress size={28}/></Paper>
      : wellsWithAfe === 0 && wellsWithActual === 0 && rows.length === 0
        ? <Paper variant="outlined" sx={{ p: 3, textAlign: 'center', borderRadius: 2 }}><Typography color="text.secondary">No wells are available for this report.</Typography></Paper>
        : <DataTable
            rows={rows}
            columns={columns}
            exportName="well-wise-cost-comparison"
            searchPlaceholder="Search wells, rigs, blocks or costs..."
            canExport={canExport}
            onExport={auditExport}
            fillHeight
          />}
    {!canExport && <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 1.2 }}>
      Export is available when you have export permission for the well register and each cost source visible in this report.
    </Typography>}
  </>
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom'
import {
  AddRounded, DeleteForeverOutlined, DeleteOutlineRounded, EventNoteOutlined,
  FactCheckOutlined, FilterAltOffOutlined, InsightsOutlined, PlaylistAddCheckRounded,
  RestoreRounded, RefreshRounded, PrintOutlined, WaterDropOutlined,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, Divider, MenuItem, Paper, Tab, Tabs, TextField, Typography,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { WellCostPrintDialog } from '../components/daily-cost/WellCostPrintDialog'
import { BulkDailyCostPrintDialog } from '../components/daily-cost/BulkDailyCostPrintDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import {
  readActiveScope, requestedScope, resolveWorkingScope, scopeLink, writeActiveScope, type ActiveScope,
} from '../lib/activeScope'
import {
  dailyMoney, DAILY_COST_STATUSES, displayDate, entryQuery, localToday,
  type DailyCostDay, type DailyCostEntry, type DailyCostReference,
  type DailyCostStatus,
} from '../lib/dailyCost'
import { formatDepthMeters } from '../lib/units'

type CostTab = 'register' | 'final_review' | 'completed'

const TABS: { key: CostTab; label: string }[] = [
  { key: 'register', label: 'Daily cost register' },
  { key: 'final_review', label: 'Wells for final review' },
  { key: 'completed', label: 'Completed wells' },
]

type PendingAction = { kind: 'delete' | 'restore' | 'purge'; rows: DailyCostEntry[] }

/**
 * The registers that capture the detail behind a daily sheet. Each shortcut opens
 * its register with the register's working scope, so the rig and well are already
 * selected there (and can still be changed on the target page).
 */
const SCOPED_REGISTERS: { label: string; path: string; icon: typeof WaterDropOutlined }[] = [
  { label: 'Mud cost analysis', path: '/daily-cost/mud-cost-analysis', icon: WaterDropOutlined },
  { label: 'LIH Cost Register', path: '/daily-cost/lih-register', icon: PlaylistAddCheckRounded },
  { label: 'NDT Inspection Register', path: '/daily-cost/ndt-inspections', icon: FactCheckOutlined },
]

function isValidCostDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function scopeState(well: DailyCostReference['wells'][number], scope: 'drilling' | 'completion') {
  return scope === 'completion'
    ? { status: well.completion_status, config_status: well.completion_config_status }
    : { status: well.status, config_status: well.config_status }
}

export default function DailyCostManagement() {
  const { can, user } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const deletedView = params.get('view') === 'deleted'
  const requested = params.get('tab')
  const active: CostTab = TABS.some(tab => tab.key === requested) ? (requested as CostTab) : 'register'
  // The rig and well the user is costing right now: the scope a link carried, or
  // the one remembered from the last register visit. The link is read at once; the
  // remembered scope is read once the workspace is known (see below).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const linkedScope = useMemo<ActiveScope>(() => requestedScope(params), [])
  const [scopeRigId, setScopeRigId] = useState(linkedScope.rigId)
  const [scopeWellId, setScopeWellId] = useState(linkedScope.wellId)
  const scopeInitialised = useRef(false)
  const [rows, setRows] = useState<DailyCostEntry[]>([])
  const [reference, setReference] = useState<DailyCostReference | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<DailyCostEntry[]>([])
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [actionError, setActionError] = useState('')
  const [actionBusy, setActionBusy] = useState(false)
  const [printOpen, setPrintOpen] = useState(false)
  const [bulkPrintOpen, setBulkPrintOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [wellId, setWellId] = useState('')
  const [afeId, setAfeId] = useState('')
  const [costDate, setCostDate] = useState(localToday())
  const [usdExchangeRate, setUsdExchangeRate] = useState('')
  const [remarks, setRemarks] = useState('')
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
      if (deletedView) {
        // Deleted rows remain recoverable even when a deleted well/AFE makes the
        // active reference-data request unavailable. The snapshots on each row
        // are sufficient to render and restore the register.
        const entries = await api<DailyCostEntry[]>('/daily-cost/entries/deleted')
        setRows(entries)
        try { setReference(await api<DailyCostReference>('/daily-cost/reference')) }
        catch { setReference(null) }
      } else {
        const [entries, ref] = await Promise.all([
          api<DailyCostEntry[]>(`/daily-cost/entries${filterQuery}`),
          api<DailyCostReference>('/daily-cost/reference'),
        ])
        setRows(entries)
        setReference(ref)
      }
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : 'Daily Cost Management could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [deletedView, filterQuery])

  useEffect(() => { void load() }, [load])

  const wellsById = useMemo(() => Object.fromEntries((reference?.wells ?? []).map(well => [well.id, well])), [reference])
  const afesById = useMemo(() => Object.fromEntries((reference?.afes ?? []).map(afe => [afe.id, afe])), [reference])

  const rowScope = (row: DailyCostEntry) => {
    const well = wellsById[row.well_id]
    const afe = afesById[row.afe_id]
    if (!well || !afe) return 'drilling'
    return afe.configuration_scope as 'drilling' | 'completion'
  }

  const rowTab = (row: DailyCostEntry): CostTab => {
    const well = wellsById[row.well_id]
    const afe = afesById[row.afe_id]
    if (!well || !afe) return 'register'
    const state = scopeState(well, afe.configuration_scope as 'drilling' | 'completion')
    if (state.config_status === 'final_review') return 'final_review'
    if (state.status === 'completed') return 'completed'
    return 'register'
  }

  const tabRows = useMemo(() => rows.filter(row => deletedView ? true : rowTab(row) === active), [rows, active, deletedView])

  // Wells whose at least one non-deleted scope is configured can take new daily sheets; the sheet's scope follows its AFE.
  const wells = useMemo(() => reference?.wells.filter(well => {
    const drillingReady = !well.drilling_is_deleted && well.status === 'active' && well.config_status === 'configured'
    const completionReady = !well.completion_is_deleted && well.completion_status === 'active' && well.completion_config_status === 'configured'
    return drillingReady || completionReady
  }) ?? [], [reference])
  const selectedWell = wells.find(well => well.id === wellId)
  const afes = useMemo(() => reference?.afes.filter(afe => {
    if (afe.well_id !== wellId) return false
    const well = wellsById[afe.well_id]
    const afeScope = afe.configuration_scope ?? 'drilling'
    if (well && (afeScope === 'completion' ? well.completion_is_deleted : well.drilling_is_deleted)) return false
    return true
  }) ?? [], [reference, wellId, wellsById])
  const selectedAfe = afes.find(afe => afe.id === afeId)
  const selectedScope: 'drilling' | 'completion' = selectedAfe?.configuration_scope
    ?? (selectedWell && (selectedWell.drilling_is_deleted || selectedWell.config_status !== 'configured') ? 'completion' : 'drilling')
  const needsUsdExchangeRate = Boolean(selectedAfe && selectedAfe.standard_currency.toUpperCase() !== 'USD')
  const usdRateValid = !needsUsdExchangeRate || (Number.isFinite(Number(usdExchangeRate)) && Number(usdExchangeRate) > 0)
  const createDateValid = isValidCostDate(costDate)
  const selectedDuplicate = rows.find(row => row.well_id === wellId && row.afe_id === afeId && row.cost_date === costDate)
  const wellSubActivities = useMemo(
    () => reference?.sub_activities.filter(item => item.well_id === wellId && (item.scope ?? 'drilling') === selectedScope) ?? [],
    [reference, wellId, selectedScope],
  )
  const missingSubActivities = Boolean(selectedWell) && wellSubActivities.length === 0

  // The current rig and well. They default from the last register visit (or the
  // link that opened the page), drive the shortcuts and the new sheet, and stay
  // changeable by the user here or on any register they open.
  const scopeRigs = reference?.rigs ?? []
  const scopeWellOptions = useMemo(
    () => (reference?.wells ?? []).filter(well => !scopeRigId || well.rig_id === scopeRigId),
    [reference, scopeRigId],
  )
  const scopeRig = scopeRigs.find(rig => rig.id === scopeRigId) ?? null
  const scopeWell = reference?.wells.find(well => well.id === scopeWellId) ?? null
  const scopeLinks: ActiveScope = { rigId: scopeRigId, wellId: scopeWellId }

  useEffect(() => {
    if (!reference || !user || scopeInitialised.current) return
    scopeInitialised.current = true
    const remembered = readActiveScope(user.organization_slug)
    const newest = [...rows].sort((left, right) => right.cost_date.localeCompare(left.cost_date))[0]
    const next = resolveWorkingScope(
      // A well or rig named in the link outranks the remembered one.
      { rigId: scopeRigId || remembered.rigId, wellId: scopeWellId || remembered.wellId },
      reference.wells, reference.rigs,
      // The sheet last costed here, then the first well that can take a new sheet.
      [newest?.well_id, wells[0]?.id],
    )
    if (next.wellId !== scopeWellId) setScopeWellId(next.wellId)
    if (next.rigId !== scopeRigId) setScopeRigId(next.rigId)
  }, [reference, user, rows, scopeRigId, scopeWellId, wells])

  useEffect(() => {
    if (!scopeInitialised.current || !user) return
    writeActiveScope({ rigId: scopeRigId, wellId: scopeWellId }, user.organization_slug)
  }, [scopeRigId, scopeWellId, user])

  const chooseScopeRig = (value: string) => {
    setScopeRigId(value)
    const nextWells = (reference?.wells ?? []).filter(well => !value || well.rig_id === value)
    if (!nextWells.some(well => well.id === scopeWellId)) setScopeWellId(nextWells[0]?.id ?? '')
  }
  const chooseScopeWell = (value: string) => {
    setScopeWellId(value)
    const well = reference?.wells.find(item => item.id === value)
    if (well) setScopeRigId(well.rig_id)
  }
  // Opening a sheet makes its well the current scope, so the register and its
  // shortcuts resume on the well the user was last costing.
  const rememberRowScope = useCallback((row: DailyCostEntry) => {
    const well = wellsById[row.well_id]
    if (!well) return
    setScopeWellId(well.id)
    setScopeRigId(well.rig_id)
  }, [wellsById])

  useEffect(() => {
    if (!createOpen || !reference) return
    if (!wellId && wells.length) setWellId(wells.find(well => well.id === scopeWellId)?.id ?? wells[0].id)
    if (wellId && !afes.some(afe => afe.id === afeId)) setAfeId(afes[0]?.id ?? '')
  }, [createOpen, reference, wellId, afeId, wells, scopeWellId, afes])

  const openCreate = () => {
    setCreateError('')
    setRemarks('')
    setUsdExchangeRate('')
    setCostDate(localToday())
    // A new sheet starts on the current rig and well; the dialog still lets the
    // user pick another configured well or AFE.
    const firstWell = wells.find(well => well.id === scopeWellId) ?? wells[0]
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
    if (needsUsdExchangeRate && !usdRateValid) {
      setCreateError(`Enter a positive USD conversion rate for ${selectedAfe.standard_currency.toUpperCase()} so USD values can be standardized across all wells.`)
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
        method: 'POST',
        body: body({
          well_id: selectedWell.id,
          afe_id: selectedAfe.id,
          cost_date: costDate,
          remarks,
          ...(needsUsdExchangeRate ? { usd_exchange_rate: usdExchangeRate.trim() } : {}),
        }),
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
      module: deletedView ? 'deleted' : `daily-cost-${active}`, format, record_count: recordCount, include_deleted: deletedView,
    }) })
  }

  const columns = useMemo<ColDef<DailyCostEntry>[]>(() => [
    { headerName: 'DATE', field: 'cost_date', minWidth: 125, width: 130, valueFormatter: params => displayDate(String(params.value ?? '')) },
    { headerName: 'DAILY SHEET', field: 'daily_cost_code', minWidth: 230, flex: 1.1 },
    { headerName: 'WELL', field: 'well_code', minWidth: 150, valueGetter: params => `${params.data?.well_code ?? ''} · ${params.data?.well_name ?? ''}` },
    { headerName: 'AFE', field: 'afe_code', minWidth: 165, valueGetter: params => `${params.data?.afe_code ?? ''} · ${params.data?.afe_name ?? ''}` },
    { headerName: 'SCOPE', field: 'id', minWidth: 115, maxWidth: 130, valueGetter: params => params.data ? rowScope(params.data) : '', cellRenderer: (params: ICellRendererParams<DailyCostEntry>) => <Box display="flex" alignItems="center" height="100%"><Tag tone="info">{params.value === 'completion' ? 'Completion' : 'Drilling'}</Tag></Box> },
    { headerName: 'ACTUAL DEPTH (m)', field: 'actual_depth', minWidth: 140, valueFormatter: params => formatDepthMeters(params.data?.actual_depth, 'm') },
    { headerName: 'DAILY TOTAL', field: 'total_cost', minWidth: 150, valueFormatter: params => dailyMoney(String(params.value ?? '0'), params.data?.standard_currency) },
    {
      headerName: 'CUMULATIVE TO DATE', field: 'cumulative_cost', minWidth: 175,
      headerTooltip: 'Running actual cost of this well and AFE through and including the sheet date.',
      valueFormatter: params => dailyMoney(String(params.value ?? params.data?.total_cost ?? '0'), params.data?.standard_currency),
    },
    { headerName: 'USD TOTAL', field: 'total_cost_usd', minWidth: 150, valueFormatter: params => dailyMoney(String(params.value ?? params.data?.total_cost ?? '0'), 'USD') },
    {
      headerName: 'OTHER EXPENSES', field: 'other_expenses_total', minWidth: 160,
      cellRenderer: (params: ICellRendererParams<DailyCostEntry>) => {
        const row = params.data
        if (!row) return null
        if (!Number(row.other_expenses_total)) return <Typography fontSize={12} color="text.secondary">—</Typography>
        return <Typography fontSize={12} fontWeight={700} color="warning.main" title={`${row.other_expenses_count} line(s) deducted from the AFE total`}>
          − {dailyMoney(row.other_expenses_total, row.standard_currency)}
        </Typography>
      },
    },
    { headerName: 'LINES', field: 'services_count', minWidth: 105, valueGetter: params => {
      const row = params.data
      return row ? row.services_count + row.consumables_count + row.tangibles_count + row.other_expenses_count : 0
    } },
    { headerName: 'UPA / NPT', field: 'upa_total', minWidth: 160, valueGetter: params => params.data
      ? `${dailyMoney(params.data.upa_total, params.data.standard_currency)} / ${dailyMoney(params.data.npt_total, params.data.standard_currency)}` : '—' },
    { headerName: 'STATUS', field: 'status', minWidth: 120, cellRenderer: (params: ICellRendererParams<DailyCostEntry>) => <Tag tone={params.value === 'submitted' ? 'success' : 'info'}>{DAILY_COST_STATUSES[params.value as 'draft' | 'submitted'] ?? String(params.value ?? '')}</Tag> },
    { headerName: 'ACTIONS', field: 'id', minWidth: deletedView ? 205 : 170, width: deletedView ? 215 : 180, sortable: false,
      cellRenderer: (params: ICellRendererParams<DailyCostEntry>) => {
        const record = params.data
        if (!record) return null
        return <Box display="flex" alignItems="center" height="100%" gap={.35}>
          <Button size="small" component={RouterLink} to={`/daily-cost/entries/${record.id}`} onClick={() => rememberRowScope(record)}>Open</Button>
          {deletedView ? <>
            {can('daily-cost:restore') && <Button size="small" onClick={() => { setActionError(''); setPending({ kind: 'restore', rows: [record] }) }}>Restore</Button>}
            {can('daily-cost:permanent-delete') && <Button size="small" color="error" aria-label={`Permanently delete ${record.daily_cost_code}`} onClick={() => { setActionError(''); setPending({ kind: 'purge', rows: [record] }) }}><DeleteForeverOutlined sx={{ fontSize: 17 }}/></Button>}
          </> : can('daily-cost:delete') && record.status === 'draft' && <Button size="small" color="error" aria-label={`Move ${record.daily_cost_code} to Deleted Entries`} onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: [record] }) }}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></Button>}
        </Box>
      } },
  ], [can, deletedView, reference, rememberRowScope])

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
          to={scopeWellId ? `/daily-cost/analysis/${scopeWellId}` : filterWell ? `/daily-cost/analysis/${filterWell}` : '/daily-cost/analysis'}
        >Well cost analysis</Button>}
        {!deletedView && can('daily-cost:export') && <Button variant="outlined" startIcon={<PrintOutlined/>} onClick={() => setPrintOpen(true)}>Print well costing sheet</Button>}
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</Button>
        {deletedView
          ? <Button variant="outlined" startIcon={<EventNoteOutlined/>} onClick={() => { setParams({}); setNotice('') }}>Active register</Button>
          : can('daily-cost:read') && <Button variant="outlined" startIcon={<RestoreRounded/>} onClick={() => { setParams({ view: 'deleted' }); setNotice('') }}>Deleted entries</Button>}
        {!deletedView && can('daily-cost:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate} disabled={!wells.length || !reference?.afes.length}>New daily sheet</Button>}
      </Box>}
    />

    {!deletedView && <Paper variant="outlined" data-testid="daily-cost-working-scope" sx={{ p: 1.6, borderRadius: 2, mb: 1.8 }}>
      <Box display="flex" gap={1.4} flexWrap="wrap" alignItems="flex-end">
        <Box flex="1 1 260px" minWidth={230}>
          <Typography fontWeight={800} fontSize={13}>Working scope · rig and well</Typography>
          <Typography color="text.secondary" fontSize={11} mt={.25}>
            The rig and well you are costing. New daily sheets and the shortcuts below load with this
            scope; change it here or on the register you open.
          </Typography>
        </Box>
        <TextField select size="small" label="Rig" value={scopeRigId} onChange={event => chooseScopeRig(event.target.value)}
          helperText="Current rig" sx={{ minWidth: 200 }} disabled={!scopeRigs.length}>
          {!scopeRigs.length && <MenuItem value="">No rig</MenuItem>}
          {scopeRigs.map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Well" value={scopeWellId} onChange={event => chooseScopeWell(event.target.value)}
          helperText="Current well" sx={{ minWidth: 250 }} disabled={!scopeWellOptions.length}>
          {!scopeWellOptions.length && <MenuItem value="">No well</MenuItem>}
          {scopeWellOptions.map(well => <MenuItem key={well.id} value={well.id}>{well.well_code} · {well.well_name}</MenuItem>)}
        </TextField>
      </Box>
      <Divider sx={{ my: 1.3 }} />
      <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
        <Typography fontSize={10.5} fontWeight={800} letterSpacing={.7} color="text.secondary" mr={.5}>SHORTCUTS</Typography>
        {SCOPED_REGISTERS.map(register => <Button
          key={register.path} size="small" variant="outlined"
          component={RouterLink} to={scopeLink(register.path, scopeLinks)}
          startIcon={<register.icon sx={{ fontSize: 18 }}/>}
        >{register.label}</Button>)}
        <Typography fontSize={11} color="text.secondary">
          Open on {scopeRig?.display_name ?? 'the selected rig'} · {scopeWell ? `${scopeWell.well_code} · ${scopeWell.well_name}` : 'the selected well'}.
          Change the rig or well there at any time.
        </Typography>
      </Box>
    </Paper>}

    {!deletedView && <Box borderBottom={1} borderColor="divider" mb={2}>
      <Tabs value={active} onChange={(_event, value: CostTab) => setParams(value === 'register' ? {} : { tab: value })} aria-label="Daily cost tabs">
        {TABS.map(tab => <Tab key={tab.key} value={tab.key} label={tab.label} id={`daily-cost-tab-${tab.key}`} aria-controls={`daily-cost-panel-${tab.key}`} />)}
      </Tabs>
    </Box>}

    <Box
      role={deletedView ? undefined : 'tabpanel'}
      id={deletedView ? 'daily-cost-deleted-panel' : `daily-cost-panel-${active}`}
      aria-labelledby={deletedView ? undefined : `daily-cost-tab-${active}`}
    >
      <ErrorMessage message={loadError} />
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}

      {!deletedView && <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2, mb: 1.8 }}>
        <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', lg: '1.3fr 1.3fr .8fr .8fr .8fr auto' } }} alignItems="center">
          <TextField select label="Filter by well" value={filterWell} onChange={event => {
            const next = event.target.value
            setFilterWell(next)
            setFilterAfe('')
          }} helperText="Narrows this register list only">
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
          <TextField type="date" label="Cost date from" value={dateFrom} onChange={event => setDateFrom(event.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField type="date" label="to" value={dateTo} onChange={event => setDateTo(event.target.value)} InputLabelProps={{ shrink: true }} />
          <Button variant="outlined" startIcon={<FilterAltOffOutlined/>} onClick={() => {
            setFilterWell(''); setFilterAfe(''); setFilterStatus(''); setDateFrom(''); setDateTo('')
          }} disabled={!filtersActive}>Clear</Button>
        </Box>
        {filtersActive && <Alert severity="info" sx={{ mt: 1.3, py: .4 }}>
          Showing {tabRows.length} daily sheet{tabRows.length === 1 ? '' : 's'} for the selected filters.
          {dateFrom && dateTo && dateFrom > dateTo ? ' The start date is after the end date, so no sheet can match.' : ''}
        </Alert>}
      </Paper>}

      {loading && !rows.length ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26} /></Box> : <>
        {selected.length > 0 && <Paper variant="outlined" sx={{ p: 1.4, borderRadius: 2, mb: 1.5, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          <Typography fontSize={12} fontWeight={700} mr="auto">{selected.length} sheet{selected.length === 1 ? '' : 's'} selected</Typography>
          {!deletedView && can('daily-cost:export') && <Button
            size="small" variant="contained" startIcon={<PrintOutlined/>}
            onClick={() => setBulkPrintOpen(true)}
          >Print selected first pages</Button>}
          {deletedView ? <>
            {can('daily-cost:restore') && <Button size="small" startIcon={<RestoreRounded/>} onClick={() => { setActionError(''); setPending({ kind: 'restore', rows: selected }) }}>Restore selected</Button>}
            {can('daily-cost:permanent-delete') && <Button size="small" color="error" startIcon={<DeleteForeverOutlined/>} onClick={() => { setActionError(''); setPending({ kind: 'purge', rows: selected }) }}>Delete permanently</Button>}
          </> : can('daily-cost:delete') && <>
            {selected.some(row => row.status !== 'draft') && <Typography fontSize={11} color="warning.dark">Submitted sheets must be reopened before deleting.</Typography>}
            <Button size="small" color="error" startIcon={<DeleteOutlineRounded/>} disabled={selected.some(row => row.status !== 'draft')} onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: selected }) }}>Move to Deleted Entries</Button>
          </>}
        </Paper>}
        <DataTable
          fillHeight
          fillReserve={!loading && tabRows.length === 0 ? 40 : 0}
          rows={tabRows}
          columns={columns}
          rowKey="id"
          searchPlaceholder={deletedView ? 'Search deleted sheets by date, well, AFE or code…' : 'Search sheets by date, well, AFE, amount or status…'}
          exportName={deletedView ? 'daily-cost-deleted' : `daily-cost-${active}`}
          canExport={can('daily-cost:export')}
          onExport={can('daily-cost:export') ? exportAudit : undefined}
          selectable={deletedView
            ? can('daily-cost:restore') || can('daily-cost:permanent-delete')
            : can('daily-cost:delete') || can('daily-cost:export')}
          onSelectionChange={setSelected}
        />
        {!loading && tabRows.length === 0 && <Typography color="text.secondary" fontSize={12} mt={1.2}>
          {deletedView ? 'There are no deleted daily sheets.' : 'No daily sheets yet. Start from a saved AFE estimate on a configured well.'}
        </Typography>}
      </>}
    </Box>

    <WellCostPrintDialog open={printOpen} onClose={() => setPrintOpen(false)} wells={reference?.wells ?? []} initialWellId={filterWell} />
    <BulkDailyCostPrintDialog
      open={bulkPrintOpen} onClose={() => setBulkPrintOpen(false)}
      entries={selected} wells={reference?.wells ?? []}
    />

    <FormDialog open={createOpen} title="Start a daily cost sheet" subtitle="The first sheet locks the AFE estimate, FX factors, well plan, service rates and Master Data catalogue prices for this well/AFE." onClose={() => setCreateOpen(false)} onSubmit={() => void createEntry()} busy={creating} submitLabel="Create daily sheet" submitDisabled={!selectedAfe || !selectedWell || !createDateValid || !usdRateValid || Boolean(selectedDuplicate) || missingSubActivities}>
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
        {missingSubActivities && <Alert severity="warning" sx={{ py: 0 }} action={<Button component={RouterLink} to={selectedWell ? `/rig-well/sub-activities?rig_id=${encodeURIComponent(selectedWell.rig_id)}&well_id=${encodeURIComponent(selectedWell.id)}&scope=${selectedScope}` : '/rig-well/sub-activities'} size="small" color="inherit" onClick={() => setCreateOpen(false)}>Open well sub activities</Button>}>
          Configuring the well sub activity for this well scope ({selectedScope}) in Rig &amp; Well Management is mandatory for daily cost entry. Add the scope's sub activities first — every cost line is recorded under an Activity and Sub activity.
        </Alert>}
        <TextField select required label="Saved AFE estimate" value={afeId} onChange={event => setAfeId(event.target.value)} disabled={!afes.length}>
          {afes.map(afe => <MenuItem key={afe.id} value={afe.id}>{afe.display_name}</MenuItem>)}
        </TextField>
        {selectedAfe && <Alert severity="info" sx={{ py: 0 }}>AFE status: {selectedAfe.status}. Budget baseline: {dailyMoney(selectedAfe.total_cost, selectedAfe.standard_currency)}. Subsequent estimate or Master Data changes will not rewrite this locked baseline.</Alert>}
        {needsUsdExchangeRate && selectedAfe && (
          <TextField
            required
            type="number"
            label={`USD conversion rate (1 ${selectedAfe.standard_currency.toUpperCase()} = ? USD)`}
            value={usdExchangeRate}
            onChange={event => { setUsdExchangeRate(event.target.value); setCreateError('') }}
            inputProps={{ min: 0.000001, step: 'any' }}
            error={Boolean(usdExchangeRate) && !usdRateValid}
            helperText={`USD is the standard currency across all wells. Enter the conversion rate for ${selectedAfe.standard_currency.toUpperCase()} to calculate USD values automatically.`}
          />
        )}
        {selectedDuplicate && <Alert severity="warning" sx={{ py: 0 }} action={<Button component={RouterLink} to={`/daily-cost/entries/${selectedDuplicate.id}`} size="small" color="inherit" onClick={() => setCreateOpen(false)}>Open existing</Button>}>
          A sheet already exists for this well, AFE and date. Open it to review or continue editing instead of creating a duplicate.
        </Alert>}
        <TextField required type="date" label="Cost date" value={costDate} onChange={event => { setCostDate(event.target.value); setCreateError('') }} error={Boolean(costDate) && !createDateValid} helperText={Boolean(costDate) && !createDateValid ? 'Enter a real calendar date.' : 'Each well + AFE + date can have one sheet.'} InputLabelProps={{ shrink: true }} />
        <TextField label="Shift / day remarks" value={remarks} onChange={event => setRemarks(event.target.value)} multiline minRows={2} inputProps={{ maxLength: 1000 }} />
        <ErrorMessage message={createError} />
      </Box>
    </FormDialog>

    <FormDialog open={Boolean(pending)} title={actionTitle ?? 'Confirm action'} subtitle={actionSubtitle} onClose={() => { if (!actionBusy) setPending(null) }} onSubmit={() => void act()} busy={actionBusy} submitLabel={pending?.kind === 'purge' ? 'Delete permanently' : pending?.kind === 'restore' ? 'Restore' : 'Move to Deleted Entries'} danger={pending?.kind === 'purge'}>
      <Box display="grid" gap={1.2}>
        {pending?.kind === 'purge' && <Alert severity="warning">Permanent deletion cannot be undone. The locked AFE budget and well rate snapshots are kept for audit until the AFE or well itself is permanently deleted from its Deleted Entries.</Alert>}
        <ErrorMessage message={actionError} />
      </Box>
    </FormDialog>
  </>
}

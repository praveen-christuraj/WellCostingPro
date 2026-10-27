import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import {
  AddRounded, CalculateOutlined, DeleteForeverOutlined, DeleteOutlineRounded, DownloadRounded, EventNoteOutlined,
  PrintOutlined, RefreshRounded, RestoreRounded, SettingsOutlined, WaterDropOutlined,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, Menu, MenuItem, Paper, Tab, Tabs, TextField, Typography,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { MudCostEntryDialog, type MudCostEditorPayload } from '../components/mud-cost/MudCostEntryDialog'
import { MudCostOpeningStockDialog } from '../components/mud-cost/MudCostOpeningStockDialog'
import { MudCostKpis, MudCostReconciliationRateKpi, type MudCostKpiSnapshot } from '../components/mud-cost/MudCostKpis'
import { MudCostSectionSettingsDialog } from '../components/mud-cost/MudCostSectionSettingsDialog'
import { useMudCostPrint } from '../components/mud-cost/MudCostPrintSheet'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { readActiveScope, requestedScope, resolveRequestedScope, writeActiveScope } from '../lib/activeScope'
import { exportCsv, exportXlsx, type ExportColumn } from '../lib/export'
import { dailyMoney } from '../lib/dailyCost'
import { radius, space } from '../designSystem'
import {
  MUD_COST_BALANCE_VIEWS, MUD_COST_IMPORT_HEADERS, MUD_COST_IMPORT_OPTIONAL_HEADERS, MUD_COST_LINE_SPECS,
  MUD_COST_IMPORT_SAMPLE, mudQuantity,
  type MudCostBalanceRow, type MudCostBalanceView, type MudCostEntry, type MudCostExportPayload,
  type MudCostMaterialBalance, type MudCostReconciliation,
  type MudCostReconciliationRow, type MudCostReconciliationSection, type MudCostReference,
  type MudCostSectionSetting, type MudCostSectionSettingPayload,
} from '../lib/mudCost'

const ALL_SECTIONS = '__all_sections__'

type PendingAction = { kind: 'delete' | 'restore' | 'purge'; rows: MudCostEntry[] }

function dateLabel(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(`${value}T00:00:00`)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString()
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: `${space[4]}px`, borderRadius: `${radius.lg}px`, minWidth: 0 }}>
    <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={0.7} textTransform="uppercase">{label}</Typography>
    <Typography className="stat-value" sx={{ fontSize: 22, my: 0.7, overflowWrap: 'anywhere' }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
  </Paper>
}

export default function MudCostAnalysis() {
  const { can, user } = useAuth()
  const { print, printSheet } = useMudCostPrint()
  const [searchParams] = useSearchParams()
  // The scope a daily cost register shortcut carried. The scope remembered from the
  // last register visit is read once the workspace is known (see below).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const linkedScope = useMemo(() => requestedScope(searchParams), [])
  const [reference, setReference] = useState<MudCostReference | null>(null)
  const [referenceLoading, setReferenceLoading] = useState(true)
  const [referenceError, setReferenceError] = useState('')
  const [rigId, setRigId] = useState(linkedScope.rigId)
  const [wellId, setWellId] = useState(linkedScope.wellId)
  const [entrySectionId, setEntrySectionId] = useState('')
  const [balanceSectionId, setBalanceSectionId] = useState(ALL_SECTIONS)
  const [tab, setTab] = useState(0)
  const [deletedView, setDeletedView] = useState(false)
  const [entries, setEntries] = useState<MudCostEntry[]>([])
  const [existingRows, setExistingRows] = useState<MudCostEntry[]>([])
  const [entriesLoading, setEntriesLoading] = useState(false)
  const [entriesError, setEntriesError] = useState('')
  const [balance, setBalance] = useState<MudCostMaterialBalance | null>(null)
  const [balanceLoading, setBalanceLoading] = useState(false)
  const [balanceError, setBalanceError] = useState('')
  const [balanceView, setBalanceView] = useState<MudCostBalanceView>('daily')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [settings, setSettings] = useState<MudCostSectionSetting[]>([])
  const [settingsLoading, setSettingsLoading] = useState(false)
  const [settingsError, setSettingsError] = useState('')
  const [configRow, setConfigRow] = useState<MudCostSectionSetting | null>(null)
  const [reconciliation, setReconciliation] = useState<MudCostReconciliation | null>(null)
  const [kpiSnapshot, setKpiSnapshot] = useState<MudCostKpiSnapshot | null>(null)
  const [kpiLoading, setKpiLoading] = useState(false)
  const [reconLoading, setReconLoading] = useState(false)
  const [reconError, setReconError] = useState('')
  const [reconSectionId, setReconSectionId] = useState(ALL_SECTIONS)
  const [reconDateFrom, setReconDateFrom] = useState('')
  const [reconDateTo, setReconDateTo] = useState('')
  const [reconView, setReconView] = useState<'daily' | 'section'>('daily')
  const [notice, setNotice] = useState('')
  const [selectedRows, setSelectedRows] = useState<MudCostEntry[]>([])
  const [selectionResetKey, setSelectionResetKey] = useState(0)
  const [entryDialogOpen, setEntryDialogOpen] = useState(false)
  const [openingStockEntry, setOpeningStockEntry] = useState<MudCostEntry | null>(null)
  const [editingEntry, setEditingEntry] = useState<MudCostEntry | null>(null)
  const [entryError, setEntryError] = useState('')
  const [savingEntry, setSavingEntry] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [detailedExportAnchor, setDetailedExportAnchor] = useState<HTMLElement | null>(null)
  const [detailedExportError, setDetailedExportError] = useState('')
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const entriesRequest = useRef(0)
  const balanceRequest = useRef(0)
  const reconciliationRequest = useRef(0)
  const settingsRequest = useRef(0)
  const kpiRequest = useRef(0)
  const kpiScope = useRef({ rigId, wellId })
  kpiScope.current = { rigId, wellId }

  const loadReference = useCallback(async () => {
    setReferenceLoading(true)
    setReferenceError('')
    try {
      setReference(await api<MudCostReference>('/mud-cost/reference'))
    } catch (caught) {
      setReferenceError(caught instanceof Error ? caught.message : 'Rig, well and section scope could not be loaded')
    } finally {
      setReferenceLoading(false)
    }
  }, [])

  useEffect(() => { void loadReference() }, [loadReference])

  const rigOptions = reference?.rigs ?? []
  const wellOptions = useMemo(
    () => reference?.wells.filter(well => well.rig_id === rigId) ?? [],
    [reference, rigId],
  )
  const selectedRig = rigOptions.find(rig => rig.id === rigId) ?? null
  const selectedWell = wellOptions.find(well => well.id === wellId) ?? null
  const sectionOptions = selectedWell?.sections ?? []
  const entrySection = sectionOptions.find(section => section.id === entrySectionId) ?? null
  const balanceSection = sectionOptions.find(section => section.id === balanceSectionId) ?? null

  // Apply the scope the page was opened with (link first, then the remembered one)
  // before the fallback defaults run, so a requested well also selects its rig.
  // The defaults wait for `scopeReady` so they can never overwrite that choice.
  const [scopeReady, setScopeReady] = useState(false)
  useEffect(() => {
    if (!reference || !user || scopeReady) return
    const remembered = readActiveScope(user.organization_slug)
    const next = resolveRequestedScope(
      { rigId: rigId || remembered.rigId, wellId: wellId || remembered.wellId }, reference.wells, reference.rigs,
    )
    if (next.wellId) {
      setRigId(next.rigId)
      setWellId(next.wellId)
    } else if (next.rigId) setRigId(next.rigId)
    setScopeReady(true)
  }, [reference, user, scopeReady, rigId, wellId])

  useEffect(() => {
    if (!reference || !scopeReady) return
    if (!rigId || !rigOptions.some(rig => rig.id === rigId)) {
      setRigId(rigOptions.find(rig => !rig.is_deleted)?.id ?? rigOptions[0]?.id ?? '')
    }
  }, [reference, scopeReady, rigId, rigOptions])

  useEffect(() => {
    if (!reference || !scopeReady) return
    if (!rigId) {
      setWellId('')
      return
    }
    if (!wellOptions.some(well => well.id === wellId)) {
      setWellId(wellOptions.find(well => !well.is_deleted)?.id ?? wellOptions[0]?.id ?? '')
    }
  }, [reference, scopeReady, rigId, wellId, wellOptions])

  // The scope chosen here becomes the current scope everywhere in Daily Cost Management.
  useEffect(() => {
    if (rigId && wellId && user) writeActiveScope({ rigId, wellId }, user.organization_slug)
  }, [rigId, wellId, user])

  useEffect(() => {
    if (!selectedWell?.sections.length) {
      setEntrySectionId('')
      return
    }
    if (entrySectionId === ALL_SECTIONS) return
    if (!selectedWell.sections.some(section => section.id === entrySectionId)) {
      setEntrySectionId(selectedWell.sections.find(section => section.is_current)?.id ?? selectedWell.sections[0].id)
    }
  }, [selectedWell, entrySectionId])

  const loadEntries = useCallback(async () => {
    const version = ++entriesRequest.current
    setEntriesError('')
    setSelectedRows([])
    setSelectionResetKey(key => key + 1)
    if (!rigId || !wellId) {
      setEntries([])
      setExistingRows([])
      setEntriesLoading(false)
      return
    }
    setEntriesLoading(true)
    setEntries([])
    setExistingRows([])
    const params = new URLSearchParams({ rig_id: rigId, well_id: wellId })
    try {
      if (deletedView) {
        const deleted = await api<MudCostEntry[]>(`/mud-cost/entries/deleted?${params}`)
        if (version === entriesRequest.current) {
          setEntries(deleted)
          setExistingRows(deleted)
        }
      } else {
        const [active, deleted] = await Promise.all([
          api<MudCostEntry[]>(`/mud-cost/entries?${params}`),
          api<MudCostEntry[]>(`/mud-cost/entries/deleted?${params}`),
        ])
        if (version === entriesRequest.current) {
          setEntries(active)
          setExistingRows([...active, ...deleted])
        }
      }
    } catch (caught) {
      if (version !== entriesRequest.current) return
      setEntriesError(caught instanceof Error ? caught.message : 'Mud Cost entries could not be loaded')
    } finally {
      if (version === entriesRequest.current) setEntriesLoading(false)
    }
  }, [rigId, wellId, deletedView])

  const loadBalance = useCallback(async () => {
    const version = ++balanceRequest.current
    setBalanceError('')
    setBalance(null)
    if (!rigId || !wellId) {
      setBalanceLoading(false)
      return
    }
    if (balanceView !== 'inception' && dateFrom && dateTo && dateFrom > dateTo) {
      setBalanceError('The start date must not be after the end date.')
      setBalanceLoading(false)
      return
    }
    setBalanceLoading(true)
    const params = new URLSearchParams({ rig_id: rigId, well_id: wellId, view: balanceView })
    if (balanceSectionId !== ALL_SECTIONS) params.set('section_id', balanceSectionId)
    if (balanceView !== 'inception' && dateFrom) params.set('from', dateFrom)
    if (dateTo) params.set('to', dateTo)
    try {
      const result = await api<MudCostMaterialBalance>(`/mud-cost/material-balance?${params}`)
      if (version === balanceRequest.current) setBalance(result)
    } catch (caught) {
      if (version !== balanceRequest.current) return
      setBalanceError(caught instanceof Error ? caught.message : 'Material Balance could not be loaded')
    } finally {
      if (version === balanceRequest.current) setBalanceLoading(false)
    }
  }, [rigId, wellId, balanceSectionId, balanceView, dateFrom, dateTo])

  const loadSettings = useCallback(async () => {
    const version = ++settingsRequest.current
    setSettingsError('')
    if (!rigId || !wellId) {
      setSettings([])
      setSettingsLoading(false)
      return
    }
    setSettingsLoading(true)
    const params = new URLSearchParams({ rig_id: rigId, well_id: wellId })
    try {
      const result = await api<MudCostSectionSetting[]>(`/mud-cost/section-settings?${params}`)
      if (version === settingsRequest.current) setSettings(result)
    } catch (caught) {
      if (version !== settingsRequest.current) return
      setSettingsError(caught instanceof Error ? caught.message : 'Mud type configuration could not be loaded')
    } finally {
      if (version === settingsRequest.current) setSettingsLoading(false)
    }
  }, [rigId, wellId])

  const loadReconciliation = useCallback(async () => {
    const version = ++reconciliationRequest.current
    setReconError('')
    setReconciliation(null)
    if (!rigId || !wellId) {
      setReconLoading(false)
      return
    }
    if (reconDateFrom && reconDateTo && reconDateFrom > reconDateTo) {
      setReconError('The start date must not be after the end date.')
      setReconLoading(false)
      return
    }
    setReconLoading(true)
    const params = new URLSearchParams({ rig_id: rigId, well_id: wellId, include_draft: 'true' })
    if (reconSectionId !== ALL_SECTIONS) params.set('section_id', reconSectionId)
    if (reconDateFrom) params.set('from', reconDateFrom)
    if (reconDateTo) params.set('to', reconDateTo)
    try {
      const result = await api<MudCostReconciliation>(`/mud-cost/reconciliation?${params}`)
      if (version === reconciliationRequest.current) setReconciliation(result)
    } catch (caught) {
      if (version !== reconciliationRequest.current) return
      setReconError(caught instanceof Error ? caught.message : 'Mud cost reconciliation could not be calculated')
    } finally {
      if (version === reconciliationRequest.current) setReconLoading(false)
    }
  }, [rigId, wellId, reconSectionId, reconDateFrom, reconDateTo])

  // KPIs always cover the entire well, irrespective of the tab-level filters.
  // The inception balance is server-aggregated (first opening, summed movements,
  // latest closing). Reconciliation normally defaults to today; request the last
  // supported date here so its latest rate covers all saved dates just like the
  // latest-closing KPI, including future-dated records.
  const loadKpis = useCallback(async () => {
    if (kpiScope.current.rigId !== rigId || kpiScope.current.wellId !== wellId) return
    const version = ++kpiRequest.current
    setKpiSnapshot(null)
    if (!rigId || !wellId) {
      setKpiLoading(false)
      return
    }
    setKpiLoading(true)
    const balanceParams = new URLSearchParams({ rig_id: rigId, well_id: wellId, view: 'inception' })
    const reconParams = new URLSearchParams({ rig_id: rigId, well_id: wellId, include_draft: 'true', to: '9999-12-31' })
    const [balanceResult, reconResult] = await Promise.allSettled([
      api<MudCostMaterialBalance>(`/mud-cost/material-balance?${balanceParams}`),
      api<MudCostReconciliation>(`/mud-cost/reconciliation?${reconParams}`),
    ])
    if (version !== kpiRequest.current || kpiScope.current.rigId !== rigId || kpiScope.current.wellId !== wellId) return
    setKpiSnapshot({
      rigId, wellId,
      balance: balanceResult.status === 'fulfilled' ? balanceResult.value : null,
      reconciliation: reconResult.status === 'fulfilled' ? reconResult.value : null,
      balanceError: balanceResult.status === 'rejected' ? (balanceResult.reason instanceof Error ? balanceResult.reason.message : 'Material balance could not be loaded') : '',
      reconciliationError: reconResult.status === 'rejected' ? (reconResult.reason instanceof Error ? reconResult.reason.message : 'Reconciliation could not be calculated') : '',
    })
    setKpiLoading(false)
  }, [rigId, wellId])

  useEffect(() => { void loadEntries() }, [loadEntries])
  useEffect(() => { void loadBalance() }, [loadBalance])
  useEffect(() => { void loadSettings() }, [loadSettings])
  useEffect(() => { void loadReconciliation() }, [loadReconciliation])
  useEffect(() => { void loadKpis() }, [loadKpis])

  const activeEntries = useMemo(() => entries
    .filter(entry => entry.rig_id === rigId && entry.well_id === wellId && !entry.is_deleted)
    .sort((a, b) => b.entry_date.localeCompare(a.entry_date)), [entries, rigId, wellId])
  const initialEntryIds = useMemo(() => {
    const firstBySection = new Map<string, MudCostEntry>()
    for (const entry of activeEntries) {
      const current = firstBySection.get(entry.section_id)
      if (!current || entry.entry_date < current.entry_date || (entry.entry_date === current.entry_date && entry.id < current.id)) {
        firstBySection.set(entry.section_id, entry)
      }
    }
    return new Set([...firstBySection.values()].map(entry => entry.id))
  }, [activeEntries])
  const tableRows = useMemo(() => entries
    .filter(entry => entry.rig_id === rigId && entry.well_id === wellId
      && (entrySectionId === ALL_SECTIONS || !entrySectionId || entry.section_id === entrySectionId))
    .sort((a, b) => b.entry_date.localeCompare(a.entry_date)), [entries, rigId, wellId, entrySectionId])
  const hasScope = Boolean(selectedRig && selectedWell)
  const canCreateHere = Boolean(hasScope && selectedRig && !selectedRig.is_deleted && selectedWell && !selectedWell.is_deleted && entrySection?.is_current)
  const invalidBalanceDates = balanceView !== 'inception' && dateFrom && dateTo && dateFrom > dateTo
  const currentSettings = settings.filter(row => row.is_current)
  const unconfiguredSettings = currentSettings.filter(row => !row.is_configured)
  // Never render a prior well's figures during a scope change, before effects run.
  const scopedKpis = kpiSnapshot?.rigId === rigId && kpiSnapshot.wellId === wellId ? kpiSnapshot : null
  const scopedSettings = settings.filter(row => row.rig_id === rigId && row.well_id === wellId)

  const saveConfig = async (payload: MudCostSectionSettingPayload) => {
    const saved = await api<MudCostSectionSetting>('/mud-cost/section-settings', { method: 'PUT', body: body(payload) })
    setSettings(rows => rows.map(row => row.section_id === saved.section_id ? saved : row))
    setNotice(`Mud type for ${saved.section_label} was saved.`)
    setConfigRow(null)
    await Promise.all([loadSettings(), loadReconciliation(), loadKpis()])
  }

  const auditExport = useCallback(async (payload: MudCostExportPayload) => {
    await api('/mud-cost/export-audit', { method: 'POST', body: body(payload) })
  }, [])

  const entryColumns = useMemo<ColDef<MudCostEntry>[]>(() => [
    { headerName: 'ENTRY DATE', field: 'entry_date', minWidth: 125, valueFormatter: params => dateLabel(String(params.value ?? '')) },
    { headerName: 'SECTION', field: 'section_label', minWidth: 245, flex: 1.2 },
    { headerName: 'OPENING STOCK', field: 'opening_stock', minWidth: 145, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'RECEIPT', field: 'receipt', minWidth: 120, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'ADDITIONS', field: 'additions', minWidth: 125, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'CONSUMPTION / LOSSES', field: 'consumption_losses', minWidth: 175, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'OTHERS', field: 'others', minWidth: 110, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'CLOSING STOCK', field: 'closing_stock', minWidth: 145, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    {
      headerName: 'ACTIONS', field: 'id', minWidth: deletedView ? 210 : 310, width: deletedView ? 220 : 330, sortable: false,
      cellRenderer: (params: ICellRendererParams<MudCostEntry>) => {
        const record = params.data
        if (!record) return null
        return <Box display="flex" alignItems="center" height="100%" gap={0.25}>
          {deletedView ? <>
            {can('daily-cost:restore') && <Button size="small" onClick={() => { setActionError(''); setPendingAction({ kind: 'restore', rows: [record] }) }}>Restore</Button>}
            {can('daily-cost:permanent-delete') && <Button size="small" color="error" aria-label={`Permanently delete Mud Cost entry ${record.entry_date}`} onClick={() => { setActionError(''); setPendingAction({ kind: 'purge', rows: [record] }) }}><DeleteForeverOutlined sx={{ fontSize: 17 }}/></Button>}
          </> : <>
            {can('mud-cost:opening-stock-update') && initialEntryIds.has(record.id) && <Button size="small" onClick={() => setOpeningStockEntry(record)}>Edit opening stock</Button>}
            {can('daily-cost:update') && <Button size="small" onClick={() => { setEditingEntry(record); setEntryError(''); setEntryDialogOpen(true) }}>Edit</Button>}
            {can('daily-cost:delete') && <Button size="small" color="error" aria-label={`Move Mud Cost entry ${record.entry_date} to Deleted Entries`} onClick={() => { setActionError(''); setPendingAction({ kind: 'delete', rows: [record] }) }}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></Button>}
          </>}
        </Box>
      },
    },
  ], [can, deletedView, initialEntryIds])

  const detailedExportColumns = useMemo<ExportColumn<MudCostEntry>[]>(() => [
    { header: 'entry_date', value: row => row.entry_date },
    ...MUD_COST_LINE_SPECS.flatMap(spec => [
      { header: spec.code, value: (row: MudCostEntry) => row.lines.find(line => line.line_code === spec.code)?.amount ?? '0' },
      { header: `${spec.code}_remarks`, value: (row: MudCostEntry) => row.lines.find(line => line.line_code === spec.code)?.remarks ?? '' },
    ]),
  ], [])

  const balanceColumns = useMemo<ColDef<MudCostBalanceRow>[]>(() => [
    {
      headerName: 'DATE / PERIOD', field: 'cost_date', minWidth: 170,
      valueFormatter: params => params.data?.period_label ?? dateLabel(String(params.value ?? '')),
    },
    { headerName: 'SECTION', field: 'section_label', minWidth: 245, flex: 1.15 },
    { headerName: 'OPENING STOCK', field: 'opening_stock', minWidth: 145, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'RECEIPT', field: 'receipt', minWidth: 120, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'ADDITIONS', field: 'additions', minWidth: 125, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'CONSUMPTION / LOSSES', field: 'consumption_losses', minWidth: 175, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'OTHERS', field: 'others', minWidth: 110, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'CLOSING STOCK', field: 'closing_stock', minWidth: 145, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'ENTRY COUNT', field: 'entry_count', minWidth: 110 },
  ], [])

  const mudTypeCell = (params: ICellRendererParams<{ mud_type: string | null; is_configured: boolean }>) => {
    const row = params.data
    if (!row) return null
    return <Box display="flex" alignItems="center" height="100%">
      <Tag tone={row.is_configured ? 'info' : 'warning'}>{row.mud_type ?? 'Not configured'}</Tag>
    </Box>
  }

  const reconciliationColumns = useMemo<ColDef<MudCostReconciliationRow>[]>(() => [
    { headerName: 'DATE', field: 'cost_date', minWidth: 118, width: 128, valueFormatter: params => dateLabel(String(params.value ?? '')) },
    { headerName: 'SECTION', field: 'section_label', minWidth: 250, flex: 1.1 },
    { headerName: 'MUD TYPE', field: 'mud_type', minWidth: 130, cellRenderer: mudTypeCell },
    { headerName: 'ADDITIONS', field: 'additions', minWidth: 120, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'INITIAL OPENING STOCK', field: 'opening_stock', minWidth: 185, headerTooltip: 'Initial inventory for this section and its configured mud type; included once in ALPHA', valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'EXTRA OBM RECEIVED', field: 'extra_obm_received', minWidth: 170, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'ACTUAL MUD COST', field: 'actual_cost', minWidth: 155, valueFormatter: params => dailyMoney(String(params.value ?? '0'), reconciliation?.currency ?? '') },
    { headerName: 'TOTAL MUD (CUM.)', field: 'total_mud', minWidth: 150, headerTooltip: 'Opening Stock + Extra OBM received + Additions, cumulative to this date', valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'ALPHA', field: 'alpha', minWidth: 130, headerTooltip: '(Opening Stock + Extra OBM received) × Cost/BBL base rate', valueFormatter: params => params.value == null ? '—' : dailyMoney(String(params.value), reconciliation?.currency ?? '') },
    { headerName: 'BETA', field: 'beta', minWidth: 135, headerTooltip: 'ALPHA + actual mud chemicals cost (section & mud type scoped)', valueFormatter: params => params.value == null ? '—' : dailyMoney(String(params.value), reconciliation?.currency ?? '') },
    {
      headerName: 'COST / BBL', field: 'cost_per_bbl', minWidth: 140, headerTooltip: 'BETA ÷ Total Mud we have; the latest value drives cumulative reconciliation',
      cellRenderer: (params: ICellRendererParams<MudCostReconciliationRow>) => {
        if (params.value == null) return <Typography fontSize={12} color="text.secondary" sx={{ py: 1.2 }}>—</Typography>
        return <Typography fontSize={12} fontWeight={800}>{dailyMoney(String(params.value), reconciliation?.currency ?? '')}</Typography>
      },
    },
    { headerName: 'CONSUMPTION / LOSSES', field: 'consumption_losses', minWidth: 185, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'RECONCILED COST', field: 'reconciled_cost', minWidth: 155, headerTooltip: 'The day\'s Consumption/Losses × the latest Cost/BBL to that date', valueFormatter: params => params.value == null ? '—' : dailyMoney(String(params.value), reconciliation?.currency ?? '') },
    { headerName: 'CUM. CONSUMPTION', field: 'cumulative_consumption_losses', minWidth: 165, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'CUM. RECONCILED (LATEST)', field: 'cumulative_reconciled_cost', minWidth: 205, headerTooltip: 'Cumulative consumption/losses × the latest Cost/BBL; this is the amount used in Well Cost Analysis', valueFormatter: params => params.value == null ? '—' : dailyMoney(String(params.value), reconciliation?.currency ?? '') },
  ], [reconciliation?.currency])

  const reconciliationSectionColumns = useMemo<ColDef<MudCostReconciliationSection>[]>(() => [
    { headerName: 'SECTION', field: 'section_label', minWidth: 255, flex: 1.1 },
    { headerName: 'MUD TYPE', field: 'mud_type', minWidth: 130, cellRenderer: mudTypeCell },
    // The section's own AFE Mud Chemicals allowance — never the section's whole
    // AFE plan, which also carries its services and other cost groups.
    { headerName: 'PLANNED (AFE)', field: 'planned_cost', minWidth: 155, headerTooltip: 'The section\'s locked AFE mud chemicals allowance', valueFormatter: params => params.value == null ? '—' : dailyMoney(String(params.value), reconciliation?.currency ?? '') },
    { headerName: 'BASE RATE', field: 'base_rate', minWidth: 135, valueFormatter: params => dailyMoney(String(params.value ?? '0'), reconciliation?.currency ?? '') },
    { headerName: 'ADDITIONS', field: 'additions', minWidth: 120, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'INITIAL OPENING STOCK', field: 'opening_stock', minWidth: 185, headerTooltip: 'Initial inventory for this section and its configured mud type; included once in ALPHA', valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'EXTRA OBM RECEIVED', field: 'extra_obm_received', minWidth: 170, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'ACTUAL MUD COST', field: 'actual_cost', minWidth: 155, valueFormatter: params => dailyMoney(String(params.value ?? '0'), reconciliation?.currency ?? '') },
    { headerName: 'TOTAL MUD', field: 'total_mud', minWidth: 135, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'ALPHA', field: 'alpha', minWidth: 130, valueFormatter: params => params.value == null ? '—' : dailyMoney(String(params.value), reconciliation?.currency ?? '') },
    { headerName: 'BETA', field: 'beta', minWidth: 135, valueFormatter: params => params.value == null ? '—' : dailyMoney(String(params.value), reconciliation?.currency ?? '') },
    { headerName: 'COST / BBL (LATEST)', field: 'cost_per_bbl', minWidth: 175, headerTooltip: 'Latest Cost/BBL from the section\'s cumulative figures to the To date; it prices the selected period\'s consumption/losses', valueFormatter: params => params.value == null ? '—' : dailyMoney(String(params.value), reconciliation?.currency ?? '') },
    { headerName: 'CONSUMPTION / LOSSES', field: 'consumption_losses', minWidth: 180, valueFormatter: params => mudQuantity(String(params.value ?? '0')) },
    { headerName: 'RECONCILED COST', field: 'reconciled_cost', minWidth: 155, headerTooltip: 'Selected period Consumption/Losses × the latest Cost/BBL', valueFormatter: params => params.value == null ? '—' : dailyMoney(String(params.value), reconciliation?.currency ?? '') },
    {
      headerName: 'DIFFERENCE', field: 'adjustment', minWidth: 145, headerTooltip: 'Reconciled cost − actual mud chemicals cost for the selected period',
      cellRenderer: (params: ICellRendererParams<MudCostReconciliationSection>) => {
        if (params.value == null) return <Typography fontSize={12} color="text.secondary" sx={{ py: 1.2 }}>—</Typography>
        const value = Number(params.value)
        return <Typography fontSize={12} fontWeight={700} color={value < 0 ? 'error.main' : value > 0 ? 'warning.main' : 'text.secondary'}>{dailyMoney(value, reconciliation?.currency ?? '')}</Typography>
      },
    },
    { headerName: 'REMARKS', field: 'remarks', minWidth: 200, flex: 1 },
  ], [reconciliation?.currency])

  const exportReconciliation = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await auditExport({
      module: 'reconciliation', format, record_count: recordCount,
      rig_id: rigId, well_id: wellId,
      section_id: reconSectionId === ALL_SECTIONS ? '' : reconSectionId,
      view: reconView === 'daily' ? 'daily' : 'section',
      date_from: reconDateFrom || undefined,
      date_to: reconDateTo || undefined,
    })
  }

  const refresh = async () => {
    await Promise.all([loadReference(), loadEntries(), loadBalance(), loadSettings(), loadReconciliation(), loadKpis()])
  }

  const openCreate = () => {
    setEditingEntry(null)
    setEntryError('')
    setEntryDialogOpen(true)
  }

  const saveEntry = async (payload: MudCostEditorPayload) => {
    if (!selectedWell || !selectedRig || (!editingEntry && !entrySection?.is_current)) {
      setEntryError('Select an active rig, well and configured section before saving.')
      return
    }
    setSavingEntry(true)
    setEntryError('')
    try {
      if (editingEntry) {
        await api(`/mud-cost/entries/${editingEntry.id}`, { method: 'PUT', body: body(payload) })
        setNotice(`Mud Cost entry for ${payload.entry_date} was updated.`)
      } else {
        await api('/mud-cost/entries', {
          method: 'POST',
          body: body({
            rig_id: selectedRig.id,
            well_id: selectedWell.id,
            section_id: entrySection?.id ?? '',
            ...payload,
          }),
        })
        setNotice(`Mud Cost entry for ${payload.entry_date} was created.`)
      }
      setEntryDialogOpen(false)
      setEditingEntry(null)
      await Promise.all([loadEntries(), loadBalance(), loadSettings(), loadReconciliation(), loadKpis()])
    } catch (caught) {
      setEntryError(caught instanceof Error ? caught.message : 'Mud Cost entry could not be saved')
    } finally {
      setSavingEntry(false)
    }
  }

  const runImport = async (rows: Record<string, string>[]) => {
    if (!selectedRig || !selectedWell || !entrySection?.is_current) throw new Error('Select an active rig, well and configured section before importing.')
    const result = await api<{ imported_count: number; error_count: number; errors: string[]; success: boolean }>('/mud-cost/entries/import', {
      method: 'POST',
      body: body({ rig_id: selectedRig.id, well_id: selectedWell.id, section_id: entrySection.id, rows }),
    })
    if (result.imported_count) {
      setNotice(`${result.imported_count} Mud Cost row(s) imported${result.error_count ? `; ${result.error_count} row(s) need correction` : ''}.`)
      await Promise.all([loadEntries(), loadBalance(), loadSettings(), loadReconciliation(), loadKpis()])
    }
    return result.errors
  }

  const executeAction = async () => {
    if (!pendingAction) return
    const ids = pendingAction.rows.map(row => row.id)
    setActionBusy(true)
    setActionError('')
    try {
      if (pendingAction.kind === 'delete') {
        if (ids.length === 1) await api(`/mud-cost/entries/${ids[0]}`, { method: 'DELETE' })
        else await api('/mud-cost/entries/bulk-delete', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} Mud Cost entry/entries moved to Deleted Entries.`)
      } else if (pendingAction.kind === 'restore') {
        if (ids.length === 1) await api(`/mud-cost/entries/${ids[0]}/restore`, { method: 'POST' })
        else await api('/mud-cost/entries/bulk-restore', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} Mud Cost entry/entries restored.`)
      } else if (ids.length === 1) {
        await api(`/mud-cost/entries/${ids[0]}/permanent`, { method: 'DELETE' })
        setNotice('Mud Cost entry permanently deleted.')
      } else {
        await api('/mud-cost/entries/bulk-permanent-delete', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} Mud Cost entry/entries permanently deleted.`)
      }
      setPendingAction(null)
      await Promise.all([loadEntries(), loadBalance(), loadSettings(), loadReconciliation(), loadKpis()])
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'The requested action could not be completed')
    } finally {
      setActionBusy(false)
    }
  }

  const exportEntries = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await auditExport({
      module: deletedView ? 'deleted' : 'entries', format, record_count: recordCount,
      rig_id: rigId, well_id: wellId,
      section_id: entrySectionId === ALL_SECTIONS ? '' : entrySectionId,
    })
  }

  const exportDetailedEntries = async (format: 'csv' | 'xlsx') => {
    setDetailedExportAnchor(null)
    setDetailedExportError('')
    try {
      await auditExport({
        module: deletedView ? 'deleted' : 'entries',
        format,
        record_count: tableRows.length,
        rig_id: rigId,
        well_id: wellId,
        section_id: entrySectionId === ALL_SECTIONS ? '' : entrySectionId,
      })
      const filename = `mud-cost-${deletedView ? 'deleted-' : ''}detail-${new Date().toISOString().slice(0, 10)}.${format}`
      if (format === 'csv') exportCsv(filename, tableRows, detailedExportColumns)
      else await exportXlsx(filename, tableRows, detailedExportColumns)
    } catch (caught) {
      setDetailedExportError(caught instanceof Error ? caught.message : 'The detailed Mud Cost export could not be prepared')
    }
  }

  const exportBalance = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await auditExport({
      module: 'material_balance', format, record_count: recordCount,
      rig_id: rigId, well_id: wellId,
      section_id: balanceSectionId === ALL_SECTIONS ? '' : balanceSectionId,
      view: balanceView,
      date_from: balanceView === 'inception' ? undefined : dateFrom || undefined,
      date_to: dateTo || undefined,
    })
  }

  const printBalance = async () => {
    if (!balance || !selectedRig || !selectedWell) return
    setBalanceError('')
    try {
      await auditExport({
        module: 'material_balance', format: 'print', record_count: balance.rows.length,
        rig_id: rigId, well_id: wellId,
        section_id: balanceSectionId === ALL_SECTIONS ? '' : balanceSectionId,
        view: balanceView,
        date_from: balanceView === 'inception' ? undefined : dateFrom || undefined,
        date_to: dateTo || undefined,
      })
      const viewLabel = MUD_COST_BALANCE_VIEWS.find(item => item.value === balanceView)?.label ?? balanceView
      print({
        rig: selectedRig.display_name,
        well: selectedWell.display_name,
        section: balanceSection?.display_name ?? 'All sections (each shown separately)',
        view: viewLabel,
        period: balanceView === 'inception'
          ? `Since first recorded entry${dateTo ? ` through ${dateLabel(dateTo)}` : ''}`
          : `${dateFrom ? dateLabel(dateFrom) : 'All dates'} to ${dateTo ? dateLabel(dateTo) : 'Latest entry'}`,
        rows: balance.rows,
        entryCount: balance.entry_count,
        sectionCount: balance.selected_section_count,
      })
    } catch (caught) {
      setBalanceError(caught instanceof Error ? caught.message : 'The print report could not be prepared')
    }
  }

  const pendingCount = pendingAction?.rows.length ?? 0
  const pendingTitle = pendingAction?.kind === 'delete'
    ? `Move ${pendingCount === 1 ? 'this entry' : `${pendingCount} entries`} to Deleted Entries?`
    : pendingAction?.kind === 'restore'
      ? `Restore ${pendingCount === 1 ? 'this entry' : `${pendingCount} entries`}?`
      : `Permanently delete ${pendingCount === 1 ? 'this entry' : `${pendingCount} entries`}?`
  const pendingSubtitle = pendingAction?.kind === 'delete'
    ? 'The entry remains recoverable. Later opening stocks will be recalculated from the remaining section history.'
    : pendingAction?.kind === 'restore'
      ? 'Restoring returns the row to the active material balance and recalculates subsequent opening stocks.'
      : 'Permanent deletion removes the daily entry and its line remarks. This cannot be undone.'

  const noConfiguredSection = Boolean(selectedWell && !selectedWell.sections.some(section => section.is_current))

  return <>
    <PageHeading
      eyebrow="DAILY COST MANAGEMENT / MUD COST ANALYSIS"
      title="Mud Cost Analysis"
      subtitle="Capture section-scoped daily mud movements and calculate closing stock. Each well/date has a single entry; balances stay separate by section."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void refresh()} disabled={referenceLoading || entriesLoading || balanceLoading}>
          {referenceLoading || entriesLoading || balanceLoading ? 'Refreshing…' : 'Refresh'}
        </Button>
        {can('rig-well:read') && <Button variant="outlined" component={RouterLink} to="/rig-well/wells" startIcon={<EventNoteOutlined/>}>Rig &amp; Well setup</Button>}
      </Box>}
    />

    <ErrorMessage message={referenceError}/>
    {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}

    <Paper variant="outlined" sx={{ p: `${space[4]}px`, borderRadius: `${radius.lg}px`, mb: `${space[4]}px` }}>
      <Box display="flex" alignItems="center" gap={1} mb={1.5}>
        <WaterDropOutlined sx={{ color: 'text.secondary', fontSize: 19 }}/>
        <Box>
          <Typography fontWeight={800} fontSize={14}>Well scope</Typography>
          <Typography color="text.secondary" fontSize={11.5}>Rigs, wells and sections come from Rig &amp; Well Management.</Typography>
        </Box>
      </Box>
      <Box display="grid" gap={1.4} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField select size="small" label="Rig" value={rigId} onChange={event => {
          setRigId(event.target.value)
          setWellId('')
          setEntrySectionId('')
          setBalanceSectionId(ALL_SECTIONS)
          setReconSectionId(ALL_SECTIONS)
        }} disabled={referenceLoading || !rigOptions.length}>
          <MenuItem value="" disabled>Select a rig</MenuItem>
          {rigOptions.map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Well" value={wellId} onChange={event => {
          setWellId(event.target.value)
          setEntrySectionId('')
          setBalanceSectionId(ALL_SECTIONS)
          setReconSectionId(ALL_SECTIONS)
        }} disabled={referenceLoading || !rigId || !wellOptions.length}>
          <MenuItem value="" disabled>Select a well</MenuItem>
          {wellOptions.map(well => <MenuItem key={well.id} value={well.id}>{well.display_name}</MenuItem>)}
        </TextField>
      </Box>
      {selectedRig?.is_deleted || selectedWell?.is_deleted ? <Alert severity="warning" sx={{ mt: 1.4 }}>
        This rig or well is in Deleted Entries. Historical records can be reviewed and cleaned up, but new entries are disabled.
      </Alert> : null}
    </Paper>

    {referenceLoading && !reference ? <Box py={7} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box> : null}
    {reference && !referenceLoading && reference.rigs.length === 0 && <Alert severity="info" sx={{ mb: 2 }}>
      Create a rig, well and at least one well section in Rig &amp; Well Management to start a Mud Cost record.
      {can('rig-well:read') && <Button component={RouterLink} to="/rig-well/wells" size="small" sx={{ ml: 1 }}>Open well register</Button>}
    </Alert>}
    {noConfiguredSection && <Alert severity="info" sx={{ mb: 2 }}>
      This well has no configured section. Add or configure sections in Rig &amp; Well Management before entering mud quantities.
      {can('rig-well:read') && <Button component={RouterLink} to="/rig-well/wells" size="small" sx={{ ml: 1 }}>Configure well sections</Button>}
    </Alert>}

    {hasScope && <>
      <Paper variant="outlined" sx={{ p: `${space[4]}px`, borderRadius: `${radius.lg}px`, mb: `${space[4]}px` }}>
        <Box display="flex" alignItems="flex-start" justifyContent="space-between" gap={1.5} flexWrap="wrap" mb={1.5}>
          <Box display="flex" alignItems="flex-start" gap={1}>
            <SettingsOutlined sx={{ color: 'text.secondary', fontSize: 19, mt: 0.2 }}/>
            <Box>
              <Typography fontWeight={800} fontSize={14}>Section mud type &amp; Cost/BBL</Typography>
              <Typography color="text.secondary" fontSize={11.5} maxWidth={760}>
                Configured once per section. WBM derives Cost/BBL as actual mud chemicals cost ÷ additions and keeps actual cost as reconciled cost. OBM, SOBM and OTHERS
                apply the reconciliation formula; OTHERS additionally requires remarks. Changes recalculate every day of that section.
              </Typography>
            </Box>
          </Box>
          {currentSettings.length > 0 && <Tag tone={unconfiguredSettings.length ? 'warning' : 'success'}>
            {currentSettings.length - unconfiguredSettings.length} of {currentSettings.length} sections configured
          </Tag>}
        </Box>
        {settingsError && <ErrorMessage message={settingsError}/>}
        {settingsLoading && !settings.length
          ? <Box py={3} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={22}/></Box>
          : currentSettings.length > 0
            ? <Box sx={{ overflowX: 'auto' }}>
                <Box component="table" sx={{
                  borderCollapse: 'collapse', width: '100%', minWidth: 780,
                  '& th': { textAlign: 'left', color: 'text.secondary', fontSize: 10, letterSpacing: 0.6, fontWeight: 800, py: 1, borderBottom: '1px solid', borderColor: 'divider' },
                  '& td': { py: 1.1, borderBottom: '1px solid', borderColor: 'divider', fontSize: 12, verticalAlign: 'top' },
                }}>
                  <thead><tr>
                    <th>SECTION</th><th>MUD TYPE</th><th>COST/BBL BASE RATE</th><th>REMARKS</th><th>STATUS</th><th>ACTIONS</th>
                  </tr></thead>
                  <tbody>{currentSettings.map(row => <tr key={row.section_id}>
                    <td><Typography fontSize={12} fontWeight={700}>{row.section_code} · {row.section_name}</Typography><Typography fontSize={10.5} color="text.secondary">{row.section_scope === 'completion' ? 'Completion' : 'Drilling'}</Typography></td>
                    <td><Tag tone={row.is_configured ? 'info' : 'warning'}>{row.mud_type ?? 'Not configured'}</Tag>{row.mud_type && <Typography fontSize={10.5} color="text.secondary" mt={0.4}>{row.mud_type_label}</Typography>}</td>
                    <td>{row.is_configured && row.mud_type && row.mud_type !== 'WBM' ? dailyMoney(row.base_rate, row.currency) : <Typography fontSize={12} color="text.secondary">—</Typography>}</td>
                    <td>{row.remarks ? <Typography fontSize={11.5} title={row.remarks} sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 280 }}>{row.remarks}</Typography> : <Typography fontSize={12} color="text.secondary">—</Typography>}</td>
                    <td><Tag tone={row.is_configured ? 'success' : 'neutral'}>{row.is_configured ? 'Configured' : 'Pending'}</Tag></td>
                    <td>{can('daily-cost:update') && <Button size="small" onClick={() => setConfigRow(row)} disabled={!selectedRig || selectedRig.is_deleted || !selectedWell || selectedWell.is_deleted}>{row.is_configured ? 'Edit' : 'Configure'}</Button>}</td>
                  </tr>)}</tbody>
                </Box>
              </Box>
            : <Typography color="text.secondary" fontSize={12.5}>This well has no configured section to set a mud type on.</Typography>}
        {unconfiguredSettings.length > 0 && <Alert severity="info" sx={{ mt: 1.4 }}>
          {unconfiguredSettings.length} section{unconfiguredSettings.length === 1 ? '' : 's'} still need a mud type. Reconciliation stays unavailable for an unconfigured section and its recorded mud chemicals cost remains the actual in Well Cost Analysis.
        </Alert>}
      </Paper>

      {!deletedView && <MudCostKpis
        sections={sectionOptions}
        settings={scopedSettings}
        snapshot={scopedKpis}
        loading={kpiLoading || !scopedKpis}
      />}

      <Paper variant="outlined" sx={{ borderRadius: `${radius.lg}px`, overflow: 'hidden' }}>
        <Tabs value={tab} onChange={(_event, value: number) => setTab(value)} aria-label="Mud Cost Analysis pages" sx={{ px: 1.2, borderBottom: 1, borderColor: 'divider' }}>
          <Tab label="Daily Entries" id="mud-cost-tab-entry" aria-controls="mud-cost-panel-entry"/>
          <Tab label="Material Balance" id="mud-cost-tab-balance" aria-controls="mud-cost-panel-balance"/>
          <Tab label="Reconciliation" id="mud-cost-tab-reconciliation" aria-controls="mud-cost-panel-reconciliation"/>
        </Tabs>

        {tab === 0 && <Box role="tabpanel" id="mud-cost-panel-entry" aria-labelledby="mud-cost-tab-entry" sx={{ p: `${space[4]}px` }}>
          <Box display="flex" justifyContent="space-between" alignItems="center" gap={1.5} flexWrap="wrap" mb={1.5}>
            <Box display="flex" alignItems="center" gap={1.2} flexWrap="wrap">
              <TextField select size="small" label="Entry section" value={entrySectionId} onChange={event => setEntrySectionId(event.target.value)} sx={{ minWidth: 260 }}>
                <MenuItem value="" disabled>Select a section</MenuItem>
                {sectionOptions.map(section => <MenuItem key={section.id} value={section.id}>{section.display_name}</MenuItem>)}
                <MenuItem value={ALL_SECTIONS}>All sections (separate rows)</MenuItem>
              </TextField>
              <Button size="small" color="inherit" variant={deletedView ? 'contained' : 'outlined'} startIcon={<RestoreRounded/>} onClick={() => { setDeletedView(value => !value); setSelectedRows([]) }}>
                {deletedView ? 'Active entries' : 'Deleted entries'}
              </Button>
              {selectedRows.length > 0 && <Tag tone="info">{selectedRows.length} selected</Tag>}
            </Box>
            <Box display="flex" gap={1} flexWrap="wrap">
              {can('daily-cost:export') && <>
                <Button size="small" variant="outlined" color="inherit" startIcon={<DownloadRounded/>} onClick={event => setDetailedExportAnchor(event.currentTarget)} disabled={!tableRows.length || entrySectionId === ALL_SECTIONS} title={entrySectionId === ALL_SECTIONS ? 'Choose one section to export re-importable line details.' : 'Export all configured line quantities and remarks for this section.'}>
                  Detailed export
                </Button>
                <Menu anchorEl={detailedExportAnchor} open={Boolean(detailedExportAnchor)} onClose={() => setDetailedExportAnchor(null)}>
                  <MenuItem onClick={() => void exportDetailedEntries('csv')}>Full details as CSV</MenuItem>
                  <MenuItem onClick={() => void exportDetailedEntries('xlsx')}>Full details as Excel</MenuItem>
                </Menu>
              </>}
              {deletedView
                ? <>
                    {can('daily-cost:restore') && selectedRows.length > 0 && <Button size="small" variant="outlined" startIcon={<RestoreRounded/>} onClick={() => setPendingAction({ kind: 'restore', rows: selectedRows })}>Restore selected</Button>}
                    {can('daily-cost:permanent-delete') && selectedRows.length > 0 && <Button size="small" variant="outlined" color="error" startIcon={<DeleteForeverOutlined/>} onClick={() => setPendingAction({ kind: 'purge', rows: selectedRows })}>Permanently delete selected</Button>}
                  </>
                : <>
                    {can('daily-cost:delete') && selectedRows.length > 0 && <Button size="small" variant="outlined" color="error" startIcon={<DeleteOutlineRounded/>} onClick={() => setPendingAction({ kind: 'delete', rows: selectedRows })}>Move selected to Deleted Entries</Button>}
                    {can('daily-cost:create') && <Button size="small" variant="contained" startIcon={<AddRounded/>} onClick={openCreate} disabled={!canCreateHere}>
                      New daily entry
                    </Button>}
                  </>}
            </Box>
          </Box>
          {entriesError && <ErrorMessage message={entriesError} />}
          {detailedExportError && <ErrorMessage message={detailedExportError} />}
          {entrySection && !entrySection.is_current && !deletedView && <Alert severity="info" sx={{ mb: 1.5 }}>
            This is a historical section snapshot. You can review its entries, but new entries must use a section in the current well configuration.
          </Alert>}
          {entriesLoading ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={25}/></Box> : <DataTable
            fillHeight
            fillReserve={entries.length === 0 ? 74 : 48}
            rows={tableRows}
            columns={entryColumns}
            rowKey="id"
            exportName={deletedView ? 'mud-cost-deleted-entries' : 'mud-cost-daily-entries'}
            searchPlaceholder="Search dates, sections and quantities..."
            selectable={deletedView ? can('daily-cost:restore') || can('daily-cost:permanent-delete') : can('daily-cost:delete')}
            onSelectionChange={setSelectedRows}
            selectionResetKey={selectionResetKey}
            canExport={can('daily-cost:export')}
            onExport={exportEntries}
            onImport={!deletedView && can('daily-cost:import') && Boolean(entrySection?.is_current) ? () => setImportOpen(true) : undefined}
          />}
          {entries.length === 0 && !entriesLoading && !entriesError && <Typography color="text.secondary" fontSize={12.5} mt={1.4}>
            {deletedView ? 'No deleted Mud Cost entries for this well.' : 'No daily Mud Cost entries yet. Create the first entry for the selected section and date.'}
          </Typography>}
          {!deletedView && can('daily-cost:read') && <Typography color="text.secondary" fontSize={11.5} mt={1.5}>
            Use Filters in the table for quick search, advanced column filters and a dedicated date range. Pagination is available at 20, 50 and 100 rows.
          </Typography>}
        </Box>}

        {tab === 1 && <Box role="tabpanel" id="mud-cost-panel-balance" aria-labelledby="mud-cost-tab-balance" sx={{ p: `${space[4]}px` }}>
          <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.1fr 1.2fr .9fr .9fr .9fr' }, alignItems: 'center', mb: 1.4 }}>
            <TextField select size="small" label="Material balance view" value={balanceView} onChange={event => setBalanceView(event.target.value as MudCostBalanceView)}>
              {MUD_COST_BALANCE_VIEWS.map(view => <MenuItem key={view.value} value={view.value}>{view.label}</MenuItem>)}
            </TextField>
            <TextField select size="small" label="Section" value={balanceSectionId} onChange={event => setBalanceSectionId(event.target.value)}>
              <MenuItem value={ALL_SECTIONS}>All sections (shown separately)</MenuItem>
              {sectionOptions.map(section => <MenuItem key={section.id} value={section.id}>{section.display_name}</MenuItem>)}
            </TextField>
            <TextField size="small" type="date" label="From" value={dateFrom} onChange={event => setDateFrom(event.target.value)} disabled={balanceView === 'inception'} InputLabelProps={{ shrink: true }}/>
            <TextField size="small" type="date" label="To" value={dateTo} onChange={event => setDateTo(event.target.value)} InputLabelProps={{ shrink: true }}/>
            <Box display="flex" justifyContent={{ xs: 'flex-start', sm: 'flex-end' }}>
              {can('daily-cost:export') && <Button variant="outlined" startIcon={<PrintOutlined/>} onClick={() => void printBalance()} disabled={!balance || balanceLoading || !balance.rows.length}>Print balance</Button>}
            </Box>
          </Box>
          {invalidBalanceDates && <Alert severity="error" sx={{ mb: 1.4 }}>The start date must not be after the end date.</Alert>}
          <Typography color="text.secondary" fontSize={11.5} mb={1.4}>
            {MUD_COST_BALANCE_VIEWS.find(view => view.value === balanceView)?.help} Opening stock carries forward from the prior calculated closing stock, including across days without transactions. When all sections are selected, every row is still section-specific.
          </Typography>
          {balanceError && <ErrorMessage message={balanceError} />}
          {balanceLoading ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={25}/></Box> : <DataTable
            fillHeight
            fillReserve={56}
            rows={balance?.rows ?? []}
            columns={balanceColumns}
            rowKey="id"
            exportName="mud-cost-material-balance"
            searchPlaceholder="Search date, period and section..."
            canExport={can('daily-cost:export')}
            onExport={exportBalance}
          />}
          {balance && <Box display="flex" justifyContent="space-between" gap={1} flexWrap="wrap" mt={1.2}>
            <Typography color="text.secondary" fontSize={11.5} aria-live="polite">
              {balance.entry_count} daily record(s) · {balance.selected_section_count} section(s); no cross-section totals are calculated.
            </Typography>
            {balanceView === 'inception' && <Typography color="text.secondary" fontSize={11.5}>
              Inception view includes each section from its first recorded entry through {dateTo ? dateLabel(dateTo) : 'the latest entry'}.
            </Typography>}
          </Box>}
          {!balanceLoading && balance && balance.rows.length === 0 && <Typography color="text.secondary" fontSize={12.5} mt={1.4}>
            No material-balance entries match this section and period.
          </Typography>}
        </Box>}

        {tab === 2 && <Box role="tabpanel" id="mud-cost-panel-reconciliation" aria-labelledby="mud-cost-tab-reconciliation" sx={{ p: `${space[4]}px` }}>
          <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.1fr .9fr .9fr .9fr auto' }, alignItems: 'center', mb: 1.4 }}>
            <TextField select size="small" label="Section" value={reconSectionId} onChange={event => setReconSectionId(event.target.value)}>
              <MenuItem value={ALL_SECTIONS}>All sections (shown separately)</MenuItem>
              {sectionOptions.map(section => <MenuItem key={section.id} value={section.id}>{section.display_name}</MenuItem>)}
            </TextField>
            <TextField size="small" type="date" label="From" value={reconDateFrom} onChange={event => setReconDateFrom(event.target.value)} InputLabelProps={{ shrink: true }}/>
            <TextField size="small" type="date" label="To" value={reconDateTo} onChange={event => setReconDateTo(event.target.value)} InputLabelProps={{ shrink: true }}/>
            <TextField select size="small" label="View" value={reconView} onChange={event => setReconView(event.target.value as 'daily' | 'section')}>
              <MenuItem value="daily">Daily detail</MenuItem>
              <MenuItem value="section">Section summary</MenuItem>
            </TextField>
            <Button size="small" variant="outlined" startIcon={<CalculateOutlined/>} onClick={() => { void loadReconciliation(); void loadKpis() }} disabled={reconLoading || kpiLoading}>
              {reconLoading ? 'Calculating…' : 'Recalculate'}
            </Button>
          </Box>
          {reconDateFrom && reconDateTo && reconDateFrom > reconDateTo && <Alert severity="error" sx={{ mb: 1.4 }}>The start date must not be after the end date.</Alert>}
          <Typography color="text.secondary" fontSize={11.5} mb={1.4}>
            WBM Cost/BBL = actual mud chemicals cost ÷ Additions, and its reconciled cost remains the actual cost. For OBM, SOBM and OTHERS: Total Mud we have = Opening Stock + Extra OBM received + Additions;
            ALPHA = (Opening Stock + Extra OBM received) × Cost/BBL base rate; BETA = ALPHA + actual mud chemicals cost (section & mud type scoped); Cost/BBL = BETA ÷ Total Mud we have; Reconciled Cost = (Consumption/Losses) × Cost/BBL. Every section is calculated and shown separately;
            cumulative figures run from that section&apos;s first entry. Section summary totals cover the selected period while
            Cost/BBL stays the latest cumulative rate to the To date.
          </Typography>
          {reconError && <ErrorMessage message={reconError}/>}
          {reconLoading && !reconciliation
            ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={25}/></Box>
            : reconciliation
              ? <>
                  <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }, mb: 1.6 }}>
                    <MudCostReconciliationRateKpi reconciliation={reconciliation}/>
                    <Stat label="Actual mud chemicals" value={dailyMoney(reconciliation.total_actual_cost, reconciliation.currency)} hint="Daily Cost register, section-scoped, in the AFE standard currency"/>
                    <Stat label="Reconciled mud cost" value={dailyMoney(reconciliation.total_reconciled_cost, reconciliation.currency)} hint="WBM uses actual cost; other mud types value Consumption/Losses at Cost/BBL"/>
                    <Stat label="Reconciliation difference" value={dailyMoney(reconciliation.total_adjustment, reconciliation.currency)} hint={`${reconciliation.configured_section_count} configured · ${reconciliation.unconfigured_section_count} unconfigured section(s)`}/>
                  </Box>
                  {reconciliation.unconfigured_section_count > 0 && <Alert severity="warning" sx={{ mb: 1.4 }}>
                    {reconciliation.unconfigured_section_count} section(s) have no mud type. Their actual mud chemicals cost is shown, but no reconciled amount is calculated until the section is configured above.
                  </Alert>}
                  {reconView === 'daily'
                    ? <DataTable
                        fillHeight
                        fillReserve={78}
                        rows={reconciliation.rows}
                        columns={reconciliationColumns}
                        rowKey="id"
                        exportName="mud-cost-reconciliation-daily"
                        searchPlaceholder="Search dates, sections, mud types and amounts..."
                        canExport={can('daily-cost:export')}
                        onExport={exportReconciliation}
                      />
                    : <DataTable
                        fillHeight
                        fillReserve={78}
                        rows={reconciliation.sections}
                        columns={reconciliationSectionColumns}
                        rowKey="section_id"
                        exportName="mud-cost-reconciliation-sections"
                        searchPlaceholder="Search sections, mud types and amounts..."
                        canExport={can('daily-cost:export')}
                        onExport={exportReconciliation}
                      />}
                  <Box display="flex" justifyContent="space-between" gap={1} flexWrap="wrap" mt={1.2}>
                    <Typography color="text.secondary" fontSize={11.5} aria-live="polite">
                      {reconView === 'daily' ? reconciliation.rows.length : reconciliation.sections.length} row(s) · {reconciliation.selected_section_count} section(s); no cross-section totals are calculated.
                    </Typography>
                    <Typography color="text.secondary" fontSize={11.5}>
                      Rate as at {dateLabel(reconciliation.to_date)} · {reconciliation.currency || 'No currency'} · entries to {dateLabel(reconciliation.to_date)}
                    </Typography>
                  </Box>
                  {reconView === 'daily' && reconciliation.rows.length === 0 && <Typography color="text.secondary" fontSize={12.5} mt={1.4}>
                    No reconciliation rows match this section and period. Add mud entries or configure a section’s mud type.
                  </Typography>}
                </>
              : <Typography color="text.secondary" fontSize={12.5} mt={1.4}>No reconciliation data for this section and period.</Typography>}
        </Box>}
      </Paper>
    </>}

    <MudCostOpeningStockDialog
      entry={openingStockEntry}
      onClose={() => setOpeningStockEntry(null)}
      onSave={async (entry, payload) => {
        await api(`/mud-cost/entries/${entry.id}/opening-stock`, { method: 'PUT', body: body(payload) })
        setOpeningStockEntry(null)
        setNotice('Initial opening stock saved. Section balances and reconciliation recalculated.')
        await Promise.all([loadEntries(), loadBalance(), loadReconciliation(), loadKpis()])
      }}
    />

    <MudCostEntryDialog
      open={entryDialogOpen}
      onClose={() => { setEntryDialogOpen(false); setEditingEntry(null); setEntryError('') }}
      onSave={saveEntry}
      entry={editingEntry}
      rig={selectedRig}
      well={selectedWell}
      section={editingEntry
        ? sectionOptions.find(section => section.id === editingEntry.section_id) ?? {
            id: editingEntry.section_id,
            hole_section_id: editingEntry.hole_section_id,
            section_code: editingEntry.section_code,
            section_name: editingEntry.section_name,
            scope: editingEntry.section_scope,
            from_depth: editingEntry.section_from_depth,
            to_depth: editingEntry.section_to_depth,
            is_current: false,
            display_name: editingEntry.section_label,
          }
        : entrySection}
      entries={activeEntries}
      existingRows={existingRows}
      saving={savingEntry}
      error={entryError}
    />

    <MudCostSectionSettingsDialog
      row={configRow}
      onClose={() => setConfigRow(null)}
      onSave={saveConfig}
    />


    {can('daily-cost:import') && <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import Mud Cost entries"
      subtitle={`Import date-wise rows into ${selectedWell?.display_name ?? 'the selected well'} · ${entrySection?.display_name ?? 'the selected section'}. Blank quantities are saved as zero; remarks are optional for every row.`}
      headers={MUD_COST_IMPORT_HEADERS}
      optionalHeaders={MUD_COST_IMPORT_OPTIONAL_HEADERS}
      sample={MUD_COST_IMPORT_SAMPLE}
      templateName="mud-cost-daily-entry-template.csv"
      onRows={runImport}
    />}

    <FormDialog
      open={Boolean(pendingAction)}
      title={pendingTitle}
      subtitle={pendingSubtitle}
      onClose={() => { if (!actionBusy) { setPendingAction(null); setActionError('') } }}
      onSubmit={executeAction}
      busy={actionBusy}
      busyLabel={pendingAction?.kind === 'purge' ? 'Permanently deleting…' : 'Saving…'}
      submitLabel={pendingAction?.kind === 'delete' ? 'Move to Deleted Entries' : pendingAction?.kind === 'restore' ? 'Restore entries' : 'Permanently delete'}
      danger={pendingAction?.kind === 'purge'}
    >
      <Box pt={0.5}><ErrorMessage message={actionError}/></Box>
    </FormDialog>

    {printSheet}
  </>
}

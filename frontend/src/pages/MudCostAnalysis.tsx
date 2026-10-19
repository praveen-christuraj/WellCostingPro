import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  AddRounded, DeleteForeverOutlined, DeleteOutlineRounded, DownloadRounded, EventNoteOutlined, PrintOutlined,
  RefreshRounded, RestoreRounded, WaterDropOutlined,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, Menu, MenuItem, Paper, Tab, Tabs, TextField, Typography,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { MudCostEntryDialog, type MudCostEditorPayload } from '../components/mud-cost/MudCostEntryDialog'
import { useMudCostPrint } from '../components/mud-cost/MudCostPrintSheet'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { exportCsv, exportXlsx, type ExportColumn } from '../lib/export'
import { radius, space } from '../designSystem'
import {
  MUD_COST_BALANCE_VIEWS, MUD_COST_IMPORT_HEADERS, MUD_COST_IMPORT_OPTIONAL_HEADERS, MUD_COST_LINE_SPECS,
  MUD_COST_IMPORT_SAMPLE, mudQuantity,
  type MudCostBalanceRow, type MudCostBalanceView, type MudCostEntry, type MudCostExportPayload,
  type MudCostMaterialBalance, type MudCostReference,
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
  const { can } = useAuth()
  const { print, printSheet } = useMudCostPrint()
  const [reference, setReference] = useState<MudCostReference | null>(null)
  const [referenceLoading, setReferenceLoading] = useState(true)
  const [referenceError, setReferenceError] = useState('')
  const [rigId, setRigId] = useState('')
  const [wellId, setWellId] = useState('')
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
  const [notice, setNotice] = useState('')
  const [selectedRows, setSelectedRows] = useState<MudCostEntry[]>([])
  const [selectionResetKey, setSelectionResetKey] = useState(0)
  const [entryDialogOpen, setEntryDialogOpen] = useState(false)
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

  useEffect(() => {
    if (!reference) return
    if (!rigId || !rigOptions.some(rig => rig.id === rigId)) {
      setRigId(rigOptions.find(rig => !rig.is_deleted)?.id ?? rigOptions[0]?.id ?? '')
    }
  }, [reference, rigId, rigOptions])

  useEffect(() => {
    if (!reference || !rigId) {
      setWellId('')
      return
    }
    if (!wellOptions.some(well => well.id === wellId)) {
      setWellId(wellOptions.find(well => !well.is_deleted)?.id ?? wellOptions[0]?.id ?? '')
    }
  }, [reference, rigId, wellId, wellOptions])

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

  useEffect(() => { void loadEntries() }, [loadEntries])
  useEffect(() => { void loadBalance() }, [loadBalance])

  const activeEntries = useMemo(() => entries
    .filter(entry => entry.rig_id === rigId && entry.well_id === wellId && !entry.is_deleted)
    .sort((a, b) => b.entry_date.localeCompare(a.entry_date)), [entries, rigId, wellId])
  const tableRows = useMemo(() => entries
    .filter(entry => entry.rig_id === rigId && entry.well_id === wellId
      && (entrySectionId === ALL_SECTIONS || !entrySectionId || entry.section_id === entrySectionId))
    .sort((a, b) => b.entry_date.localeCompare(a.entry_date)), [entries, rigId, wellId, entrySectionId])
  const selectedSectionEntries = activeEntries.filter(entry => entry.section_id === entrySectionId)
  const trackedSections = new Set(activeEntries.map(entry => entry.section_id)).size
  const latestEntry = selectedSectionEntries[0]
  const hasScope = Boolean(selectedRig && selectedWell)
  const canCreateHere = Boolean(hasScope && selectedRig && !selectedRig.is_deleted && selectedWell && !selectedWell.is_deleted && entrySection?.is_current)
  const invalidBalanceDates = balanceView !== 'inception' && dateFrom && dateTo && dateFrom > dateTo

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
      headerName: 'ACTIONS', field: 'id', minWidth: deletedView ? 210 : 160, width: deletedView ? 220 : 185, sortable: false,
      cellRenderer: (params: ICellRendererParams<MudCostEntry>) => {
        const record = params.data
        if (!record) return null
        return <Box display="flex" alignItems="center" height="100%" gap={0.25}>
          {deletedView ? <>
            {can('daily-cost:restore') && <Button size="small" onClick={() => { setActionError(''); setPendingAction({ kind: 'restore', rows: [record] }) }}>Restore</Button>}
            {can('daily-cost:permanent-delete') && <Button size="small" color="error" aria-label={`Permanently delete Mud Cost entry ${record.entry_date}`} onClick={() => { setActionError(''); setPendingAction({ kind: 'purge', rows: [record] }) }}><DeleteForeverOutlined sx={{ fontSize: 17 }}/></Button>}
          </> : <>
            {can('daily-cost:update') && <Button size="small" onClick={() => { setEditingEntry(record); setEntryError(''); setEntryDialogOpen(true) }}>Edit</Button>}
            {can('daily-cost:delete') && <Button size="small" color="error" aria-label={`Move Mud Cost entry ${record.entry_date} to Deleted Entries`} onClick={() => { setActionError(''); setPendingAction({ kind: 'delete', rows: [record] }) }}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></Button>}
          </>}
        </Box>
      },
    },
  ], [can, deletedView])

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

  const refresh = async () => {
    await Promise.all([loadReference(), loadEntries(), loadBalance()])
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
      await Promise.all([loadEntries(), loadBalance()])
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
      await Promise.all([loadEntries(), loadBalance()])
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
      await Promise.all([loadEntries(), loadBalance()])
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
        }} disabled={referenceLoading || !rigOptions.length}>
          <MenuItem value="" disabled>Select a rig</MenuItem>
          {rigOptions.map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Well" value={wellId} onChange={event => {
          setWellId(event.target.value)
          setEntrySectionId('')
          setBalanceSectionId(ALL_SECTIONS)
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
      {!deletedView && <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }, mb: `${space[4]}px` }}>
        <Stat label="Daily entries" value={activeEntries.length.toLocaleString()} hint="Active records for the selected well"/>
        <Stat label="Sections used" value={trackedSections.toLocaleString()} hint="Each section reconciles independently"/>
        <Stat label="Latest entry" value={dateLabel(activeEntries[0]?.entry_date)} hint={activeEntries[0]?.section_label ?? 'No records yet'}/>
        <Stat label="Latest closing stock" value={entrySectionId === ALL_SECTIONS ? 'Per section' : latestEntry ? mudQuantity(latestEntry.closing_stock) : '—'} hint={entrySection?.display_name ?? 'Choose one section to see its latest closing stock'}/>
      </Box>}

      <Paper variant="outlined" sx={{ borderRadius: `${radius.lg}px`, overflow: 'hidden' }}>
        <Tabs value={tab} onChange={(_event, value: number) => setTab(value)} aria-label="Mud Cost Analysis pages" sx={{ px: 1.2, borderBottom: 1, borderColor: 'divider' }}>
          <Tab label="Daily Entries" id="mud-cost-tab-entry" aria-controls="mud-cost-panel-entry"/>
          <Tab label="Material Balance" id="mud-cost-tab-balance" aria-controls="mud-cost-panel-balance"/>
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
      </Paper>
    </>}

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

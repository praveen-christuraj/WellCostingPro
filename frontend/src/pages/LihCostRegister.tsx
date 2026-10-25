import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  AddRounded, DeleteForeverOutlined, DeleteOutlineRounded, EventNoteOutlined, FilterAltOffOutlined,
  OpenInNewRounded, RefreshRounded, RestoreRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, Divider, IconButton, Menu, MenuItem, Paper, TextField, Tooltip, Typography,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag, useUnsavedChangesGuard } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { LihWorksheet } from '../components/lih-cost/LihWorksheet'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { readActiveScope, requestedScope, resolveRequestedScope, writeActiveScope } from '../lib/activeScope'
import { dailyMoney, displayDate, localToday } from '../lib/dailyCost'
import { exportCsv, exportPdf, exportXlsx, type ExportColumn, type ImportRow } from '../lib/export'
import {
  LIH_IMPORT_HEADERS, LIH_IMPORT_OPTIONAL_HEADERS, LIH_IMPORT_SAMPLE, blankDraftRow, draftRowFromSavedLine,
  lihDayPayloadLines, lihImportRow, lihLineTotal, lihQuery, rowHasChanged, rowIsBlank, validateDraft,
  type LihCostDay, type LihCostEntry, type LihCostImportResponse, type LihCostReference, type LihDraftRow,
} from '../lib/lihCost'

type PendingAction = { kind: 'delete' | 'restore' | 'purge'; rows: LihCostEntry[] }

export default function LihCostRegister() {
  const { can, user } = useAuth()
  const [searchParams] = useSearchParams()
  // The scope a daily cost register shortcut carried. The scope remembered from the
  // last register visit is read once the workspace is known (see below).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const linkedScope = useMemo(() => requestedScope(searchParams), [])
  const scopeApplied = useRef(false)
  const [reference, setReference] = useState<LihCostReference | null>(null)
  const [referenceError, setReferenceError] = useState('')
  const [register, setRegister] = useState<LihCostEntry[]>([])
  const [registerLoading, setRegisterLoading] = useState(true)
  const [registerError, setRegisterError] = useState('')
  const [showDeleted, setShowDeleted] = useState(false)
  const [notice, setNotice] = useState('')

  const [rigId, setRigId] = useState(linkedScope.rigId)
  const [wellId, setWellId] = useState(linkedScope.wellId)
  const [afeId, setAfeId] = useState('')
  const [costDate, setCostDate] = useState(localToday())
  const [day, setDay] = useState<LihCostDay | null>(null)
  const [dayLoading, setDayLoading] = useState(false)
  const [dayError, setDayError] = useState('')

  const [draft, setDraft] = useState<LihDraftRow[]>([])
  const [remarks, setRemarks] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [sheetExportAnchor, setSheetExportAnchor] = useState<HTMLElement | null>(null)
  const [autoFocusSheet, setAutoFocusSheet] = useState(false)
  const [worksheetOpen, setWorksheetOpen] = useState(false)

  const [filterRig, setFilterRig] = useState('')
  const [filterWell, setFilterWell] = useState('')
  const [filterAfe, setFilterAfe] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [selected, setSelected] = useState<LihCostEntry[]>([])
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  // Guards against a second save being fired before React re-renders the busy state.
  const saveInFlight = useRef(false)

  const canCreate = can('daily-cost:create')
  const canUpdate = can('daily-cost:update')
  const canSave = day ? canUpdate : canCreate
  const canEdit = canSave

  const filtersActive = Boolean(filterRig || filterWell || filterAfe || dateFrom || dateTo)
  const registerQuery = lihQuery({
    rig_id: filterRig, well_id: filterWell, afe_id: filterAfe, from: dateFrom, to: dateTo,
  })

  const loadReference = useCallback(async () => {
    try {
      setReference(await api<LihCostReference>('/lih-cost/reference'))
      setReferenceError('')
    } catch (caught) {
      setReferenceError(caught instanceof Error ? caught.message : 'The LIH register reference data could not be loaded')
    }
  }, [])

  const loadRegister = useCallback(async () => {
    setRegisterLoading(true)
    setRegisterError('')
    setSelected([])
    try {
      const base = showDeleted ? '/lih-cost/entries/deleted' : '/lih-cost/entries'
      setRegister(await api<LihCostEntry[]>(`${base}${registerQuery}`))
    } catch (caught) {
      setRegisterError(caught instanceof Error ? caught.message : 'The LIH register could not be loaded')
    } finally {
      setRegisterLoading(false)
    }
  }, [registerQuery, showDeleted])

  const loadDay = useCallback(async (well: string, date: string) => {
    if (!well || !date) { setDay(null); return }
    setDayLoading(true)
    setDayError('')
    try {
      const result = await api<LihCostDay | null>(`/lih-cost/day?${new URLSearchParams({ well_id: well, date }).toString()}`)
      setDay(result)
      // An existing day is always edited against the AFE it is filed on. A new
      // day keeps the AFE chosen for the well (a multi-AFE well must name one).
      if (result) setAfeId(result.entry.afe_id ?? '')
    } catch (caught) {
      setDay(null)
      setDayError(caught instanceof Error ? caught.message : 'This LIH day could not be loaded')
    } finally {
      setDayLoading(false)
    }
  }, [])

  useEffect(() => { void loadReference() }, [loadReference])
  useEffect(() => { void loadRegister() }, [loadRegister])
  useEffect(() => { void loadDay(wellId, costDate) }, [wellId, costDate, loadDay])

  // Select the rig, well and AFE the register was opened with once the reference
  // is known. A plain visit without a remembered scope keeps the deliberate
  // "choose a rig and well" start.
  useEffect(() => {
    if (!reference || !user || scopeApplied.current) return
    scopeApplied.current = true
    const remembered = readActiveScope(user.organization_slug)
    const next = resolveRequestedScope(
      { rigId: rigId || remembered.rigId, wellId: wellId || remembered.wellId }, reference.wells, reference.rigs,
    )
    if (next.wellId) {
      setRigId(next.rigId)
      setWellId(next.wellId)
      setAfeId(reference.afes.find(afe => afe.well_id === next.wellId)?.id ?? '')
    } else if (next.rigId) setRigId(next.rigId)
  }, [reference, user, rigId, wellId])

  // The scope chosen here becomes the current scope everywhere in Daily Cost Management.
  useEffect(() => {
    if (rigId && wellId && user) writeActiveScope({ rigId, wellId }, user.organization_slug)
  }, [rigId, wellId, user])

  // Reset the worksheet whenever a different day is loaded, or after any save
  // (the revision changes), so the sheet always mirrors what is stored.
  const loadedKey = day ? `${day.entry.id}:${day.entry.revision}:${day.lines.length}` : ''
  useEffect(() => {
    if (day) {
      setDraft(day.lines.length ? day.lines.map(draftRowFromSavedLine) : [blankDraftRow()])
      setRemarks(day.entry.remarks)
    } else {
      setDraft(wellId && costDate ? [blankDraftRow()] : [])
      setRemarks('')
    }
    setSaveError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedKey, wellId, costDate])

  const wellsForRig = useMemo(
    () => reference?.wells.filter(well => !rigId || well.rig_id === rigId) ?? [],
    [reference, rigId],
  )
  const selectedWell = reference?.wells.find(well => well.id === wellId)
  const afesForWell = useMemo(
    () => reference?.afes.filter(afe => afe.well_id === wellId) ?? [],
    [reference, wellId],
  )
  const selectedAfe = afesForWell.find(afe => afe.id === afeId) ?? afesForWell[0] ?? null
  const dayCurrency = day?.entry.currency || selectedAfe?.standard_currency || reference?.default_currency || ''

  const removedCount = useMemo(() => {
    if (!day) return 0
    const kept = new Set(draft.filter(row => row.id).map(row => row.id))
    return day.lines.filter(line => !kept.has(line.id)).length
  }, [day, draft])
  const rowsDirty = useMemo(() => draft.some(rowHasChanged), [draft])
  const remarksDirty = day ? remarks !== day.entry.remarks : remarks.trim() !== ''
  // Re-filing the day against another AFE is a real change, so it must enable Save.
  const afeDirty = Boolean(day) && (afeId || '') !== (day?.entry.afe_id ?? '')
  const dirty = rowsDirty || removedCount > 0 || remarksDirty || afeDirty

  /**
   * Changing the day while the sheet has unsaved work would throw it away, so
   * the day selectors are locked until the sheet is saved or deliberately
   * discarded (the same rule as the navigation guard).
   */
  const dayLocked = dirty && !saving

  const chooseRig = (value: string) => {
    if (dayLocked) return
    setRigId(value)
    const nextWells = reference?.wells.filter(well => !value || well.rig_id === value) ?? []
    if (!nextWells.some(well => well.id === wellId)) {
      const first = nextWells[0]
      setWellId(first?.id ?? '')
      setAfeId(reference?.afes.find(afe => afe.well_id === first?.id)?.id ?? '')
      setAutoFocusSheet(false)
    }
  }
  const chooseWell = (value: string) => {
    if (dayLocked) return
    setWellId(value)
    setAfeId(reference?.afes.find(afe => afe.well_id === value)?.id ?? '')
    setAutoFocusSheet(true)
  }

  const discardDraft = useCallback(() => {
    if (day) {
      setDraft(day.lines.length ? day.lines.map(draftRowFromSavedLine) : [blankDraftRow()])
      setRemarks(day.entry.remarks)
      setAfeId(day.entry.afe_id ?? '')
    } else {
      setDraft([blankDraftRow()])
      setRemarks('')
    }
    setSaveError('')
  }, [day])

  const saveWorksheet = useCallback(async (): Promise<boolean> => {
    if (!wellId || !costDate) {
      setSaveError('Choose a well and a LIH date before saving the sheet.')
      return false
    }
    if (!canSave) {
      setSaveError('You do not have permission to save this LIH worksheet.')
      return false
    }
    if (saveInFlight.current) return false
    const problems = validateDraft(draft)
    if (problems.length) {
      setSaveError(`Fix ${problems.length} row${problems.length === 1 ? '' : 's'} on the sheet before saving.`)
      return false
    }
    const lines = lihDayPayloadLines(draft)
    if (!day && !lines.length) {
      setSaveError('Add at least one LIH item before saving the register day.')
      return false
    }
    saveInFlight.current = true
    setSaving(true)
    setSaveError('')
    try {
      const updated = await api<LihCostDay>('/lih-cost/day', {
        method: 'PUT',
        body: body({
          well_id: wellId,
          rig_id: rigId,
          afe_id: afeId,
          cost_date: costDate,
          remarks,
          expected_revision: day?.entry.revision ?? null,
          lines,
        }),
      })
      setDay(updated)
      setNotice(`LIH day saved — ${updated.entry.line_count} item(s), total ${dailyMoney(updated.entry.total_cost, updated.entry.currency)}.`)
      await loadRegister()
      return true
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : 'The LIH worksheet could not be saved')
      return false
    } finally {
      saveInFlight.current = false
      setSaving(false)
    }
  }, [afeId, canSave, costDate, day, draft, loadRegister, remarks, rigId, wellId])

  // Ctrl/⌘+S saves from anywhere on the page, not only from a focused cell.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return
      if (!worksheetOpen || !dirty || saving || !canSave || showDeleted || importOpen || pending) return
      event.preventDefault()
      void saveWorksheet().then(saved => {
        if (saved) {
          setWorksheetOpen(false)
          setAutoFocusSheet(false)
        }
      })
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [canSave, dirty, importOpen, pending, saveWorksheet, saving, showDeleted, worksheetOpen])

  const leaveGuard = useUnsavedChangesGuard({
    when: dirty,
    onSave: saveWorksheet,
    title: 'Leave with an unsaved LIH worksheet?',
    message: 'The items and remarks on this LIH worksheet are not saved yet. Save them before leaving, or discard them deliberately.',
  })

  /** Import replaces the loaded day from the server, so unsaved work is protected first. */
  const openImport = () => {
    if (dayLocked) {
      setSaveError('Save or discard the worksheet changes before importing items.')
      return
    }
    setImportOpen(true)
  }

  const refresh = () => {
    void loadRegister()
    if (dayLocked) {
      setSaveError('Save or discard the worksheet changes before reloading the day.')
      return
    }
    void loadDay(wellId, costDate)
  }

  const runImport = async (rows: ImportRow[]): Promise<string[]> => {
    if (!wellId) return ['Choose the well the LIH items belong to before importing.']
    const payload = rows.map(lihImportRow)
    try {
      const result = await api<LihCostImportResponse>('/lih-cost/import', {
        method: 'POST',
        body: body({ well_id: wellId, afe_id: afeId, cost_date: costDate, rows: payload }),
      })
      if (result.imported_count) {
        setNotice(`Imported ${result.imported_count} LIH item(s) into ${result.day_count} day(s).`)
        await loadRegister()
        await loadDay(wellId, costDate)
      }
      return result.errors
    } catch (caught) {
      return [caught instanceof Error ? caught.message : 'The LIH items could not be imported']
    }
  }

  const act = async () => {
    if (!pending) return
    setActionBusy(true)
    setActionError('')
    try {
      const ids = pending.rows.map(row => row.id)
      if (pending.kind === 'delete') {
        if (ids.length === 1) await api(`/lih-cost/entries/${ids[0]}`, { method: 'DELETE' })
        else await api('/lih-cost/entries/bulk-delete', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} LIH day${ids.length === 1 ? '' : 's'} moved to Deleted Entries.`)
      } else if (pending.kind === 'restore') {
        if (ids.length === 1) await api(`/lih-cost/entries/${ids[0]}/restore`, { method: 'POST' })
        else await api('/lih-cost/entries/bulk-restore', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} LIH day${ids.length === 1 ? '' : 's'} restored to the register.`)
      } else {
        if (ids.length === 1) await api(`/lih-cost/entries/${ids[0]}/permanent`, { method: 'DELETE' })
        else await api('/lih-cost/entries/bulk-permanent-delete', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} LIH day${ids.length === 1 ? '' : 's'} permanently deleted.`)
      }
      setPending(null)
      await loadRegister()
      await loadDay(wellId, costDate)
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'The requested action could not be completed')
    } finally {
      setActionBusy(false)
    }
  }

  const openRegisterDay = (entry: LihCostEntry) => {
    if (dayLocked) {
      setNotice('')
      setSaveError('Save or discard the current worksheet before opening another LIH day.')
      return
    }
    setDay(null)
    setDraft([])
    setRigId(entry.rig_id)
    setWellId(entry.well_id)
    setAfeId(entry.afe_id ?? '')
    setCostDate(entry.cost_date)
    setAutoFocusSheet(false)
    setWorksheetOpen(true)
    void loadDay(entry.well_id, entry.cost_date)
  }

  const openWorksheet = () => {
    setSaveError('')
    if (!rigId || !wellId || !costDate) {
      setDayError('Choose the rig, well and LIH date before adding items.')
      return
    }
    setDayError('')
    setAutoFocusSheet(true)
    setWorksheetOpen(true)
  }

  const closeWorksheet = () => {
    if (dirty) discardDraft()
    setWorksheetOpen(false)
    setAutoFocusSheet(false)
  }

  const saveAndCloseWorksheet = async () => {
    if (await saveWorksheet()) {
      setWorksheetOpen(false)
      setAutoFocusSheet(false)
    }
  }

  const exportAudit = async (
    format: 'csv' | 'xlsx' | 'pdf', recordCount: number, module: 'register' | 'deleted' | 'day',
  ) => {
    if (!can('daily-cost:export')) return
    await api('/lih-cost/export-audit', {
      method: 'POST',
      body: body({
        module,
        format,
        record_count: recordCount,
        include_deleted: showDeleted,
        well_id: module === 'day' ? wellId : filterWell,
        entry_id: module === 'day' ? day?.entry.id ?? '' : '',
      }),
    })
  }

  /** Export the sheet as shown, including rows that are not saved yet. */
  const exportSheet = async (format: 'csv' | 'xlsx' | 'pdf') => {
    setSheetExportAnchor(null)
    const rows = draft.filter(row => !rowIsBlank(row.values))
    if (!rows.length) {
      setSaveError('There are no items on the sheet to export.')
      return
    }
    const heading = (label: string) => `${label} (${dayCurrency || 'currency'})`
    const columns: ExportColumn<LihDraftRow>[] = [
      { header: 'ITEM DESCRIPTION', value: row => row.values.item_description.trim() },
      { header: 'OD', value: row => row.values.od_size.trim() },
      { header: 'ID', value: row => row.values.id_size.trim() },
      { header: 'FISH NECK OD', value: row => row.values.fish_neck_od.trim() },
      { header: 'FISH NECK LENGTH', value: row => row.values.fish_neck_length.trim() },
      { header: 'SERIAL NUMBER', value: row => row.values.serial_number.trim() },
      { header: 'CONNECTION', value: row => row.values.connection.trim() },
      { header: 'LENGTH', value: row => row.values.length.trim() },
      { header: 'UNITS', value: row => row.values.no_of_units.trim() },
      { header: 'UNIT', value: row => row.values.unit.trim() },
      { header: heading('UNIT COST'), value: row => row.values.unit_cost.trim() },
      { header: heading('TOTAL COST'), value: row => lihLineTotal(row.values).toFixed(2) },
      { header: 'REMARKS', value: row => row.values.remarks.trim() },
      { header: 'STATE', value: row => (row.id ? 'saved' : 'not saved') },
    ]
    const filename = `lih-sheet-${day?.entry.well_code ?? selectedWell?.well_code ?? 'well'}-${costDate}`
    if (format === 'csv') exportCsv(`${filename}.csv`, rows, columns)
    else if (format === 'xlsx') await exportXlsx(`${filename}.xlsx`, rows, columns)
    else await exportPdf(`${filename}.pdf`, `LIH sheet · ${day?.entry.well_code ?? selectedWell?.well_code ?? ''} · ${costDate}`, rows, columns)
    await exportAudit(format, rows.length, 'day')
  }

  const registerColumns = useMemo<ColDef<LihCostEntry>[]>(() => [
    { headerName: 'DATE', field: 'cost_date', minWidth: 130, width: 135, valueFormatter: params => displayDate(String(params.value ?? '')) },
    { headerName: 'RIG', field: 'rig_code', minWidth: 140, valueGetter: params => `${params.data?.rig_code ?? ''} · ${params.data?.rig_name ?? ''}` },
    { headerName: 'WELL', field: 'well_code', minWidth: 170, valueGetter: params => `${params.data?.well_code ?? ''} · ${params.data?.well_name ?? ''}` },
    {
      headerName: 'AFE', field: 'afe_code', minWidth: 190,
      valueGetter: params => params.data?.afe_code ? `${params.data.afe_code} · ${params.data.afe_name}` : 'No AFE',
    },
    { headerName: 'ITEMS', field: 'line_count', minWidth: 100 },
    {
      headerName: 'TOTAL LIH COST', field: 'total_cost', minWidth: 170,
      cellRenderer: (params: ICellRendererParams<LihCostEntry>) => <Typography fontSize={12} fontWeight={800}>{dailyMoney(params.data?.total_cost, params.data?.currency)}</Typography>,
    },
    { headerName: 'REMARKS', field: 'remarks', minWidth: 220, flex: 1, valueFormatter: params => String(params.value || '—') },
    { headerName: 'UPDATED BY', field: 'updated_by', minWidth: 150, valueFormatter: params => String(params.value || '—') },
    {
      headerName: 'ACTIONS',
      colId: 'actions',
      minWidth: 150,
      sortable: false,
      filter: false,
      cellRenderer: (params: ICellRendererParams<LihCostEntry>) => {
        const entry = params.data
        if (!entry) return null
        return <Box display="flex" gap={.4} alignItems="center">
          {!showDeleted && <Button size="small" startIcon={<OpenInNewRounded sx={{ fontSize: 16 }}/>} onClick={() => openRegisterDay(entry)}>View items</Button>}
          {!showDeleted && can('daily-cost:delete') && <Tooltip title="Move to Deleted Entries"><span><IconButton size="small" color="error" aria-label="Delete LIH day" onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: [entry] }) }}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton></span></Tooltip>}
          {showDeleted && can('daily-cost:restore') && <Tooltip title="Restore"><span><IconButton size="small" aria-label="Restore LIH day" onClick={() => { setActionError(''); setPending({ kind: 'restore', rows: [entry] }) }}><RestoreRounded sx={{ fontSize: 17 }}/></IconButton></span></Tooltip>}
          {showDeleted && can('daily-cost:permanent-delete') && <Tooltip title="Delete permanently"><span><IconButton size="small" color="error" aria-label="Permanently delete LIH day" onClick={() => { setActionError(''); setPending({ kind: 'purge', rows: [entry] }) }}><DeleteForeverOutlined sx={{ fontSize: 17 }}/></IconButton></span></Tooltip>}
        </Box>
      },
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [can, dayLocked, showDeleted])

  const actionTitle = pending?.kind === 'purge' ? 'Delete this LIH day permanently?'
    : pending?.kind === 'restore' ? 'Restore this LIH day?' : 'Move this LIH day to Deleted Entries?'
  const actionSubtitle = pending?.rows.length === 1 ? pending.rows[0].display_name : `${pending?.rows.length ?? 0} register days selected`
  const worksheetTitle = day
    ? `${day.entry.well_code} · LIH cost on ${displayDate(day.entry.cost_date)}`
    : `${selectedWell?.well_code ?? 'Well'} · LIH cost on ${displayDate(costDate)}`

  return <>
    <PageHeading
      eyebrow="DAILY COST MANAGEMENT / LIH COST REGISTER"
      title="LIH Cost Register"
      subtitle="Capture every Lost In Hole item on one worksheet and save them together, or import a whole file. Saved items stay editable, and similar items can be duplicated. LIH is added to the actual cost and deducted explicitly from the AFE total."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button variant="outlined" startIcon={<RefreshRounded/>} disabled={registerLoading} onClick={refresh}>
          {registerLoading ? 'Refreshing…' : 'Refresh'}
        </Button>
        <Button variant="outlined" startIcon={showDeleted ? <EventNoteOutlined/> : <DeleteOutlineRounded/>} onClick={() => {
          if (dayLocked) { setSaveError('Save or discard the worksheet before opening Deleted Entries.'); return }
          setShowDeleted(value => !value); setNotice('')
        }}>
          {showDeleted ? 'Active register' : 'Deleted entries'}
        </Button>
      </Box>}
    />
    <ErrorMessage message={referenceError}/>
    {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}

    {!showDeleted && <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, mb: 1.6 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" mb={1.3}>
        <Box>
          <Typography fontWeight={800} fontSize={15}>Select the LIH day</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25}>
            Choose the rig and its well, then the date the LIH cost belongs to. Open the item dialog only when you are ready to enter or review lines.
          </Typography>
        </Box>
        <Box display="flex" gap={0.7} flexWrap="wrap">
          {day && <Tag tone={day.entry.afe_id ? 'info' : 'warning'}>{day.entry.afe_id ? `Deducted from ${day.entry.afe_code}` : 'No AFE on this well'}</Tag>}
          {day && <Tag>Revision {day.entry.revision}</Tag>}
          {day && <Tag tone={day.entry.line_count ? 'success' : 'neutral'}>{day.entry.line_count} saved item{day.entry.line_count === 1 ? '' : 's'}</Tag>}
          {day && <Tag tone="info">Total {dailyMoney(day.entry.total_cost, day.entry.currency)}</Tag>}
        </Box>
      </Box>
      <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: '1fr', md: '1fr 1.3fr .9fr .9fr auto' } }} alignItems="center">
        <TextField select label="Rig" value={rigId} onChange={event => chooseRig(event.target.value)} helperText="Rigs in this workspace" disabled={dayLocked}>
          <MenuItem value="">Choose rig</MenuItem>
          {(reference?.rigs ?? []).map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <TextField select required label="Well" value={wellId} onChange={event => chooseWell(event.target.value)} disabled={dayLocked || !wellsForRig.length}
          helperText={selectedWell ? `${selectedWell.well_code} · ${selectedWell.well_name}` : 'Choose the well the LIH cost belongs to'}>
          {wellsForRig.map(well => <MenuItem key={well.id} value={well.id}>{well.display_name}</MenuItem>)}
        </TextField>
        <TextField required type="date" label="LIH date" value={costDate} onChange={event => { if (!dayLocked) { setCostDate(event.target.value); setAutoFocusSheet(true) } }}
          InputLabelProps={{ shrink: true }} disabled={dayLocked}/>
        {afesForWell.length > 1
          ? <TextField select label="AFE" value={afeId} onChange={event => setAfeId(event.target.value)}
              helperText="Each AFE deducts its own LIH cost" disabled={dayLocked}>
              {day && !day.entry.afe_id && <MenuItem value="">No AFE (as saved)</MenuItem>}
              {afesForWell.map(afe => <MenuItem key={afe.id} value={afe.id}>{afe.display_name}</MenuItem>)}
            </TextField>
          : <TextField label="AFE" value={selectedAfe ? `${selectedAfe.afe_code} · ${selectedAfe.afe_name}` : 'No AFE yet'} InputProps={{ readOnly: true }}
              helperText={selectedAfe ? `Standard currency ${selectedAfe.standard_currency}` : 'Recorded in the workspace default currency'}/>}
        <Button variant="contained" startIcon={<AddRounded/>} onClick={openWorksheet}
          disabled={!rigId || !wellId || !costDate || dayLoading || (!day && !canCreate)}>
          Add items
        </Button>
      </Box>
      {dayLocked && <Alert severity="info" sx={{ mt: 1.3, py: .4 }}>
        The worksheet has unsaved changes. Save all items or discard the changes before switching to another day.
      </Alert>}
      {afesForWell.length > 1 && !dayLocked && <Alert severity="info" sx={{ mt: 1.3, py: .4 }}>
        This well has {afesForWell.length} AFEs. The LIH cost is deducted from the AFE selected above only.
      </Alert>}
      {!wellId && <Alert severity="info" sx={{ mt: 1.3, py: .4 }}>Choose a rig and well to open its LIH worksheet.</Alert>}
    </Paper>}

    <ErrorMessage message={dayError}/>
    {!showDeleted && wellId && dayLoading && <Box py={4} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={24}/></Box>}

    <FormDialog
      open={worksheetOpen}
      title={worksheetTitle}
      subtitle={day
        ? `${day.entry.rig_code} · ${day.entry.rig_name} · ${day.entry.afe_code || 'No AFE'} · recorded in ${day.entry.currency}`
        : `${selectedWell?.well_code ?? ''} · ${selectedAfe?.afe_code ?? 'No AFE'} · ${dayCurrency || 'currency from the AFE'}. The day is created when the first items are saved.`}
      onClose={closeWorksheet}
      onSubmit={() => void saveAndCloseWorksheet()}
      busy={saving}
      busyLabel="Saving all items…"
      submitLabel="Save all items"
      submitDisabled={!dirty || !canEdit || dayLoading}
      dirty={dirty}
      maxWidth="xl"
    >
      {dayLoading ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
        : dayError ? <ErrorMessage message={dayError}/>
        : draft.length > 0 ? <Box>
        <Box display="flex" justifyContent="space-between" alignItems="flex-start" gap={1} flexWrap="wrap" mb={1.2}>
          <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
            <Box sx={{ px: 1.4, py: .7, border: '1px solid', borderColor: 'divider', borderRadius: 1.5, minWidth: 150 }}>
              <Typography fontSize={9.5} fontWeight={800} letterSpacing={.6} color="text.secondary">SAVED LIH TOTAL</Typography>
              <Typography fontSize={17} fontWeight={800} mt={.2}>{dailyMoney(day?.entry.total_cost ?? '0', dayCurrency)}</Typography>
            </Box>
            <Box sx={{ px: 1.4, py: .7, border: '1px solid', borderColor: 'divider', borderRadius: 1.5, minWidth: 150 }}>
              <Typography fontSize={9.5} fontWeight={800} letterSpacing={.6} color="text.secondary">ACCOUNTING TREATMENT</Typography>
              <Typography fontSize={12.5} fontWeight={800} mt={.5}>Added to actual</Typography>
              <Typography fontSize={10.5} color="text.secondary">Deducted from the AFE total</Typography>
            </Box>
          </Box>
        </Box>

        <LihWorksheet
          rows={draft}
          onRowsChange={setDraft}
          currency={dayCurrency}
          uoms={reference?.uoms ?? []}
          suggestions={reference?.previous_items ?? []}
          removedCount={removedCount}
          savedCount={day?.lines.length ?? 0}
          canEdit={canEdit}
          canImport={can('daily-cost:import') && Boolean(wellId)}
          canExport={can('daily-cost:export')}
          saving={saving}
          dirty={dirty}
          saveError={saveError}
          onSave={() => void saveWorksheet()}
          onDiscard={discardDraft}
          onImport={openImport}
          onExportSheet={setSheetExportAnchor}
          autoFocus={autoFocusSheet}
          showSaveActions={false}
        />

        <Divider sx={{ my: 1.6 }}/>
        <TextField
          fullWidth
          label="Day remarks"
          value={remarks}
          onChange={event => setRemarks(event.target.value)}
          disabled={!canEdit}
          multiline
          minRows={2}
          inputProps={{ maxLength: 1000 }}
          helperText={remarksDirty ? 'Unsaved remarks — they save with the worksheet.' : 'Context for this LIH day, for example the fishing job or failure.'}
        />
      </Box> : <Typography color="text.secondary">No LIH item sheet is available for this selection.</Typography>}
    </FormDialog>

    {can('daily-cost:import') && <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title="Import LIH items"
        subtitle={`Add many LIH items to ${selectedWell?.display_name ?? 'the selected well'} from an Excel or CSV file. Each row may carry its own Date; rows without a date use ${displayDate(costDate)}. Rows are added to the day they belong to, and any existing day is appended to, not replaced.`}
        headers={LIH_IMPORT_HEADERS}
        optionalHeaders={LIH_IMPORT_OPTIONAL_HEADERS}
        sample={LIH_IMPORT_SAMPLE}
        templateName="lih-cost-items-template.csv"
        onRows={runImport}
      />}

    <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2, mb: 1.8 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" mb={1.2}>
        <Box>
          <Typography fontWeight={800} fontSize={15}>{showDeleted ? 'Deleted LIH register entries' : 'LIH register'}</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25}>
            Every LIH day in this workspace, with its item count and total LIH cost.
          </Typography>
        </Box>
        <Tag>{register.length} day{register.length === 1 ? '' : 's'}</Tag>
      </Box>
      <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', lg: '1fr 1.3fr 1.2fr .8fr .8fr auto' } }} alignItems="center">
        <TextField select label="Filter by rig" value={filterRig} onChange={event => { setFilterRig(event.target.value); setFilterWell(''); setFilterAfe('') }}>
          <MenuItem value="">All rigs</MenuItem>
          {(reference?.rigs ?? []).map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <TextField select label="Filter by well" value={filterWell} onChange={event => { setFilterWell(event.target.value); setFilterAfe('') }}>
          <MenuItem value="">All wells</MenuItem>
          {(reference?.wells ?? []).filter(well => !filterRig || well.rig_id === filterRig)
            .map(well => <MenuItem key={well.id} value={well.id}>{well.display_name}</MenuItem>)}
        </TextField>
        <TextField select label="Filter by AFE" value={filterAfe} onChange={event => setFilterAfe(event.target.value)}>
          <MenuItem value="">All AFEs</MenuItem>
          {(reference?.afes ?? []).filter(afe => !filterWell || afe.well_id === filterWell)
            .map(afe => <MenuItem key={afe.id} value={afe.id}>{afe.display_name}</MenuItem>)}
        </TextField>
        <TextField type="date" label="From" value={dateFrom} onChange={event => setDateFrom(event.target.value)} InputLabelProps={{ shrink: true }}/>
        <TextField type="date" label="To" value={dateTo} onChange={event => setDateTo(event.target.value)} InputLabelProps={{ shrink: true }}/>
        <Button variant="outlined" startIcon={<FilterAltOffOutlined/>} onClick={() => {
          setFilterRig(''); setFilterWell(''); setFilterAfe(''); setDateFrom(''); setDateTo('')
        }} disabled={!filtersActive}>Clear</Button>
      </Box>
      {dateFrom && dateTo && dateFrom > dateTo && <Alert severity="error" sx={{ mt: 1.2 }}>The start date is after the end date.</Alert>}
    </Paper>

    {selected.length > 0 && <Paper variant="outlined" sx={{ p: 1.4, borderRadius: 2, mb: 1.5, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
      <Typography fontSize={12} fontWeight={700} mr="auto">{selected.length} LIH day{selected.length === 1 ? '' : 's'} selected</Typography>
      {showDeleted ? <>
        {can('daily-cost:restore') && <Button size="small" startIcon={<RestoreRounded/>} onClick={() => { setActionError(''); setPending({ kind: 'restore', rows: selected }) }}>Restore selected</Button>}
        {can('daily-cost:permanent-delete') && <Button size="small" color="error" startIcon={<DeleteForeverOutlined/>} onClick={() => { setActionError(''); setPending({ kind: 'purge', rows: selected }) }}>Delete permanently</Button>}
      </> : can('daily-cost:delete') && <Button size="small" color="error" startIcon={<DeleteOutlineRounded/>} onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: selected }) }}>Move to Deleted Entries</Button>}
    </Paper>}

    <ErrorMessage message={registerError}/>
    {registerLoading && !register.length
      ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
      : <DataTable
        rows={register}
        columns={registerColumns}
        rowKey="id"
        searchPlaceholder={showDeleted ? 'Search deleted LIH days by date, well, AFE or amount…' : 'Search LIH days by date, well, AFE or amount…'}
        exportName={showDeleted ? 'lih-register-deleted' : 'lih-register'}
        canExport={can('daily-cost:export')}
        onExport={(format, count) => exportAudit(format, count, showDeleted ? 'deleted' : 'register')}
        selectable={showDeleted ? can('daily-cost:restore') || can('daily-cost:permanent-delete') : can('daily-cost:delete')}
        onSelectionChange={setSelected}
      />}
    {!registerLoading && !register.length && <Typography color="text.secondary" fontSize={12.5} mt={1.2}>
      {showDeleted ? 'There are no deleted LIH register entries.' : 'No LIH register entries yet. Choose a rig, well and date above, then use Add items.'}
    </Typography>}

    <FormDialog
      open={Boolean(pending)}
      title={actionTitle}
      subtitle={actionSubtitle}
      onClose={() => { if (!actionBusy) setPending(null) }}
      onSubmit={() => void act()}
      busy={actionBusy}
      submitLabel={pending?.kind === 'purge' ? 'Delete permanently' : pending?.kind === 'restore' ? 'Restore' : 'Move to Deleted Entries'}
      danger={pending?.kind === 'purge'}
    >
      <Box display="grid" gap={1.2}>
        {pending?.kind === 'purge' && <Alert severity="warning">Permanent deletion cannot be undone.</Alert>}
        {pending?.kind === 'delete' && <Alert severity="info">The register day moves to Deleted Entries and no longer counts towards the AFE deduction.</Alert>}
        <ErrorMessage message={actionError}/>
      </Box>
    </FormDialog>

    <Menu
      anchorEl={sheetExportAnchor}
      open={Boolean(sheetExportAnchor)}
      onClose={() => setSheetExportAnchor(null)}
    >
      <MenuItem onClick={() => void exportSheet('csv')}>Export sheet as CSV</MenuItem>
      <MenuItem onClick={() => void exportSheet('xlsx')}>Export sheet as Excel (.xlsx)</MenuItem>
      <MenuItem onClick={() => void exportSheet('pdf')}>Export sheet as PDF</MenuItem>
    </Menu>

    {leaveGuard}
  </>
}

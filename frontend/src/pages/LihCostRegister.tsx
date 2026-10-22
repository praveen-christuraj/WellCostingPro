import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AddRounded, DeleteForeverOutlined, DeleteOutlineRounded, EditOutlined, EventNoteOutlined,
  FilterAltOffOutlined, OpenInNewRounded, RestoreRounded, RefreshRounded, SaveOutlined,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, Divider, IconButton, MenuItem, Paper, TextField, Tooltip, Typography,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag, useUnsavedChangesGuard } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { dailyMoney, displayDate, localToday } from '../lib/dailyCost'
import {
  EMPTY_LIH_LINE, lihLinePayload, lihLineTotal, lihMeasure, lihQuery,
  type LihCostDay, type LihCostEntry, type LihCostLine, type LihCostLineInput,
  type LihCostReference,
} from '../lib/lihCost'

type PendingAction = { kind: 'delete' | 'restore' | 'purge' | 'delete-line'; rows: LihCostEntry[]; line?: LihCostLine }
type LineEditor = { mode: 'add' | 'edit'; id?: string; values: LihCostLineInput }

function numberOrBlank(value: string): string {
  return value
}

function validateLine(values: LihCostLineInput): string {
  if (!values.item_description.trim()) return 'Item description is mandatory.'
  const units = Number(values.no_of_units)
  if (!values.no_of_units.trim() || !Number.isFinite(units) || units <= 0) return 'No of units must be a number greater than zero.'
  if (!values.unit_cost.trim() || !Number.isFinite(Number(values.unit_cost)) || Number(values.unit_cost) < 0) {
    return 'Unit cost is mandatory and cannot be negative.'
  }
  for (const [label, raw] of [
    ['OD size', values.od_size], ['ID size', values.id_size], ['Fish neck OD', values.fish_neck_od],
    ['Fish neck length', values.fish_neck_length], ['Length', values.length],
  ]) {
    const value = raw ?? ''
    if (value.trim() === '') continue
    const parsed = Number(value)
    if (!Number.isFinite(parsed) || parsed < 0) return `${label} must be a number that is zero or more, or left blank.`
  }
  return ''
}

function lineFromSaved(line: LihCostLine): LihCostLineInput {
  return {
    item_description: line.item_description,
    od_size: line.od_size ?? '',
    id_size: line.id_size ?? '',
    fish_neck_od: line.fish_neck_od ?? '',
    fish_neck_length: line.fish_neck_length ?? '',
    serial_number: line.serial_number,
    connection: line.connection,
    length: line.length ?? '',
    no_of_units: String(Number(line.no_of_units)),
    unit: line.unit,
    unit_cost: String(Number(line.unit_cost)),
    remarks: line.remarks,
  }
}

export default function LihCostRegister() {
  const { can } = useAuth()
  const [reference, setReference] = useState<LihCostReference | null>(null)
  const [referenceError, setReferenceError] = useState('')
  const [register, setRegister] = useState<LihCostEntry[]>([])
  const [registerLoading, setRegisterLoading] = useState(true)
  const [registerError, setRegisterError] = useState('')
  const [showDeleted, setShowDeleted] = useState(false)
  const [notice, setNotice] = useState('')

  const [rigId, setRigId] = useState('')
  const [wellId, setWellId] = useState('')
  const [afeId, setAfeId] = useState('')
  const [costDate, setCostDate] = useState(localToday())
  const [day, setDay] = useState<LihCostDay | null>(null)
  const [dayLoading, setDayLoading] = useState(false)
  const [dayError, setDayError] = useState('')
  const [editor, setEditor] = useState<LineEditor | null>(null)
  const [savingLine, setSavingLine] = useState(false)
  const [lineError, setLineError] = useState('')
  const [remarks, setRemarks] = useState('')
  const [savingRemarks, setSavingRemarks] = useState(false)
  const [remarksNotice, setRemarksNotice] = useState('')

  const [filterRig, setFilterRig] = useState('')
  const [filterWell, setFilterWell] = useState('')
  const [filterAfe, setFilterAfe] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [selected, setSelected] = useState<LihCostEntry[]>([])
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState('')

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
      setRemarks(result?.entry.remarks ?? '')
      setRemarksNotice('')
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
  const remarksDirty = Boolean(day) && remarks !== day?.entry.remarks

  // The rig select narrows the well list; the well select resets an incompatible AFE.
  const chooseRig = (value: string) => {
    setRigId(value)
    const nextWells = reference?.wells.filter(well => !value || well.rig_id === value) ?? []
    if (!nextWells.some(well => well.id === wellId)) {
      const first = nextWells[0]
      setWellId(first?.id ?? '')
      setAfeId(reference?.afes.find(afe => afe.well_id === first?.id)?.id ?? '')
    }
  }
  const chooseWell = (value: string) => {
    setWellId(value)
    setAfeId(reference?.afes.find(afe => afe.well_id === value)?.id ?? '')
  }

  const saveRemarks = async (): Promise<boolean> => {
    if (!day) return true
    setSavingRemarks(true)
    setRemarksNotice('')
    try {
      const updated = await api<LihCostDay>(`/lih-cost/entries/${day.entry.id}`, {
        method: 'PUT', body: body({ remarks }),
      })
      setDay(updated)
      setRemarks(updated.entry.remarks)
      setRemarksNotice('Day remarks saved.')
      await loadRegister()
      return true
    } catch (caught) {
      setRemarksNotice(caught instanceof Error ? caught.message : 'The day remarks could not be saved')
      return false
    } finally {
      setSavingRemarks(false)
    }
  }
  const leaveGuard = useUnsavedChangesGuard({
    when: remarksDirty,
    onSave: saveRemarks,
    title: 'Leave with unsaved LIH remarks?',
    message: 'The remarks on this LIH register day are not saved yet. Save them before leaving, or discard them deliberately.',
  })

  const openAdd = () => {
    setLineError('')
    setEditor({ mode: 'add', values: { ...EMPTY_LIH_LINE, unit: reference?.uoms[0]?.code ?? '' } })
  }
  const openEdit = (line: LihCostLine) => {
    setLineError('')
    setEditor({ mode: 'edit', id: line.id, values: lineFromSaved(line) })
  }

  const submitLine = async () => {
    if (!editor) return
    const problem = validateLine(editor.values)
    if (problem) { setLineError(problem); return }
    setSavingLine(true)
    setLineError('')
    try {
      let entryId = day?.entry.id
      if (!entryId) {
        const created = await api<LihCostDay>('/lih-cost/entries', {
          method: 'POST',
          body: body({
            well_id: wellId,
            rig_id: rigId,
            afe_id: selectedAfe?.id ?? '',
            cost_date: costDate,
          }),
        })
        entryId = created.entry.id
        setDay(created)
      }
      const updated = editor.mode === 'edit' && editor.id
        ? await api<LihCostDay>(`/lih-cost/entries/${entryId}/lines/${editor.id}`, {
            method: 'PUT', body: body(lihLinePayload(editor.values)),
          })
        : await api<LihCostDay>(`/lih-cost/entries/${entryId}/lines`, {
            method: 'POST', body: body(lihLinePayload(editor.values)),
          })
      setDay(updated)
      setRemarks(updated.entry.remarks)
      setNotice(editor.mode === 'edit' ? 'LIH item updated.' : 'LIH item added to the register.')
      setEditor(null)
      await loadRegister()
    } catch (caught) {
      setLineError(caught instanceof Error ? caught.message : 'The LIH item could not be saved')
    } finally {
      setSavingLine(false)
    }
  }

  const act = async () => {
    if (!pending) return
    setActionBusy(true)
    setActionError('')
    try {
      const ids = pending.rows.map(row => row.id)
      if (pending.kind === 'delete-line' && day && pending.line) {
        const updated = await api<LihCostDay>(`/lih-cost/entries/${day.entry.id}/lines/${pending.line.id}`, { method: 'DELETE' })
        setDay(updated)
        setNotice('LIH item removed from the register.')
      } else if (pending.kind === 'delete') {
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
    setRigId(entry.rig_id)
    setWellId(entry.well_id)
    setAfeId(entry.afe_id ?? '')
    setCostDate(entry.cost_date)
  }

  const exportAudit = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number, module: 'register' | 'deleted' | 'day') => {
    if (!can('daily-cost:export')) return
    await api('/lih-cost/export-audit', {
      method: 'POST',
      body: body({
        module, format, record_count: recordCount, include_deleted: showDeleted,
        well_id: wellId || filterWell, entry_id: day?.entry.id ?? '',
      }),
    })
  }

  const lineColumns = useMemo<ColDef<LihCostLine>[]>(() => [
    { headerName: 'ITEM DESCRIPTION', field: 'item_description', minWidth: 240, flex: 1.2 },
    { headerName: 'OD', field: 'od_size', minWidth: 95, valueFormatter: params => lihMeasure(params.value as string | null) },
    { headerName: 'ID', field: 'id_size', minWidth: 95, valueFormatter: params => lihMeasure(params.value as string | null) },
    { headerName: 'FISH NECK OD', field: 'fish_neck_od', minWidth: 130, valueFormatter: params => lihMeasure(params.value as string | null) },
    { headerName: 'FISH NECK LENGTH', field: 'fish_neck_length', minWidth: 150, valueFormatter: params => lihMeasure(params.value as string | null) },
    { headerName: 'SERIAL NUMBER', field: 'serial_number', minWidth: 140, valueFormatter: params => String(params.value || '—') },
    { headerName: 'CONNECTION', field: 'connection', minWidth: 130, valueFormatter: params => String(params.value || '—') },
    { headerName: 'LENGTH', field: 'length', minWidth: 105, valueFormatter: params => lihMeasure(params.value as string | null) },
    { headerName: 'UNITS', field: 'no_of_units', minWidth: 95, valueFormatter: params => lihMeasure(params.value as string) },
    { headerName: 'UNIT', field: 'unit', minWidth: 90, valueFormatter: params => String(params.value || '—') },
    { headerName: 'UNIT COST', field: 'unit_cost', minWidth: 140, valueFormatter: params => dailyMoney(params.value as string, dayCurrency) },
    {
      headerName: 'TOTAL COST', field: 'total_cost', minWidth: 150,
      cellRenderer: (params: ICellRendererParams<LihCostLine>) => <Typography fontSize={12} fontWeight={800}>{dailyMoney(params.data?.total_cost, dayCurrency)}</Typography>,
    },
    { headerName: 'REMARKS', field: 'remarks', minWidth: 220, flex: 1, valueFormatter: params => String(params.value || '—') },
    ...(can('daily-cost:update') || can('daily-cost:delete') ? [{
      headerName: 'ACTIONS',
      colId: 'actions',
      minWidth: 110,
      sortable: false,
      filter: false,
      cellRenderer: (params: ICellRendererParams<LihCostLine>) => {
        const line = params.data
        if (!line) return null
        return <Box display="flex" gap={.4}>
          {can('daily-cost:update') && <Tooltip title="Edit item"><IconButton size="small" aria-label="Edit LIH item" onClick={() => openEdit(line)}><EditOutlined sx={{ fontSize: 17 }}/></IconButton></Tooltip>}
          {can('daily-cost:delete') && <Tooltip title="Remove item"><IconButton size="small" color="error" aria-label="Remove LIH item" onClick={() => { setActionError(''); setPending({ kind: 'delete-line', rows: [], line }) }}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton></Tooltip>}
        </Box>
      },
    } as ColDef<LihCostLine>] : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [can, dayCurrency])

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
      minWidth: 120,
      sortable: false,
      filter: false,
      cellRenderer: (params: ICellRendererParams<LihCostEntry>) => {
        const entry = params.data
        if (!entry) return null
        return <Box display="flex" gap={.4}>
          <Tooltip title="Open this LIH day"><IconButton size="small" aria-label="Open LIH day" onClick={() => openRegisterDay(entry)}><OpenInNewRounded sx={{ fontSize: 17 }}/></IconButton></Tooltip>
          {!showDeleted && can('daily-cost:delete') && <Tooltip title="Move to Deleted Entries"><IconButton size="small" color="error" aria-label="Delete LIH day" onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: [entry] }) }}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton></Tooltip>}
          {showDeleted && can('daily-cost:restore') && <Tooltip title="Restore"><IconButton size="small" aria-label="Restore LIH day" onClick={() => { setActionError(''); setPending({ kind: 'restore', rows: [entry] }) }}><RestoreRounded sx={{ fontSize: 17 }}/></IconButton></Tooltip>}
          {showDeleted && can('daily-cost:permanent-delete') && <Tooltip title="Delete permanently"><IconButton size="small" color="error" aria-label="Permanently delete LIH day" onClick={() => { setActionError(''); setPending({ kind: 'purge', rows: [entry] }) }}><DeleteForeverOutlined sx={{ fontSize: 17 }}/></IconButton></Tooltip>}
        </Box>
      },
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [can, showDeleted])

  const actionTitle = pending?.kind === 'purge' ? 'Delete this LIH day permanently?'
    : pending?.kind === 'restore' ? 'Restore this LIH day?'
    : pending?.kind === 'delete-line' ? 'Remove this LIH item?' : 'Move this LIH day to Deleted Entries?'
  const actionSubtitle = pending?.kind === 'delete-line'
    ? pending?.line?.item_description
    : pending?.rows.length === 1 ? pending.rows[0].display_name : `${pending?.rows.length ?? 0} register days selected`

  return <>
    <PageHeading
      eyebrow="DAILY COST MANAGEMENT / LIH COST REGISTER"
      title="LIH Cost Register"
      subtitle="Record Lost In Hole cost item by item against a rig, well and date. LIH is accounted separately, added to the actual cost and deducted explicitly from the AFE total."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button variant="outlined" startIcon={<RefreshRounded/>} disabled={registerLoading} onClick={() => { void loadRegister(); void loadDay(wellId, costDate) }}>
          {registerLoading ? 'Refreshing…' : 'Refresh'}
        </Button>
        <Button variant="outlined" startIcon={showDeleted ? <EventNoteOutlined/> : <DeleteOutlineRounded/>} onClick={() => { setShowDeleted(value => !value); setNotice('') }}>
          {showDeleted ? 'Active register' : 'Deleted entries'}
        </Button>
      </Box>}
    />
    <ErrorMessage message={referenceError}/>
    {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}

    <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, mb: 1.8 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" mb={1.3}>
        <Box>
          <Typography fontWeight={800} fontSize={15}>Select the LIH day</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25}>
            Choose the rig and its well, then the date the LIH cost belongs to.
          </Typography>
        </Box>
        {day && <Tag tone={day.entry.afe_id ? 'info' : 'warning'}>{day.entry.afe_id ? `Deducted from ${day.entry.afe_code}` : 'No AFE on this well'}</Tag>}
      </Box>
      <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: '1fr', md: '1fr 1.3fr .9fr .9fr' } }} alignItems="center">
        <TextField select label="Rig" value={rigId} onChange={event => chooseRig(event.target.value)} helperText="Rigs in this workspace">
          <MenuItem value="">All rigs</MenuItem>
          {(reference?.rigs ?? []).map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <TextField select required label="Well" value={wellId} onChange={event => chooseWell(event.target.value)} disabled={!wellsForRig.length}
          helperText={selectedWell ? `${selectedWell.well_code} · ${selectedWell.well_name}` : 'Choose the well the LIH cost belongs to'}>
          {wellsForRig.map(well => <MenuItem key={well.id} value={well.id}>{well.display_name}</MenuItem>)}
        </TextField>
        <TextField required type="date" label="LIH date" value={costDate} onChange={event => setCostDate(event.target.value)} InputLabelProps={{ shrink: true }}/>
        {afesForWell.length > 1
          ? <TextField select label="AFE" value={afeId || afesForWell[0]?.id || ''} onChange={event => setAfeId(event.target.value)}
              helperText="Each AFE deducts its own LIH cost">
              {afesForWell.map(afe => <MenuItem key={afe.id} value={afe.id}>{afe.display_name}</MenuItem>)}
            </TextField>
          : <TextField label="AFE" value={selectedAfe ? `${selectedAfe.afe_code} · ${selectedAfe.afe_name}` : 'No AFE yet'} InputProps={{ readOnly: true }}
              helperText={selectedAfe ? `Standard currency ${selectedAfe.standard_currency}` : 'Recorded in the workspace default currency'}/>}
      </Box>
      {afesForWell.length > 1 && <Alert severity="info" sx={{ mt: 1.3, py: .4 }}>
        This well has {afesForWell.length} AFEs. The LIH cost is deducted from the AFE selected above only.
      </Alert>}
      {!wellId && <Alert severity="info" sx={{ mt: 1.3, py: .4 }}>Choose a rig and well to open its LIH register.</Alert>}
    </Paper>

    <ErrorMessage message={dayError}/>
    {wellId && dayLoading && <Box py={4} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={24}/></Box>}

    {wellId && !dayLoading && day && <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, mb: 1.8 }}>
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" gap={1} flexWrap="wrap" mb={1.4}>
        <Box>
          <Typography fontWeight={800} fontSize={15}>{day.entry.well_code} · LIH cost on {displayDate(day.entry.cost_date)}</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25}>
            {day.entry.rig_code} · {day.entry.rig_name} · {day.entry.afe_code || 'No AFE'} · recorded in {day.entry.currency}
          </Typography>
        </Box>
        <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
          {can('daily-cost:create') && <Button variant="contained" size="small" startIcon={<AddRounded/>} onClick={openAdd}>Add item</Button>}
          {can('daily-cost:delete') && <Button size="small" color="error" variant="outlined" startIcon={<DeleteOutlineRounded/>} onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: [day.entry] }) }}>Delete day</Button>}
        </Box>
      </Box>
      <Box display="grid" gap={1.1} mb={1.6} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' } }}>
        <Box sx={{ p: 1.2, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
          <Typography fontSize={10.5} fontWeight={800} letterSpacing={.6} color="text.secondary">TOTAL LIH COST</Typography>
          <Typography fontSize={21} fontWeight={800} mt={.4}>{dailyMoney(day.entry.total_cost, day.entry.currency)}</Typography>
          <Typography fontSize={11} color="text.secondary">{day.entry.line_count} item{day.entry.line_count === 1 ? '' : 's'} on this day</Typography>
        </Box>
        <Box sx={{ p: 1.2, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
          <Typography fontSize={10.5} fontWeight={800} letterSpacing={.6} color="text.secondary">AFE THE COST IS FILED AGAINST</Typography>
          <Typography fontSize={13.5} fontWeight={800} mt={.6}>{day.entry.afe_code || 'No AFE'}</Typography>
          <Typography fontSize={11} color="text.secondary">{day.entry.afe_name || 'Reported at well level'}</Typography>
        </Box>
        <Box sx={{ p: 1.2, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
          <Typography fontSize={10.5} fontWeight={800} letterSpacing={.6} color="text.secondary">ACCOUNTING TREATMENT</Typography>
          <Typography fontSize={13.5} fontWeight={800} mt={.6}>Added to actual</Typography>
          <Typography fontSize={11} color="text.secondary">Deducted from the AFE total, never budgeted</Typography>
        </Box>
        <Box sx={{ p: 1.2, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
          <Typography fontSize={10.5} fontWeight={800} letterSpacing={.6} color="text.secondary">LAST UPDATED</Typography>
          <Typography fontSize={13.5} fontWeight={800} mt={.6}>{day.entry.updated_by || '—'}</Typography>
          <Typography fontSize={11} color="text.secondary">{day.entry.updated_at ? new Date(day.entry.updated_at).toLocaleString() : '—'}</Typography>
        </Box>
      </Box>

      <DataTable
        rows={day.lines}
        columns={lineColumns}
        rowKey="id"
        searchPlaceholder="Search LIH items by description, serial number, connection or remarks…"
        exportName={`lih-items-${day.entry.well_code}-${day.entry.cost_date}`}
        canExport={can('daily-cost:export')}
        onExport={(format, count) => exportAudit(format, count, 'day')}
      />
      {!day.lines.length && <Typography color="text.secondary" fontSize={12.5} mt={1.3}>
        No LIH items yet. Use <strong>Add item</strong> to record the first item under {displayDate(day.entry.cost_date)}.
      </Typography>}

      <Divider sx={{ my: 1.6 }}/>
      <Box display="flex" alignItems="flex-start" gap={1} flexWrap="wrap">
        <TextField
          fullWidth
          label="Day remarks"
          value={remarks}
          onChange={event => { setRemarks(event.target.value); setRemarksNotice('') }}
          disabled={!can('daily-cost:update')}
          multiline
          minRows={2}
          inputProps={{ maxLength: 1000 }}
          helperText={remarksDirty ? 'Unsaved remarks — save them or discard your change.' : 'Context for this LIH day, for example the fishing job or failure.'}
          sx={{ flex: '1 1 420px' }}
        />
        {can('daily-cost:update') && <Box display="flex" gap={1} mt={.4}>
          <Button variant="contained" startIcon={<SaveOutlined/>} disabled={!remarksDirty || savingRemarks} onClick={() => void saveRemarks()}>
            {savingRemarks ? 'Saving…' : 'Save remarks'}
          </Button>
          <Button variant="outlined" disabled={!remarksDirty || savingRemarks} onClick={() => { setRemarks(day.entry.remarks); setRemarksNotice('') }}>Discard</Button>
        </Box>}
      </Box>
      {remarksNotice && <Alert severity={remarksNotice === 'Day remarks saved.' ? 'success' : 'error'} sx={{ mt: 1.2, py: .4 }} onClose={() => setRemarksNotice('')}>{remarksNotice}</Alert>}
    </Paper>}

    {wellId && !dayLoading && !day && !dayError && <Paper variant="outlined" sx={{ p: 2.4, borderRadius: 2, mb: 1.8, textAlign: 'center' }}>
      <Typography fontWeight={800} fontSize={14.5}>No LIH register for {selectedWell?.well_code ?? 'this well'} on {displayDate(costDate)}</Typography>
      <Typography color="text.secondary" fontSize={12} mt={.5} mb={1.6}>
        Add the first item and the day is created automatically under {selectedAfe?.afe_code ? `AFE ${selectedAfe.afe_code}` : 'the well'}.
      </Typography>
      {can('daily-cost:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openAdd} disabled={!costDate}>Add LIH item</Button>}
    </Paper>}

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
      {showDeleted ? 'There are no deleted LIH register entries.' : 'No LIH register entries yet. Choose a rig, well and date above, then add the first item.'}
    </Typography>}

    <FormDialog
      open={Boolean(editor)}
      title={editor?.mode === 'edit' ? 'Edit LIH item' : 'Add LIH item'}
      subtitle={day
        ? `${day.entry.well_code} · ${displayDate(day.entry.cost_date)} · amounts in ${day.entry.currency}. Total cost is calculated as No of units × Unit cost.`
        : `${selectedWell?.well_code ?? 'Well'} · ${displayDate(costDate)}. The LIH day is created when the first item is saved.`}
      onClose={() => { setEditor(null); setLineError('') }}
      onSubmit={() => void submitLine()}
      busy={savingLine}
      submitLabel={editor?.mode === 'edit' ? 'Save item' : 'Add item'}
      maxWidth="lg"
      submitDisabled={Boolean(editor && validateLine(editor.values))}
    >
      {editor && <Box display="grid" gap={1.5}>
        <TextField
          required
          label="Item description"
          value={editor.values.item_description}
          onChange={event => setEditor(current => current && ({ ...current, values: { ...current.values, item_description: event.target.value } }))}
          inputProps={{ maxLength: 300 }}
          helperText="What was lost in hole (for example the tool or drill-string component and its size)."
        />
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(4, 1fr)' } }}>
          {([
            ['od_size', 'OD size'],
            ['id_size', 'ID size'],
            ['fish_neck_od', 'Fish neck OD'],
            ['fish_neck_length', 'Fish neck length'],
          ] as const).map(([key, label]) => <TextField
            key={key}
            type="number"
            label={label}
            value={editor.values[key]}
            onChange={event => setEditor(current => current && ({ ...current, values: { ...current.values, [key]: numberOrBlank(event.target.value) } }))}
            inputProps={{ min: 0, step: 'any' }}
          />)}
        </Box>
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' } }}>
          <TextField label="Serial number" value={editor.values.serial_number} onChange={event => setEditor(current => current && ({ ...current, values: { ...current.values, serial_number: event.target.value } }))} inputProps={{ maxLength: 100 }}/>
          <TextField label="Connection" value={editor.values.connection} onChange={event => setEditor(current => current && ({ ...current, values: { ...current.values, connection: event.target.value } }))} inputProps={{ maxLength: 100 }}/>
          <TextField type="number" label="Length" value={editor.values.length} onChange={event => setEditor(current => current && ({ ...current, values: { ...current.values, length: event.target.value } }))} inputProps={{ min: 0, step: 'any' }}/>
        </Box>
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(4, 1fr)' } }}>
          <TextField
            required type="number" label="No of units" value={editor.values.no_of_units}
            onChange={event => setEditor(current => current && ({ ...current, values: { ...current.values, no_of_units: event.target.value } }))}
            inputProps={{ min: 0.0000000001, step: 'any' }}
            error={Boolean(editor.values.no_of_units) && !(Number(editor.values.no_of_units) > 0)}
          />
          <TextField select label="Unit (UOM)" value={editor.values.unit} onChange={event => setEditor(current => current && ({ ...current, values: { ...current.values, unit: event.target.value } }))}
            helperText={reference?.uoms.length ? 'From Master Data UOM' : 'Add UOM entries in Master Data'}>
            <MenuItem value="">Not specified</MenuItem>
            {(reference?.uoms ?? []).map(uom => <MenuItem key={uom.code} value={uom.code}>{uom.display_name}</MenuItem>)}
          </TextField>
          <TextField
            required type="number" label="Unit cost" value={editor.values.unit_cost}
            onChange={event => setEditor(current => current && ({ ...current, values: { ...current.values, unit_cost: event.target.value } }))}
            inputProps={{ min: 0, step: 'any' }}
            error={editor.values.unit_cost !== '' && !(Number(editor.values.unit_cost) >= 0)}
            helperText={`Currency ${dayCurrency || 'from the AFE'}`}
          />
          <TextField label="Total cost (calculated)" value={dailyMoney(lihLineTotal(editor.values), dayCurrency)} InputProps={{ readOnly: true }}
            helperText="No of units × Unit cost" sx={{ '& input': { fontWeight: 800 } }}/>
        </Box>
        <TextField
          label="Remarks" multiline minRows={2} value={editor.values.remarks}
          onChange={event => setEditor(current => current && ({ ...current, values: { ...current.values, remarks: event.target.value } }))}
          inputProps={{ maxLength: 500 }}
        />
        <ErrorMessage message={lineError}/>
      </Box>}
    </FormDialog>

    <FormDialog
      open={Boolean(pending)}
      title={actionTitle}
      subtitle={actionSubtitle}
      onClose={() => { if (!actionBusy) setPending(null) }}
      onSubmit={() => void act()}
      busy={actionBusy}
      submitLabel={pending?.kind === 'purge' ? 'Delete permanently' : pending?.kind === 'restore' ? 'Restore' : pending?.kind === 'delete-line' ? 'Remove item' : 'Move to Deleted Entries'}
      danger={pending?.kind === 'purge' || pending?.kind === 'delete-line'}
    >
      <Box display="grid" gap={1.2}>
        {pending?.kind === 'purge' && <Alert severity="warning">Permanent deletion cannot be undone.</Alert>}
        {pending?.kind === 'delete-line' && <Alert severity="info">The item total is removed from this day's LIH cost immediately.</Alert>}
        {pending?.kind === 'delete' && <Alert severity="info">The register day moves to Deleted Entries and no longer counts towards the AFE deduction.</Alert>}
        <ErrorMessage message={actionError}/>
      </Box>
    </FormDialog>

    {leaveGuard}
  </>
}

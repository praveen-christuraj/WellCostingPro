import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AddRounded, DeleteForeverOutlined, DeleteOutlineRounded, EventNoteOutlined, FilterAltOffOutlined,
  OpenInNewRounded, RefreshRounded, RestoreRounded, StorefrontOutlined,
  UploadFileRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, IconButton, MenuItem, Paper, TextField, Tooltip, Typography,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { FuelConsumptionDialog } from '../components/fuel-cost/FuelConsumptionDialog'
import { FuelCompanyDialog } from '../components/fuel-cost/FuelCompanyDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { displayDate, localToday } from '../lib/dailyCost'
import type { ImportRow } from '../lib/export'
import {
  FUEL_IMPORT_OPTIONAL_HEADERS, FUEL_IMPORT_REQUIRED_HEADERS, FUEL_IMPORT_SAMPLE, fuelImportRow, fuelLitres,
  fuelNumber, fuelQuery, fuelShare, fuelSavePayload,
  type FuelCostCompanyConsumption, type FuelCostDay, type FuelCostEntry,
  type FuelCostImportResponse, type FuelCostReference,
} from '../lib/fuelCost'

type PendingAction = { kind: 'delete' | 'restore' | 'purge'; rows: FuelCostEntry[] }
type ClassificationRow = FuelCostCompanyConsumption['rows'][number] & { row_key: string }
type BalanceLitresKey =
  | 'opening_stock' | 'receipt' | 'rig_engine_consumption' | 'company_consumption'
  | 'book_closing_stock' | 'actual_closing_stock'

export default function FuelCostRegister() {
  const { can } = useAuth()

  const [reference, setReference] = useState<FuelCostReference | null>(null)
  const [referenceError, setReferenceError] = useState('')
  const [notice, setNotice] = useState('')

  const [rigId, setRigId] = useState('')
  const [costDate, setCostDate] = useState(localToday())
  const [day, setDay] = useState<FuelCostDay | null>(null)
  const [dayLoading, setDayLoading] = useState(false)
  const [dayError, setDayError] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [companiesOpen, setCompaniesOpen] = useState(false)

  const [register, setRegister] = useState<FuelCostEntry[]>([])
  const [registerLoading, setRegisterLoading] = useState(false)
  const [registerError, setRegisterError] = useState('')
  const [showDeleted, setShowDeleted] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [selected, setSelected] = useState<FuelCostEntry[]>([])
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  const [classification, setClassification] = useState<FuelCostCompanyConsumption | null>(null)
  const [classificationLoading, setClassificationLoading] = useState(false)
  const [classificationError, setClassificationError] = useState('')

  const [importOpen, setImportOpen] = useState(false)

  const canCreate = can('daily-cost:create')
  const canUpdate = can('daily-cost:update')
  const canImport = can('daily-cost:import')
  const canOverrideOpening = can('daily-cost:fuel-opening-stock')
  const canManageCompanies = can('daily-cost:create') || can('daily-cost:update') || can('daily-cost:delete')

  const rig = useMemo(() => reference?.rigs.find(item => item.id === rigId) ?? null, [reference, rigId])
  const companies = reference?.companies ?? []
  const rangeQuery = fuelQuery({ rig_id: rigId, from: dateFrom, to: dateTo })

  const loadReference = useCallback(async () => {
    try {
      setReference(await api<FuelCostReference>('/fuel-cost/reference'))
      setReferenceError('')
    } catch (caught) {
      setReferenceError(caught instanceof Error ? caught.message : 'The fuel register reference data could not be loaded')
    }
  }, [])

  useEffect(() => { void loadReference() }, [loadReference])

  // The page is rig-scoped, so a rig is always selected when one exists.
  useEffect(() => {
    if (!reference) return
    if (!rigId && reference.rigs.length) setRigId(reference.rigs[0].id)
  }, [reference, rigId])

  const loadDay = useCallback(async (rig: string, date: string) => {
    if (!rig || !date) { setDay(null); return }
    setDayLoading(true)
    setDayError('')
    try {
      setDay(await api<FuelCostDay>(`/fuel-cost/day${fuelQuery({ rig_id: rig, date })}`))
    } catch (caught) {
      setDay(null)
      setDayError(caught instanceof Error ? caught.message : 'This fuel day could not be loaded')
    } finally {
      setDayLoading(false)
    }
  }, [])

  useEffect(() => { void loadDay(rigId, costDate) }, [rigId, costDate, loadDay])

  const loadRegister = useCallback(async () => {
    if (!rigId) { setRegister([]); return }
    setRegisterLoading(true)
    setRegisterError('')
    setSelected([])
    try {
      const path = showDeleted ? '/fuel-cost/entries/deleted' : '/fuel-cost/entries'
      setRegister(await api<FuelCostEntry[]>(`${path}${rangeQuery}`))
    } catch (caught) {
      setRegisterError(caught instanceof Error ? caught.message : 'The fuel register could not be loaded')
    } finally {
      setRegisterLoading(false)
    }
  }, [rangeQuery, rigId, showDeleted])

  useEffect(() => { void loadRegister() }, [loadRegister])

  const loadClassification = useCallback(async () => {
    if (!rigId) { setClassification(null); return }
    setClassificationLoading(true)
    setClassificationError('')
    try {
      setClassification(await api<FuelCostCompanyConsumption>(
        `/fuel-cost/rigs/${rigId}/company-consumption${fuelQuery({ from: dateFrom, to: dateTo })}`,
      ))
    } catch (caught) {
      setClassification(null)
      setClassificationError(caught instanceof Error ? caught.message : 'The company consumption could not be loaded')
    } finally {
      setClassificationLoading(false)
    }
  }, [dateFrom, dateTo, rigId])

  useEffect(() => {
    if (showDeleted) return
    void loadClassification()
  }, [loadClassification, showDeleted])

  const filtersActive = Boolean(dateFrom || dateTo)
  const activeDays = register.filter(entry => !entry.is_deleted)
  const totals = useMemo(() => {
    const sum = (pick: (entry: FuelCostEntry) => string) => activeDays.reduce((total, entry) => total + fuelNumber(pick(entry)), 0)
    const latest = [...activeDays].sort((left, right) => right.cost_date.localeCompare(left.cost_date))[0] ?? null
    return {
      days: activeDays.length,
      totalAgo: sum(entry => entry.balance.total_consumption),
      engine: sum(entry => entry.balance.rig_engine_consumption),
      companies: sum(entry => entry.balance.company_consumption),
      gas: sum(entry => entry.balance.gas_consumption),
      receipts: sum(entry => entry.balance.receipt),
      adjustments: sum(entry => entry.balance.adjustments),
      closing: latest ? fuelNumber(latest.balance.actual_closing_stock) : 0,
      closingDate: latest?.cost_date ?? '',
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [register])

  const openDialog = () => {
    if (!rig || !costDate) { setDayError('Choose a rig and a date before adding consumption.'); return }
    if (dayLoading) return
    setSaveError('')
    setDialogOpen(true)
  }

  const saveDay = async (payload: ReturnType<typeof fuelSavePayload>): Promise<boolean> => {
    if (!day) return false
    setSaving(true)
    setSaveError('')
    try {
      const saved = await api<FuelCostDay>(
        day.entry ? `/fuel-cost/entries/${day.entry.id}` : '/fuel-cost/entries',
        { method: day.entry ? 'PUT' : 'POST', body: body(payload) },
      )
      setDay(saved)
      setNotice(
        `Fuel day saved for ${saved.rig_code} on ${displayDate(saved.cost_date)} — AGO consumption `
        + `${fuelLitres(saved.balance.total_consumption)} L, closing stock ${fuelLitres(saved.balance.actual_closing_stock)} L`
        + (fuelNumber(saved.balance.adjustments) ? `, adjustments ${fuelLitres(saved.balance.adjustments)} L.` : '.'),
      )
      setDialogOpen(false)
      void loadRegister()
      void loadClassification()
      return true
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : 'The fuel day could not be saved')
      return false
    } finally {
      setSaving(false)
    }
  }

  const act = async () => {
    if (!pending) return
    setActionBusy(true)
    setActionError('')
    try {
      const ids = pending.rows.map(row => row.id)
      if (pending.kind === 'delete') {
        if (ids.length === 1) await api(`/fuel-cost/entries/${ids[0]}`, { method: 'DELETE' })
        else await api('/fuel-cost/entries/bulk-delete', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} fuel day${ids.length === 1 ? '' : 's'} moved to Deleted Entries.`)
      } else if (pending.kind === 'restore') {
        if (ids.length === 1) await api(`/fuel-cost/entries/${ids[0]}/restore`, { method: 'POST' })
        else await api('/fuel-cost/entries/bulk-restore', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} fuel day${ids.length === 1 ? '' : 's'} restored to the register.`)
      } else {
        if (ids.length === 1) await api(`/fuel-cost/entries/${ids[0]}/permanent`, { method: 'DELETE' })
        else await api('/fuel-cost/entries/bulk-permanent-delete', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} fuel day${ids.length === 1 ? '' : 's'} permanently deleted.`)
      }
      setPending(null)
      await loadRegister()
      if (!showDeleted) await loadDay(rigId, costDate)
      await loadClassification()
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'The requested action could not be completed')
    } finally {
      setActionBusy(false)
    }
  }

  const exportAudit = async (
    format: 'csv' | 'xlsx' | 'pdf', recordCount: number,
    module: 'register' | 'deleted' | 'company-consumption',
  ) => {
    if (!can('daily-cost:export')) return
    await api('/fuel-cost/export-audit', {
      method: 'POST',
      body: body({
        module,
        format,
        record_count: recordCount,
        rig_id: rigId,
        date_from: dateFrom || null,
        date_to: dateTo || null,
        include_deleted: showDeleted,
      }),
    })
  }

  const runImport = async (rows: ImportRow[]): Promise<string[]> => {
    try {
      const result = await api<FuelCostImportResponse>('/fuel-cost/import', {
        method: 'POST',
        body: body({ rig_id: rigId, rows: rows.map(fuelImportRow) }),
      })
      if (result.imported_count) {
        setNotice(
          `Imported ${result.imported_count} fuel day${result.imported_count === 1 ? '' : 's'} with `
          + `${result.line_count} company consumption line${result.line_count === 1 ? '' : 's'}.`,
        )
        await loadReference()
        await loadRegister()
        await loadDay(rigId, costDate)
        await loadClassification()
      }
      return result.errors
    } catch (caught) {
      return [caught instanceof Error ? caught.message : 'The fuel rows could not be imported']
    }
  }

  const openRegisterDay = (entry: FuelCostEntry) => {
    setShowDeleted(false)
    const changed = entry.rig_id !== rigId || entry.cost_date !== costDate
    setRigId(entry.rig_id)
    setCostDate(entry.cost_date)
    setSaveError('')
    if (changed) { setDay(null); setDayLoading(true) }
    setDialogOpen(true)
  }

  const registerColumns = useMemo<ColDef<FuelCostEntry>[]>(() => {
    const litresCell = (key: BalanceLitresKey) =>
      (params: ICellRendererParams<FuelCostEntry>) => <Typography fontSize={12}>
        {fuelLitres(params.data?.balance?.[key] ?? 0)}
      </Typography>
    return [
      {
        headerName: 'DATE', field: 'cost_date', minWidth: 125, width: 130,
        valueFormatter: params => displayDate(String(params.value ?? '')),
      },
      {
        headerName: 'RIG', field: 'rig_code', minWidth: 150,
        valueGetter: params => `${params.data?.rig_code ?? ''} · ${params.data?.rig_name ?? ''}`,
      },
      {
        headerName: 'OPENING STOCK', colId: 'opening_stock', minWidth: 130,
        valueGetter: params => fuelLitres(params.data?.balance?.opening_stock ?? 0),
        cellRenderer: litresCell('opening_stock'),
      },
      {
        headerName: 'OPENING ADJ.', colId: 'opening_adjustment', minWidth: 135,
        valueGetter: params => fuelLitres(params.data?.balance?.opening_adjustment ?? 0),
        cellRenderer: (params: ICellRendererParams<FuelCostEntry>) => <VarianceCell value={params.data?.balance?.opening_adjustment}/>,
      },
      {
        headerName: 'RECEIPT', colId: 'receipt', minWidth: 110,
        valueGetter: params => fuelLitres(params.data?.balance?.receipt ?? 0),
        cellRenderer: litresCell('receipt'),
      },
      {
        headerName: 'RIG ENGINE AGO', colId: 'rig_engine', minWidth: 145,
        valueGetter: params => fuelLitres(params.data?.balance?.rig_engine_consumption ?? 0),
        cellRenderer: litresCell('rig_engine_consumption'),
      },
      {
        headerName: 'COMPANY AGO', colId: 'company_ago', minWidth: 135,
        valueGetter: params => fuelLitres(params.data?.balance?.company_consumption ?? 0),
        cellRenderer: litresCell('company_consumption'),
      },
      {
        headerName: 'TOTAL AGO CONSUMED', colId: 'total_ago', minWidth: 165,
        valueGetter: params => `${fuelLitres(params.data?.balance?.total_consumption ?? 0)} L`,
        cellRenderer: (params: ICellRendererParams<FuelCostEntry>) => <Typography fontSize={12} fontWeight={800}>
          {fuelLitres(params.data?.balance?.total_consumption ?? 0)} L
        </Typography>,
      },
      {
        headerName: 'BOOK CLOSING', colId: 'book_closing', minWidth: 135,
        valueGetter: params => fuelLitres(params.data?.balance?.book_closing_stock ?? 0),
        cellRenderer: litresCell('book_closing_stock'),
      },
      {
        headerName: 'ACTUAL CLOSING', colId: 'actual_closing', minWidth: 145,
        valueGetter: params => `${fuelLitres(params.data?.balance?.actual_closing_stock ?? 0)} L`,
        cellRenderer: (params: ICellRendererParams<FuelCostEntry>) => <Typography fontSize={12} fontWeight={700}>
          {fuelLitres(params.data?.balance?.actual_closing_stock ?? 0)} L
        </Typography>,
      },
      {
        headerName: 'ADJUSTMENTS', colId: 'adjustments', minWidth: 130,
        valueGetter: params => fuelLitres(params.data?.balance?.adjustments ?? 0),
        cellRenderer: (params: ICellRendererParams<FuelCostEntry>) => <VarianceCell value={params.data?.balance?.adjustments}/>,
      },
      {
        headerName: 'GAS (SEPARATE)', colId: 'gas', minWidth: 140,
        valueGetter: params => `${fuelLitres(params.data?.balance?.gas_consumption ?? 0)} L`,
        cellRenderer: (params: ICellRendererParams<FuelCostEntry>) => <Typography fontSize={12} color="text.secondary">
          {fuelLitres(params.data?.balance?.gas_consumption ?? 0)} L
        </Typography>,
      },
      { headerName: 'REMARKS', field: 'remarks', minWidth: 200, flex: 1, valueFormatter: params => String(params.value || '—') },
      {
        headerName: 'ACTIONS', colId: 'actions', minWidth: 140, sortable: false, filter: false,
        cellRenderer: (params: ICellRendererParams<FuelCostEntry>) => {
          const entry = params.data
          if (!entry) return null
          return <Box display="flex" gap={.4} alignItems="center">
            {!showDeleted && <Button size="small" startIcon={<OpenInNewRounded sx={{ fontSize: 16 }}/>}
              onClick={() => openRegisterDay(entry)}>Open day</Button>}
            {!showDeleted && can('daily-cost:delete') && <Tooltip title="Move to Deleted Entries">
              <span><IconButton size="small" color="error" aria-label="Delete fuel day"
                onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: [entry] }) }}>
                <DeleteOutlineRounded sx={{ fontSize: 17 }}/>
              </IconButton></span>
            </Tooltip>}
            {showDeleted && can('daily-cost:restore') && <Tooltip title="Restore">
              <span><IconButton size="small" aria-label="Restore fuel day"
                onClick={() => { setActionError(''); setPending({ kind: 'restore', rows: [entry] }) }}>
                <RestoreRounded sx={{ fontSize: 17 }}/>
              </IconButton></span>
            </Tooltip>}
            {showDeleted && can('daily-cost:permanent-delete') && <Tooltip title="Delete permanently">
              <span><IconButton size="small" color="error" aria-label="Permanently delete fuel day"
                onClick={() => { setActionError(''); setPending({ kind: 'purge', rows: [entry] }) }}>
                <DeleteForeverOutlined sx={{ fontSize: 17 }}/>
              </IconButton></span>
            </Tooltip>}
          </Box>
        },
      },
    ]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [can, costDate, day, rigId, showDeleted])

  const classificationRows = useMemo<ClassificationRow[]>(
    () => (classification?.rows ?? []).map(row => ({
      ...row,
      row_key: `${row.company_id}:${row.category_id ?? 'none'}`,
    })),
    [classification],
  )

  const classificationColumns = useMemo<ColDef<ClassificationRow>[]>(() => [
    { headerName: 'COMPANY', field: 'company_name', minWidth: 220, flex: 1 },
    {
      headerName: 'CATEGORY', field: 'category_name', minWidth: 180,
      valueFormatter: params => String(params.value || 'Uncategorised'),
    },
    { headerName: 'DAYS', field: 'day_count', minWidth: 90, width: 100 },
    { headerName: 'LINES', field: 'line_count', minWidth: 90, width: 100 },
    {
      headerName: 'AGO CONSUMED (LITRES)', field: 'litres', minWidth: 185,
      cellRenderer: (params: ICellRendererParams<ClassificationRow>) => <Typography fontSize={12} fontWeight={800}>
        {fuelLitres(params.data?.litres ?? 0)} L
      </Typography>,
    },
    {
      headerName: 'SHARE OF RIG', colId: 'share', minWidth: 130,
      valueGetter: params => fuelShare(params.data?.litres, fuelNumber(classification?.total_litres)),
    },
  ], [classification])

  const actionTitle = pending?.kind === 'purge' ? 'Delete this fuel day permanently?'
    : pending?.kind === 'restore' ? 'Restore this fuel day?' : 'Move this fuel day to Deleted Entries?'
  const actionSubtitle = pending?.rows.length === 1 ? pending.rows[0].display_name : `${pending?.rows.length ?? 0} fuel days selected`

  return <>
    <PageHeading
      eyebrow="DAILY COST MANAGEMENT / FUEL COST REGISTER"
      title="Fuel Cost Register"
      subtitle="Record each rig's daily AGO consumption and gas, the physical opening and closing stock, receipts and the company-wise consumption. Opening stock is captured once and carried forward; the material balance and every adjustment are calculated automatically."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button variant="outlined" startIcon={<RefreshRounded/>} disabled={registerLoading || dayLoading}
          onClick={() => { void loadReference(); void loadRegister(); void loadDay(rigId, costDate); void loadClassification() }}>
          {registerLoading ? 'Refreshing…' : 'Refresh'}
        </Button>
        <Button variant="outlined" startIcon={<StorefrontOutlined/>} onClick={() => setCompaniesOpen(true)}>
          Companies &amp; categories
        </Button>
        {canImport && <Button variant="outlined" startIcon={<UploadFileRounded/>} onClick={() => setImportOpen(true)}
          disabled={!reference?.rigs.length}>
          Import
        </Button>}
        <Button variant="outlined" startIcon={showDeleted ? <EventNoteOutlined/> : <DeleteOutlineRounded/>}
          onClick={() => { setShowDeleted(value => !value); setNotice('') }}>
          {showDeleted ? 'Active register' : 'Deleted entries'}
        </Button>
      </Box>}
    />
    <ErrorMessage message={referenceError}/>
    {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}

    {!reference?.rigs.length && !referenceError && <Alert severity="info" sx={{ mb: 2 }}>
      No rig exists in this workspace yet. Create a rig in Rig &amp; Well Management before recording fuel consumption.
    </Alert>}

    {!showDeleted && <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, mb: 1.6 }}>
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" gap={1} flexWrap="wrap" mb={1.3}>
        <Box>
          <Typography fontWeight={800} fontSize={15}>Select the rig and the fuel date</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25} sx={{ maxWidth: 800 }}>
            Every consumption is booked against the selected rig. Open the dialog to record the rig engines, gas,
            stock, receipts and the company-wise AGO usage.
          </Typography>
        </Box>
        <Box display="flex" gap={.7} flexWrap="wrap" alignItems="center">
          {dayLoading && <CircularProgress size={16}/>}
          {day?.entry && <Tag tone="success">Day saved</Tag>}
          {day && !day.entry && <Tag tone="neutral">No entry for this date yet</Tag>}
          {day && (day.entry ? day.entry.balance.is_first_entry : day.balance.is_first_entry) &&
            <Tag tone="warning">First fuel entry for this rig</Tag>}
          {day?.entry && <Tag>Total AGO {fuelLitres(day.entry.balance.total_consumption)} L</Tag>}
          {day?.entry && <Tag>Closing {fuelLitres(day.entry.balance.actual_closing_stock)} L</Tag>}
          {day?.entry && fuelNumber(day.entry.balance.adjustments) !== 0 &&
            <Tag tone="warning">Adjustments {fuelLitres(day.entry.balance.adjustments)} L</Tag>}
        </Box>
      </Box>
      <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: '1fr', md: '1.3fr 1fr auto auto' } }} alignItems="center">
        <TextField select label="Rig" value={rigId} onChange={event => { setRigId(event.target.value); setSelected([]) }}
          helperText="Fuel consumption is always rig-scoped">
          {(reference?.rigs ?? []).map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}</MenuItem>)}
        </TextField>
        <TextField required type="date" label="Fuel date" value={costDate}
          onChange={event => setCostDate(event.target.value)} InputLabelProps={{ shrink: true }}/>
        <Button variant="contained" startIcon={<AddRounded/>} onClick={openDialog}
          disabled={!rigId || !costDate || dayLoading || (day?.entry ? !canUpdate : !canCreate)}>
          {day?.entry ? 'Open consumption' : 'Add consumption'}
        </Button>
        <Tag>{companies.filter(company => company.is_default).length} in the daily set</Tag>
      </Box>
      {!canOverrideOpening && <Alert severity="info" sx={{ mt: 1.3, py: .4 }}>
        Opening stock is carried from the previous closing stock. Overriding it needs the fuel opening-stock permission.
      </Alert>}
      {dayError && <Box mt={1.2}><ErrorMessage message={dayError}/></Box>}
    </Paper>}

    {!showDeleted && <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, mb: 1.6 }}>
      <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(3, 1fr)', lg: 'repeat(7, 1fr)' } }}>
        <Kpi label="Fuel days" value={String(totals.days)} note={filtersActive ? 'In the selected period' : 'All time'} />
        <Kpi label="Total AGO consumed" value={`${fuelLitres(totals.totalAgo)} L`} note="Engines + companies" strong />
        <Kpi label="Rig engine AGO" value={`${fuelLitres(totals.engine)} L`} note="Rig engines" />
        <Kpi label="Company AGO" value={`${fuelLitres(totals.companies)} L`} note="All companies" />
        <Kpi label="Gas (separate)" value={`${fuelLitres(totals.gas)} L`} note="Not part of AGO" />
        <Kpi label="Latest closing stock" value={`${fuelLitres(totals.closing)} L`}
          note={totals.closingDate ? displayDate(totals.closingDate) : 'No saved day'} />
        <Kpi label="Adjustments" value={`${fuelLitres(totals.adjustments)} L`} note="Opening + closing" />
      </Box>
    </Paper>}

    <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2, mb: 1.8 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" mb={1.2}>
        <Box>
          <Typography fontWeight={800} fontSize={15}>{showDeleted ? 'Deleted fuel days' : 'Daily fuel register'}</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25}>
            {showDeleted
              ? 'Removed fuel days can be restored here; permanent deletion is irreversible.'
              : `Every fuel day of ${rig?.display_name ?? 'the selected rig'} with its material balance.`}
          </Typography>
        </Box>
        <Tag>{register.length} day{register.length === 1 ? '' : 's'}</Tag>
      </Box>
      <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr auto' } }} alignItems="center">
        <TextField type="date" label="From" value={dateFrom} InputLabelProps={{ shrink: true }}
          onChange={event => setDateFrom(event.target.value)}/>
        <TextField type="date" label="To" value={dateTo} InputLabelProps={{ shrink: true }}
          onChange={event => setDateTo(event.target.value)}/>
        <Button variant="outlined" startIcon={<FilterAltOffOutlined/>} disabled={!filtersActive}
          onClick={() => { setDateFrom(''); setDateTo('') }}>Clear dates</Button>
      </Box>
      {dateFrom && dateTo && dateFrom > dateTo && <Alert severity="error" sx={{ mt: 1.2 }}>
        The start date is after the end date.
      </Alert>}
    </Paper>

    {selected.length > 0 && <Paper variant="outlined" sx={{ p: 1.4, borderRadius: 2, mb: 1.5, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
      <Typography fontSize={12} fontWeight={700} mr="auto">{selected.length} fuel day{selected.length === 1 ? '' : 's'} selected</Typography>
      {showDeleted ? <>
        {can('daily-cost:restore') && <Button size="small" startIcon={<RestoreRounded/>}
          onClick={() => { setActionError(''); setPending({ kind: 'restore', rows: selected }) }}>Restore selected</Button>}
        {can('daily-cost:permanent-delete') && <Button size="small" color="error" startIcon={<DeleteForeverOutlined/>}
          onClick={() => { setActionError(''); setPending({ kind: 'purge', rows: selected }) }}>Delete permanently</Button>}
      </> : can('daily-cost:delete') && <Button size="small" color="error" startIcon={<DeleteOutlineRounded/>}
        onClick={() => { setActionError(''); setPending({ kind: 'delete', rows: selected }) }}>Move to Deleted Entries</Button>}
    </Paper>}

    <ErrorMessage message={registerError}/>
    {!rigId
      ? <Typography color="text.secondary" fontSize={12.5}>Choose a rig to see its fuel register.</Typography>
      : registerLoading && !register.length
        ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
        : <DataTable
            rows={register}
            columns={registerColumns}
            rowKey="id"
            searchPlaceholder={showDeleted ? 'Search deleted fuel days…' : 'Search fuel days by date, rig, remarks or litres…'}
            exportName={showDeleted ? 'fuel-register-deleted' : 'fuel-register'}
            canExport={can('daily-cost:export')}
            onExport={(format, count) => exportAudit(format, count, showDeleted ? 'deleted' : 'register')}
            selectable={showDeleted
              ? can('daily-cost:restore') || can('daily-cost:permanent-delete')
              : can('daily-cost:delete')}
            onSelectionChange={setSelected}
          />}
    {!registerLoading && rigId && !register.length && <Typography color="text.secondary" fontSize={12.5} mt={1.2}>
      {showDeleted
        ? 'There are no deleted fuel days for this rig.'
        : 'No fuel day is recorded for this rig yet. Choose the date above and use Add consumption, or import a file.'}
    </Typography>}

    {!showDeleted && <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2, mt: 2, mb: 1.8 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" mb={1.2}>
        <Box>
          <Typography fontWeight={800} fontSize={15}>Company and category consumption</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.25}>
            AGO consumed by {rig?.display_name ?? 'this rig'} under each company and category
            {dateFrom || dateTo ? ' in the selected period' : ' across the whole register'}. Company consumption adds
            up to the rig total alongside the rig engines.
          </Typography>
        </Box>
        <Box display="flex" gap={.7} alignItems="center">
          <Tag>{fuelLitres(classification?.total_litres ?? 0)} L company AGO</Tag>
          <Tag>{classification?.rows.length ?? 0} classification{classification?.rows.length === 1 ? '' : 's'}</Tag>
        </Box>
      </Box>
      <ErrorMessage message={classificationError}/>
      {classificationLoading && !classification
        ? <Box py={4} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={22}/></Box>
        : <DataTable
            rows={classificationRows}
            columns={classificationColumns}
            rowKey="row_key"
            searchPlaceholder="Search company or category consumption…"
            exportName="fuel-company-consumption"
            canExport={can('daily-cost:export')}
            onExport={(format, count) => exportAudit(format, count, 'company-consumption')}
          />}
      {!classificationLoading && !(classification?.rows.length) && <Typography color="text.secondary" fontSize={12.5} mt={1.2}>
        No company consumption is recorded for this rig in the selected period.
      </Typography>}
    </Paper>}

    <FuelConsumptionDialog
      open={dialogOpen}
      day={day}
      loading={dayLoading}
      loadError={dayError}
      rig={rig}
      costDate={costDate}
      companies={companies}
      vendors={reference?.vendors ?? []}
      canEdit={day?.entry ? canUpdate : canCreate}
      canManageCompanies={canManageCompanies}
      canOverrideOpening={canOverrideOpening}
      saving={saving}
      saveError={saveError}
      onClose={() => { if (!saving) { setDialogOpen(false); setSaveError('') } }}
      onSave={saveDay}
      onCompaniesChanged={loadReference}
    />

    <FuelCompanyDialog
      open={companiesOpen}
      companies={companies.filter(company => !company.is_deleted)}
      vendors={reference?.vendors ?? []}
      canManage={canManageCompanies}
      onClose={() => setCompaniesOpen(false)}
      onChanged={async () => { await loadReference(); await loadDay(rigId, costDate) }}
    />

    {canImport && <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import fuel consumption"
      subtitle={`Add or update fuel days from an Excel or CSV file. Each row may carry its own date and rig code; a blank rig code uses ${rig?.rig_code ?? 'the selected rig'}. Rows of the same rig and date form one day, and company rows are classified by company and category.`}
      headers={FUEL_IMPORT_REQUIRED_HEADERS}
      optionalHeaders={FUEL_IMPORT_OPTIONAL_HEADERS}
      sample={FUEL_IMPORT_SAMPLE}
      templateName="fuel-cost-register-template.csv"
      onRows={runImport}
    />}

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
        {pending?.kind === 'delete' && <Alert severity="info">
          The day moves to Deleted Entries and drops out of the material balance. Later days carry the previous
          remaining closing stock forward.
        </Alert>}
        <ErrorMessage message={actionError}/>
      </Box>
    </FormDialog>
  </>
}

function Kpi({ label, value, note, strong = false }: { label: string; value: string; note: string; strong?: boolean }) {
  return <Box sx={{
    border: '1px solid', borderColor: 'divider', borderRadius: 1.5, px: 1.2, py: 1,
    bgcolor: strong ? 'action.hover' : 'transparent', minWidth: 0,
  }}>
    <Typography fontSize={9.5} fontWeight={800} letterSpacing={.5} color="text.secondary"
      sx={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{label.toUpperCase()}</Typography>
    <Typography fontSize={17} fontWeight={800} mt={.2} sx={{ whiteSpace: 'nowrap' }}>{value}</Typography>
    <Typography fontSize={10.5} color="text.secondary" mt={.2}
      sx={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{note}</Typography>
  </Box>
}

function VarianceCell({ value }: { value: string | undefined }) {
  const amount = Number(value ?? 0)
  if (!amount) return <Typography fontSize={12} color="text.secondary">—</Typography>
  return <Typography fontSize={12} fontWeight={700} color={amount > 0 ? 'text.primary' : 'warning.main'}>
    {amount > 0 ? '+' : ''}{fuelLitres(amount)} L
  </Typography>
}

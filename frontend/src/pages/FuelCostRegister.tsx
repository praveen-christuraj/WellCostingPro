import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Add,
  Apartment,
  ChevronLeft,
  ChevronRight,
  DeleteForever,
  DeleteOutline,
  Download,
  EditOutlined,
  LocalGasStation,
  OpenInNew,
  Refresh,
  RestoreFromTrash,
  Today,
  Upload,
} from '@mui/icons-material'
import {
  Alert,
  Box,
  Button,
  IconButton,
  Menu,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { useAuth } from '../context/AuthContext'
import { FormDialog, PageHeading, Tag } from '../components/Common'
import { DataTable } from '../components/DataTable'
import { ImportDialog } from '../components/ImportDialog'
import { FuelCompanyDialog } from '../components/fuel-cost/FuelCompanyDialog'
import { FuelConsumptionDialog } from '../components/fuel-cost/FuelConsumptionDialog'
import { FuelLinesLedger } from '../components/fuel-cost/FuelLinesLedger'
import { api } from '../lib/api'
import { displayDate, localToday } from '../lib/dailyCost'
import { exportCsv, exportPdf, exportXlsx, type ExportColumn } from '../lib/export'
import {
  buildMonthlyMaterialBalance,
  entryRigSaving,
  FUEL_IMPORT_OPTIONAL_HEADERS,
  FUEL_IMPORT_REQUIRED_HEADERS,
  FUEL_IMPORT_SAMPLE,
  fuelImportRow,
  fuelLitres,
  fuelNumber,
  fuelQuery,
  fuelSavePayload,
  fuelShare,
  shiftIsoDate,
  type FuelCostCategorySummaryRow,
  type FuelCostCompanyConsumption,
  type FuelCostCompanyConsumptionRow,
  type FuelCostCompanySummaryRow,
  type FuelCostDay,
  type FuelCostEntry,
  type FuelCostExportModule,
  type FuelCostImportResponse,
  type FuelCostReference,
  type FuelCostRigSummary,
  type FuelMonthlyBalanceRow,
} from '../lib/fuelCost'

type FuelTab = 'entry' | 'register' | 'balance' | 'companies' | 'categories'
type BalanceViewMode = 'daily' | 'monthly'
type CompanySubView = 'summary' | 'ledger'
type CategorySubView = 'summary' | 'breakdown' | 'ledger'

function KpiTile({
  label,
  value,
  note,
  emphasize = false,
}: {
  label: string
  value: string
  note?: string
  emphasize?: boolean
}) {
  return (
    <Paper
      variant="outlined"
      sx={{
        px: 1.5,
        py: 1.1,
        borderRadius: 1.75,
        borderColor: emphasize ? 'primary.main' : 'divider',
        minWidth: 0,
      }}
    >
      <Typography
        sx={{
          fontSize: 10.5,
          fontWeight: 800,
          letterSpacing: '0.07em',
          color: 'text.secondary',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {label.toUpperCase()}
      </Typography>
      <Typography
        sx={{
          mt: 0.25,
          fontSize: 18,
          fontWeight: 800,
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1.25,
        }}
      >
        {value}
      </Typography>
      {note ? (
        <Typography
          color="text.secondary"
          sx={{
            mt: 0.2,
            fontSize: 11.5,
            lineHeight: 1.25,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {note}
        </Typography>
      ) : null}
    </Paper>
  )
}

function DateRangeBar({
  dateFrom,
  dateTo,
  onDateFrom,
  onDateTo,
  onClear,
  extra,
}: {
  dateFrom: string
  dateTo: string
  onDateFrom: (val: string) => void
  onDateTo: (val: string) => void
  onClear: () => void
  extra?: React.ReactNode
}) {
  return (
    <Paper variant="outlined" sx={{ p: 1.25, borderRadius: 2 }}>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1}
        alignItems={{ xs: 'stretch', md: 'center' }}
        justifyContent="space-between"
      >
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }} flexWrap="wrap" useFlexGap>
          {extra}
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField
            type="date"
            size="small"
            label="From"
            value={dateFrom}
            onChange={event => onDateFrom(event.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ width: 155 }}
          />
          <TextField
            type="date"
            size="small"
            label="To"
            value={dateTo}
            onChange={event => onDateTo(event.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ width: 155 }}
          />
          {dateFrom || dateTo ? (
            <Button size="small" onClick={onClear}>
              Clear dates
            </Button>
          ) : null}
        </Stack>
      </Stack>
    </Paper>
  )
}

export default function FuelCostRegister() {
  const { can } = useAuth()
  const canCreate = can('daily-cost:create')
  const canUpdate = can('daily-cost:update')
  const canDelete = can('daily-cost:delete')
  const canRestore = can('daily-cost:restore')
  const canPermanentDelete = can('daily-cost:permanent-delete')
  const canImport = can('daily-cost:import')
  const canExport = can('daily-cost:export')
  const canOverrideOpening = can('daily-cost:fuel-opening-stock')

  const [reference, setReference] = useState<FuelCostReference>({ rigs: [], companies: [], vendors: [] })
  const [rigId, setRigId] = useState('')
  const [costDate, setCostDate] = useState(localToday)
  const [activeTab, setActiveTab] = useState<FuelTab>('entry')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [showDeleted, setShowDeleted] = useState(false)

  // Compact landing data (last 5 days + lightweight rig summary + selected day preview)
  const [recentEntries, setRecentEntries] = useState<FuelCostEntry[]>([])
  const [rigSummary, setRigSummary] = useState<FuelCostRigSummary | null>(null)
  const [currentDay, setCurrentDay] = useState<FuelCostDay | null>(null)

  // Tab-loaded analytical datasets
  const [fullEntries, setFullEntries] = useState<FuelCostEntry[]>([])
  const [deletedEntries, setDeletedEntries] = useState<FuelCostEntry[]>([])
  const [classification, setClassification] = useState<FuelCostCompanyConsumption | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  // Sub-view & filter states inside tabs
  const [balanceView, setBalanceView] = useState<BalanceViewMode>('daily')
  const [companySubView, setCompanySubView] = useState<CompanySubView>('summary')
  const [selectedCompanyId, setSelectedCompanyId] = useState('')
  const [categorySubView, setCategorySubView] = useState<CategorySubView>('summary')
  const [selectedCategoryKey, setSelectedCategoryKey] = useState('')

  const [loading, setLoading] = useState(true)
  const [tabLoading, setTabLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [recentExportAnchor, setRecentExportAnchor] = useState<HTMLElement | null>(null)

  // Consumption dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogDate, setDialogDate] = useState(localToday)
  const [dialogDay, setDialogDay] = useState<FuelCostDay | null>(null)
  const [dialogLoading, setDialogLoading] = useState(false)
  const [dialogLoadError, setDialogLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  const [companyDialogOpen, setCompanyDialogOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [confirmState, setConfirmState] = useState<{
    title: string
    message: string
    confirmLabel: string
    tone: 'primary' | 'danger'
    action: () => Promise<void>
  } | null>(null)
  const [confirmBusy, setConfirmBusy] = useState(false)

  const selectedRig = useMemo(
    () => reference.rigs.find(rig => rig.id === rigId) ?? null,
    [reference.rigs, rigId],
  )

  const loadReference = useCallback(async () => {
    const data = await api<FuelCostReference>('/fuel-cost/reference')
    setReference(data)
    setRigId(current =>
      current && data.rigs.some(rig => rig.id === current) ? current : (data.rigs[0]?.id ?? ''),
    )
    return data
  }, [])

  // Landing data: ONLY the last 5 entered days (`limit=5`) + fast rig summary
  const loadLandingData = useCallback(async (activeRigId: string, from: string, to: string) => {
    if (!activeRigId) {
      setRecentEntries([])
      setRigSummary(null)
      return
    }
    const [recent, summary] = await Promise.all([
      api<FuelCostEntry[]>(`/fuel-cost/entries${fuelQuery({ rig_id: activeRigId, limit: 5 })}`),
      api<FuelCostRigSummary>(`/fuel-cost/rigs/${activeRigId}/summary${fuelQuery({ from, to })}`),
    ])
    setRecentEntries(recent)
    setRigSummary(summary)
  }, [])

  // Tab-specific data loaded on demand so the landing tab stays ultra-fast even on 10,000-day rigs
  const loadTabData = useCallback(async (
    activeRigId: string,
    tab: FuelTab,
    deletedMode: boolean,
    from: string,
    to: string,
  ) => {
    if (!activeRigId) {
      setFullEntries([])
      setDeletedEntries([])
      setClassification(null)
      return
    }
    setTabLoading(true)
    try {
      const rangeQuery = fuelQuery({ rig_id: activeRigId, from, to })
      const compQuery = fuelQuery({ from, to })
      if (deletedMode) {
        const rows = await api<FuelCostEntry[]>(`/fuel-cost/entries/deleted${rangeQuery}`)
        setDeletedEntries(rows)
        setSelectedIds([])
        return
      }
      if (tab === 'register' || tab === 'balance') {
        const rows = await api<FuelCostEntry[]>(`/fuel-cost/entries${rangeQuery}`)
        setFullEntries(rows)
        setSelectedIds([])
      } else if (tab === 'companies' || tab === 'categories') {
        const comp = await api<FuelCostCompanyConsumption>(
          `/fuel-cost/rigs/${activeRigId}/company-consumption${compQuery}`,
        )
        setClassification(comp)
      }
    } finally {
      setTabLoading(false)
    }
  }, [])

  const refreshAll = useCallback(async (activeRigId = rigId) => {
    await loadLandingData(activeRigId, dateFrom, dateTo)
    await loadTabData(activeRigId, activeTab, showDeleted, dateFrom, dateTo)
  }, [rigId, dateFrom, dateTo, activeTab, showDeleted, loadLandingData, loadTabData])

  const loadSelectedDay = useCallback(async (activeRigId: string, dateValue: string) => {
    if (!activeRigId || !dateValue) {
      setCurrentDay(null)
      return
    }
    try {
      const day = await api<FuelCostDay>(
        `/fuel-cost/day${fuelQuery({ rig_id: activeRigId, date: dateValue })}`,
      )
      setCurrentDay(day)
    } catch {
      setCurrentDay(null)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    setError('')
    loadReference()
      .catch(err => setError((err as Error).message))
      .finally(() => setLoading(false))
  }, [loadReference])

  useEffect(() => {
    if (!rigId) return
    setError('')
    loadLandingData(rigId, dateFrom, dateTo).catch(err => setError((err as Error).message))
  }, [rigId, dateFrom, dateTo, loadLandingData])

  useEffect(() => {
    if (!rigId) return
    setError('')
    loadTabData(rigId, activeTab, showDeleted, dateFrom, dateTo).catch(err => setError((err as Error).message))
  }, [rigId, activeTab, showDeleted, dateFrom, dateTo, loadTabData])

  useEffect(() => {
    loadSelectedDay(rigId, costDate)
  }, [rigId, costDate, loadSelectedDay])

  const openConsumption = async (dateValue = costDate) => {
    if (!rigId || !dateValue) return
    setCostDate(dateValue)
    setDialogDate(dateValue)
    setDialogOpen(true)
    setDialogLoading(true)
    setDialogLoadError('')
    setSaveError('')
    try {
      const day = await api<FuelCostDay>(
        `/fuel-cost/day${fuelQuery({ rig_id: rigId, date: dateValue })}`,
      )
      setDialogDay(day)
      setCurrentDay(day)
    } catch (err) {
      setDialogDay(null)
      setDialogLoadError((err as Error).message)
    } finally {
      setDialogLoading(false)
    }
  }

  const canEditDialog = useMemo(() => {
    if (!dialogDay) return false
    return dialogDay.entry ? canUpdate : canCreate
  }, [dialogDay, canCreate, canUpdate])

  const saveConsumption = async (
    payload: ReturnType<typeof fuelSavePayload>,
    entryId: string | null,
    options?: { advanceToDate?: string },
  ) => {
    setSaving(true)
    setSaveError('')
    try {
      const saved = await api<FuelCostDay>(
        entryId ? `/fuel-cost/entries/${entryId}` : '/fuel-cost/entries',
        { method: entryId ? 'PUT' : 'POST', body: JSON.stringify(payload) },
      )
      setCurrentDay(saved)
      setNotice(
        `Fuel day saved for ${saved.rig_code} on ${displayDate(saved.cost_date)} — AGO consumption `
        + `${fuelLitres(saved.balance.total_consumption)} L, closing stock `
        + `${fuelLitres(saved.balance.actual_closing_stock)} L.`,
      )
      await refreshAll(rigId)
      if (options?.advanceToDate) {
        await openConsumption(options.advanceToDate)
      } else {
        setDialogDay(saved)
        setDialogOpen(false)
      }
    } catch (err) {
      setSaveError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const runBulkAction = (
    title: string,
    message: string,
    confirmLabel: string,
    tone: 'primary' | 'danger',
    path: string,
    ids: string[],
  ) => {
    if (!ids.length) return
    setConfirmState({
      title,
      message,
      confirmLabel,
      tone,
      action: async () => {
        await api(path, { method: 'POST', body: JSON.stringify({ ids }) })
        await refreshAll(rigId)
        await loadSelectedDay(rigId, costDate)
      },
    })
  }

  const auditExport = useCallback((
    module: FuelCostExportModule,
    format: 'csv' | 'xlsx' | 'pdf',
    count: number,
  ) => {
    api('/fuel-cost/export-audit', {
      method: 'POST',
      body: JSON.stringify({ module, format, record_count: count, rig_id: rigId }),
    }).catch(() => undefined)
  }, [rigId])

  const exportRecentFive = async (format: 'csv' | 'xlsx' | 'pdf') => {
    setRecentExportAnchor(null)
    if (!recentEntries.length) return
    const cols: ExportColumn<FuelCostEntry>[] = [
      { header: 'DATE', value: r => displayDate(r.cost_date) },
      { header: 'RIG', value: r => r.rig_code },
      { header: 'OPENING STOCK (L)', value: r => fuelLitres(r.balance.opening_stock) },
      { header: 'RECEIPT (L)', value: r => fuelLitres(r.balance.receipt) },
      { header: 'RIG ENGINE AGO (L)', value: r => fuelLitres(r.balance.rig_engine_consumption) },
      { header: 'COMPANY AGO (L)', value: r => fuelLitres(r.balance.company_consumption) },
      { header: 'TOTAL AGO (L)', value: r => fuelLitres(r.balance.total_consumption) },
      { header: 'BOOK CLOSING (L)', value: r => fuelLitres(r.balance.book_closing_stock) },
      { header: 'ACTUAL CLOSING (L)', value: r => fuelLitres(r.balance.actual_closing_stock) },
      { header: 'ADJUSTMENTS (L)', value: r => fuelLitres(r.balance.adjustments) },
      { header: 'RIG SAVING (LITRES)', value: r => fuelLitres(entryRigSaving(r)) },
      { header: 'REMARKS', value: r => r.remarks || '' },
    ]
    const base = `fuel-recent-5-days-${selectedRig?.rig_code ?? 'rig'}`
    if (format === 'csv') exportCsv(`${base}.csv`, recentEntries, cols)
    else if (format === 'xlsx') await exportXlsx(`${base}.xlsx`, recentEntries, cols)
    else await exportPdf(`${base}.pdf`, `Last 5 Fuel Days — ${selectedRig?.display_name ?? ''}`, recentEntries, cols)
    auditExport('recent-register', format, recentEntries.length)
  }

  // Last-5-days metrics for the compact Daily Entry tab
  const recentMetrics = useMemo(() => {
    const engine = recentEntries.reduce((sum, item) => sum + fuelNumber(item.balance.rig_engine_consumption), 0)
    const company = recentEntries.reduce((sum, item) => sum + fuelNumber(item.balance.company_consumption), 0)
    const totalAgo = engine + company
    const rigSaving = recentEntries.reduce((sum, item) => sum + fuelNumber(entryRigSaving(item)), 0)
    const latest = recentEntries[0] ?? null
    return { engine, company, totalAgo, rigSaving, latest }
  }, [recentEntries])

  // Complete Register KPIs
  const registerTotals = useMemo(() => {
    const engine = fullEntries.reduce((sum, row) => sum + fuelNumber(row.balance.rig_engine_consumption), 0)
    const company = fullEntries.reduce((sum, row) => sum + fuelNumber(row.balance.company_consumption), 0)
    const rigSaving = fullEntries.reduce((sum, row) => sum + fuelNumber(entryRigSaving(row)), 0)
    const adjustments = fullEntries.reduce((sum, row) => sum + fuelNumber(row.balance.adjustments), 0)
    const latest = fullEntries[0] ?? null
    return {
      engine,
      company,
      total: engine + company,
      rigSaving,
      adjustments,
      closing: latest ? fuelNumber(latest.balance.actual_closing_stock) : 0,
      closingDate: latest?.cost_date ?? null,
    }
  }, [fullEntries])

  const monthlyBalanceRows = useMemo(
    () => buildMonthlyMaterialBalance(fullEntries),
    [fullEntries],
  )

  const defaultCompanyCount = useMemo(
    () => reference.companies.filter(company => !company.is_deleted && company.is_default).length,
    [reference.companies],
  )

  const activeCompanies = useMemo(
    () => reference.companies.filter(company => !company.is_deleted),
    [reference.companies],
  )

  // Company-wise derived rows & KPIs
  const companyTotalAgo = fuelNumber(classification?.total_litres)
  const rigTotalAgoInPeriod = fuelNumber(classification?.total_ago_litres)
  const rigEngineAgoInPeriod = fuelNumber(classification?.rig_engine_litres)

  const filteredCompanySummaryRows = useMemo<FuelCostCompanySummaryRow[]>(() => {
    const rows = classification?.company_rows ?? []
    if (!selectedCompanyId) return rows
    return rows.filter(row => row.company_id === selectedCompanyId)
  }, [classification, selectedCompanyId])

  // Category-wise derived rows & KPIs
  const categoryOptions = useMemo(
    () => classification?.category_rows ?? [],
    [classification],
  )

  const filteredCategorySummaryRows = useMemo<FuelCostCategorySummaryRow[]>(() => {
    const rows = classification?.category_rows ?? []
    if (!selectedCategoryKey) return rows
    return rows.filter(row => row.category_key === selectedCategoryKey)
  }, [classification, selectedCategoryKey])

  const filteredCategoryBreakdownRows = useMemo<FuelCostCompanyConsumptionRow[]>(() => {
    let rows = classification?.rows ?? []
    if (selectedCompanyId) rows = rows.filter(row => row.company_id === selectedCompanyId)
    if (selectedCategoryKey) {
      if (selectedCategoryKey === '__none__') {
        rows = rows.filter(row => !row.category_id && !row.category_name)
      } else if (selectedCategoryKey.startsWith('cat:')) {
        const target = selectedCategoryKey.slice(4).toLowerCase()
        rows = rows.filter(row => (row.category_name || '').toLowerCase() === target)
      }
    }
    return rows
  }, [classification, selectedCompanyId, selectedCategoryKey])

  const uncategorisedLitres = useMemo(() => {
    const uncat = (classification?.category_rows ?? []).find(row => row.category_key === '__none__')
    return fuelNumber(uncat?.litres)
  }, [classification])

  // ---------------------------------------------------------------------------
  // Column definitions across tabs
  // ---------------------------------------------------------------------------

  const registerColumns = useMemo<ColDef<FuelCostEntry>[]>(() => [
    {
      headerName: 'DATE',
      field: 'cost_date',
      width: 122,
      valueFormatter: params => displayDate(String(params.value ?? '')),
    },
    {
      headerName: 'OPENING STOCK',
      width: 138,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.opening_stock),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'RECEIPT',
      width: 118,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.receipt),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'RIG ENGINES (AGO)',
      width: 148,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.rig_engine_consumption),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'COMPANIES (AGO)',
      width: 146,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.company_consumption),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'TOTAL AGO',
      width: 132,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.total_consumption),
      valueFormatter: params => fuelLitres(params.value),
      cellStyle: { fontWeight: 700 },
    },
    {
      headerName: 'BOOK CLOSING',
      width: 136,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.book_closing_stock),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'ACTUAL CLOSING',
      width: 142,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.actual_closing_stock),
      valueFormatter: params => fuelLitres(params.value),
      cellStyle: { fontWeight: 700 },
    },
    {
      headerName: 'ADJUSTMENTS',
      width: 130,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.adjustments),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'RIG SAVING (LITRES)',
      width: 162,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(entryRigSaving(params.data)),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'LINES',
      field: 'line_count',
      width: 82,
      type: 'rightAligned',
    },
    {
      headerName: 'REMARKS',
      field: 'remarks',
      minWidth: 165,
      flex: 1,
    },
    {
      headerName: 'ACTIONS',
      width: showDeleted ? 195 : 150,
      pinned: 'right',
      sortable: false,
      filter: false,
      cellRenderer: (params: { data?: FuelCostEntry }) => {
        const entry = params.data
        if (!entry) return null
        if (entry.is_deleted) {
          return (
            <Stack direction="row" spacing={0.5} alignItems="center" sx={{ height: '100%' }}>
              {canRestore ? (
                <Button
                  size="small"
                  startIcon={<RestoreFromTrash fontSize="small" />}
                  onClick={() => runBulkAction(
                    'Restore fuel day?',
                    `Restore ${entry.display_name} to the active fuel register? Subsequent carry-forward stocks will recalculate.`,
                    'Restore',
                    'primary',
                    '/fuel-cost/entries/bulk-restore',
                    [entry.id],
                  )}
                >
                  Restore
                </Button>
              ) : null}
              {canPermanentDelete ? (
                <Tooltip title="Delete permanently">
                  <IconButton
                    size="small"
                    color="error"
                    aria-label="Delete fuel day permanently"
                    onClick={() => runBulkAction(
                      'Permanently delete fuel day?',
                      `Permanently remove ${entry.display_name} and all of its company consumption lines? This cannot be undone.`,
                      'Delete permanently',
                      'danger',
                      '/fuel-cost/entries/bulk-permanent-delete',
                      [entry.id],
                    )}
                  >
                    <DeleteForever fontSize="small" />
                  </IconButton>
                </Tooltip>
              ) : null}
            </Stack>
          )
        }
        return (
          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ height: '100%' }}>
            <Button
              size="small"
              startIcon={<EditOutlined fontSize="small" />}
              onClick={() => openConsumption(entry.cost_date)}
            >
              Open
            </Button>
            {canDelete ? (
              <Tooltip title="Move to Deleted Entries">
                <IconButton
                  size="small"
                  aria-label="Delete fuel day"
                  onClick={() => runBulkAction(
                    'Move fuel day to Deleted Entries?',
                    `Soft-delete ${entry.display_name}? Carry-forward balances after this date will recalculate automatically.`,
                    'Move to Deleted Entries',
                    'danger',
                    '/fuel-cost/entries/bulk-delete',
                    [entry.id],
                  )}
                >
                  <DeleteOutline fontSize="small" />
                </IconButton>
              </Tooltip>
            ) : null}
          </Stack>
        )
      },
    },
  ], [showDeleted, canDelete, canRestore, canPermanentDelete]) // eslint-disable-line react-hooks/exhaustive-deps

  const dailyBalanceColumns = useMemo<ColDef<FuelCostEntry>[]>(() => [
    {
      headerName: 'DATE',
      field: 'cost_date',
      width: 120,
      valueFormatter: params => displayDate(String(params.value ?? '')),
    },
    {
      headerName: 'SOURCE',
      width: 120,
      valueGetter: params => {
        if (params.data?.balance.is_first_entry) return 'First day'
        if (params.data?.balance.opening_overridden) return 'Overridden'
        return 'Carried'
      },
      cellRenderer: (params: { value?: string }) => (
        <Tag tone={params.value === 'Overridden' ? 'warning' : params.value === 'First day' ? 'info' : 'neutral'}>
          {params.value ?? 'Carried'}
        </Tag>
      ),
    },
    {
      headerName: 'CARRIED OPENING',
      width: 142,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.carried_opening),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'OPENING STOCK',
      width: 136,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.opening_stock),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'OPENING ADJ.',
      width: 126,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.opening_adjustment),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'RECEIPT',
      width: 118,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.receipt),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'TOTAL AGO',
      width: 130,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.total_consumption),
      valueFormatter: params => fuelLitres(params.value),
      cellStyle: { fontWeight: 700 },
    },
    {
      headerName: 'BOOK CLOSING',
      width: 136,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.book_closing_stock),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'ACTUAL CLOSING',
      width: 142,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.actual_closing_stock),
      valueFormatter: params => fuelLitres(params.value),
      cellStyle: { fontWeight: 700 },
    },
    {
      headerName: 'CLOSING ADJ.',
      width: 126,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.closing_adjustment),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'NET ADJ.',
      width: 118,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.balance.adjustments),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'RIG SAVING (LITRES)',
      width: 158,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(entryRigSaving(params.data)),
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'ACTIONS',
      width: 110,
      pinned: 'right',
      sortable: false,
      filter: false,
      cellRenderer: (params: { data?: FuelCostEntry }) =>
        params.data ? (
          <Button size="small" onClick={() => openConsumption(params.data!.cost_date)}>
            Open
          </Button>
        ) : null,
    },
  ], []) // eslint-disable-line react-hooks/exhaustive-deps

  const monthlyBalanceColumns = useMemo<ColDef<FuelMonthlyBalanceRow>[]>(() => [
    { headerName: 'MONTH', field: 'month_label', width: 130 },
    { headerName: 'DAYS', field: 'day_count', width: 86, type: 'rightAligned' },
    {
      headerName: 'OPENING STOCK',
      field: 'opening_stock',
      width: 142,
      type: 'rightAligned',
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'RECEIPTS',
      field: 'receipt',
      width: 128,
      type: 'rightAligned',
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'RIG ENGINES (AGO)',
      field: 'rig_engine_consumption',
      width: 152,
      type: 'rightAligned',
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'COMPANIES (AGO)',
      field: 'company_consumption',
      width: 148,
      type: 'rightAligned',
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'TOTAL AGO',
      field: 'total_consumption',
      width: 136,
      type: 'rightAligned',
      valueFormatter: params => fuelLitres(params.value),
      cellStyle: { fontWeight: 700 },
    },
    {
      headerName: 'EXPECTED CLOSING',
      field: 'book_closing_stock',
      width: 152,
      type: 'rightAligned',
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'ACTUAL CLOSING',
      field: 'actual_closing_stock',
      width: 146,
      type: 'rightAligned',
      valueFormatter: params => fuelLitres(params.value),
      cellStyle: { fontWeight: 700 },
    },
    {
      headerName: 'NET ADJ.',
      field: 'adjustments',
      width: 122,
      type: 'rightAligned',
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: 'RIG SAVING (LITRES)',
      field: 'rig_saving_litres',
      width: 162,
      type: 'rightAligned',
      valueFormatter: params => fuelLitres(params.value),
    },
  ], [])

  const companySummaryColumns = useMemo<ColDef<FuelCostCompanySummaryRow>[]>(() => [
    { headerName: 'COMPANY', field: 'company_name', minWidth: 210, flex: 1 },
    {
      headerName: 'VENDOR',
      field: 'vendor_code',
      width: 120,
      valueFormatter: params => String(params.value || 'Manual'),
    },
    {
      headerName: 'DAILY SET',
      width: 112,
      valueGetter: params => (params.data?.is_default ? 'Yes' : 'No'),
      cellRenderer: (params: { data?: FuelCostCompanySummaryRow }) =>
        params.data?.is_default ? <Tag tone="success">Daily set</Tag> : <Tag>On demand</Tag>,
    },
    { headerName: 'CATEGORIES', field: 'category_count', width: 116, type: 'rightAligned' },
    { headerName: 'DAYS', field: 'day_count', width: 92, type: 'rightAligned' },
    { headerName: 'LINES', field: 'line_count', width: 92, type: 'rightAligned' },
    {
      headerName: 'AGO CONSUMED (LITRES)',
      width: 185,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.litres),
      valueFormatter: params => fuelLitres(params.value),
      cellStyle: { fontWeight: 700 },
    },
    {
      headerName: 'AVG / DAY (L)',
      width: 132,
      type: 'rightAligned',
      valueGetter: params => {
        const days = params.data?.day_count ?? 0
        return days > 0 ? fuelNumber(params.data?.litres) / days : 0
      },
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: '% COMPANY AGO',
      width: 145,
      type: 'rightAligned',
      valueGetter: params => fuelShare(params.data?.litres, companyTotalAgo),
    },
    {
      headerName: '% RIG AGO',
      width: 125,
      type: 'rightAligned',
      valueGetter: params => fuelShare(params.data?.litres, rigTotalAgoInPeriod),
    },
    {
      headerName: 'ACTIONS',
      width: 128,
      pinned: 'right',
      sortable: false,
      filter: false,
      cellRenderer: (params: { data?: FuelCostCompanySummaryRow }) =>
        params.data ? (
          <Button
            size="small"
            onClick={() => {
              setSelectedCompanyId(params.data!.company_id)
              setCompanySubView('ledger')
            }}
          >
            Daily log
          </Button>
        ) : null,
    },
  ], [companyTotalAgo, rigTotalAgoInPeriod])

  const categorySummaryColumns = useMemo<ColDef<FuelCostCategorySummaryRow>[]>(() => [
    { headerName: 'CATEGORY', field: 'category_name', minWidth: 210, flex: 1 },
    { headerName: 'COMPANIES', field: 'company_count', width: 120, type: 'rightAligned' },
    { headerName: 'DAYS', field: 'day_count', width: 96, type: 'rightAligned' },
    { headerName: 'LINES', field: 'line_count', width: 96, type: 'rightAligned' },
    {
      headerName: 'AGO CONSUMED (LITRES)',
      width: 188,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.litres),
      valueFormatter: params => fuelLitres(params.value),
      cellStyle: { fontWeight: 700 },
    },
    {
      headerName: 'AVG / DAY (L)',
      width: 135,
      type: 'rightAligned',
      valueGetter: params => {
        const days = params.data?.day_count ?? 0
        return days > 0 ? fuelNumber(params.data?.litres) / days : 0
      },
      valueFormatter: params => fuelLitres(params.value),
    },
    {
      headerName: '% COMPANY AGO',
      width: 145,
      type: 'rightAligned',
      valueGetter: params => fuelShare(params.data?.litres, companyTotalAgo),
    },
    {
      headerName: '% RIG AGO',
      width: 125,
      type: 'rightAligned',
      valueGetter: params => fuelShare(params.data?.litres, rigTotalAgoInPeriod),
    },
    {
      headerName: 'ACTIONS',
      width: 128,
      pinned: 'right',
      sortable: false,
      filter: false,
      cellRenderer: (params: { data?: FuelCostCategorySummaryRow }) =>
        params.data ? (
          <Button
            size="small"
            onClick={() => {
              setSelectedCategoryKey(params.data!.category_key)
              setCategorySubView('ledger')
            }}
          >
            Daily log
          </Button>
        ) : null,
    },
  ], [companyTotalAgo, rigTotalAgoInPeriod])

  const companyCategoryBreakdownColumns = useMemo<ColDef<FuelCostCompanyConsumptionRow>[]>(() => [
    { headerName: 'COMPANY', field: 'company_name', minWidth: 210, flex: 1 },
    {
      headerName: 'CATEGORY',
      minWidth: 180,
      flex: 1,
      valueGetter: params => params.data?.category_name || 'Uncategorised',
    },
    { headerName: 'DAYS', field: 'day_count', width: 95, type: 'rightAligned' },
    { headerName: 'LINES', field: 'line_count', width: 95, type: 'rightAligned' },
    {
      headerName: 'AGO CONSUMED (LITRES)',
      width: 185,
      type: 'rightAligned',
      valueGetter: params => fuelNumber(params.data?.litres),
      valueFormatter: params => fuelLitres(params.value),
      cellStyle: { fontWeight: 700 },
    },
    {
      headerName: '% COMPANY AGO',
      width: 145,
      type: 'rightAligned',
      valueGetter: params => fuelShare(params.data?.litres, companyTotalAgo),
    },
    {
      headerName: '% RIG AGO',
      width: 125,
      type: 'rightAligned',
      valueGetter: params => fuelShare(params.data?.litres, rigTotalAgoInPeriod),
    },
    {
      headerName: 'ACTIONS',
      width: 128,
      pinned: 'right',
      sortable: false,
      filter: false,
      cellRenderer: (params: { data?: FuelCostCompanyConsumptionRow }) =>
        params.data ? (
          <Button
            size="small"
            onClick={() => {
              setSelectedCompanyId(params.data!.company_id)
              setSelectedCategoryKey(
                params.data!.category_name ? `cat:${params.data!.category_name}` : '__none__',
              )
              setCategorySubView('ledger')
            }}
          >
            Daily log
          </Button>
        ) : null,
    },
  ], [companyTotalAgo, rigTotalAgoInPeriod])

  const totalActiveDays = rigSummary?.total_active_days ?? recentEntries.length

  return (
    <Stack spacing={2}>
      <PageHeading
        eyebrow="DAILY COST MANAGEMENT / FUEL COST REGISTER"
        title="Fuel Cost Register"
        subtitle="Rig-scoped daily AGO ledger, Rig Saving (litres) from gas usage, carried physical stock and company/category allocation."
        action={(
          <>
            <Button
              size="small"
              variant="outlined"
              startIcon={<Refresh fontSize="small" />}
              disabled={loading || tabLoading}
              onClick={() => refreshAll(rigId)}
            >
              Refresh
            </Button>
            <Button
              size="small"
              variant="outlined"
              startIcon={<Apartment fontSize="small" />}
              onClick={() => setCompanyDialogOpen(true)}
            >
              Companies & categories ({activeCompanies.length})
            </Button>
            {canImport && !showDeleted ? (
              <Button
                size="small"
                variant="outlined"
                startIcon={<Upload fontSize="small" />}
                disabled={!rigId}
                onClick={() => setImportOpen(true)}
              >
                Import
              </Button>
            ) : null}
            <Button
              size="small"
              variant={showDeleted ? 'contained' : 'outlined'}
              onClick={() => setShowDeleted(current => !current)}
            >
              {showDeleted ? 'Active register' : 'Deleted entries'}
            </Button>
          </>
        )}
      />

      {error ? <Alert severity="error" onClose={() => setError('')}>{error}</Alert> : null}
      {notice ? <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert> : null}

      {!loading && !reference.rigs.length ? (
        <Alert severity="info">
          Add a rig in Master Data Management → Rig Master before recording fuel consumption.
        </Alert>
      ) : null}

      {/* Compact Single-Strip Rig + Fuel Date Entry Bar */}
      {!showDeleted ? (
        <Paper variant="outlined" sx={{ px: 1.75, py: 1.25, borderRadius: 2 }}>
          <Stack
            direction={{ xs: 'column', lg: 'row' }}
            spacing={1.25}
            alignItems={{ xs: 'stretch', lg: 'center' }}
            justifyContent="space-between"
          >
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={1}
              alignItems={{ xs: 'stretch', sm: 'center' }}
              flexWrap="wrap"
              useFlexGap
            >
              <TextField
                select
                size="small"
                label="Rig"
                value={rigId}
                onChange={event => setRigId(event.target.value)}
                disabled={!reference.rigs.length}
                sx={{ minWidth: { xs: '100%', sm: 235 } }}
              >
                {reference.rigs.map(rig => (
                  <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>
                ))}
              </TextField>

              <Stack direction="row" spacing={0.5} alignItems="center">
                <Tooltip title="Previous calendar day">
                  <span>
                    <IconButton
                      size="small"
                      aria-label="Previous fuel date"
                      disabled={!rigId}
                      onClick={() => setCostDate(current => shiftIsoDate(current, -1))}
                    >
                      <ChevronLeft fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <TextField
                  type="date"
                  size="small"
                  label="Fuel date"
                  value={costDate}
                  onChange={event => setCostDate(event.target.value)}
                  InputLabelProps={{ shrink: true }}
                  sx={{ width: 158 }}
                />
                <Tooltip title="Next calendar day">
                  <span>
                    <IconButton
                      size="small"
                      aria-label="Next fuel date"
                      disabled={!rigId}
                      onClick={() => setCostDate(current => shiftIsoDate(current, 1))}
                    >
                      <ChevronRight fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <Button
                  size="small"
                  variant="text"
                  startIcon={<Today fontSize="small" />}
                  disabled={costDate === localToday()}
                  onClick={() => setCostDate(localToday())}
                >
                  Today
                </Button>
              </Stack>

              <Button
                variant="contained"
                size="small"
                startIcon={currentDay?.entry ? <LocalGasStation fontSize="small" /> : <Add fontSize="small" />}
                disabled={!rigId || !costDate || (!currentDay?.entry && !canCreate)}
                onClick={() => openConsumption(costDate)}
                sx={{ py: 0.85, px: 1.75 }}
              >
                {currentDay?.entry ? 'Open consumption' : 'Add consumption'}
              </Button>
            </Stack>

            {currentDay ? (
              <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                {currentDay.entry ? (
                  <>
                    <Tag tone="success">Saved</Tag>
                    <Tag>AGO {fuelLitres(currentDay.balance.total_consumption)} L</Tag>
                    <Tag>Closing {fuelLitres(currentDay.balance.actual_closing_stock)} L</Tag>
                    {fuelNumber(entryRigSaving(currentDay.entry)) > 0 ? (
                      <Tag tone="info">Rig saving {fuelLitres(entryRigSaving(currentDay.entry))} L</Tag>
                    ) : null}
                  </>
                ) : (
                  <>
                    <Tag>Not entered</Tag>
                    {currentDay.balance.is_first_entry ? (
                      <Tag tone="warning">First rig day</Tag>
                    ) : (
                      <Tag>Carried open {fuelLitres(currentDay.balance.carried_opening)} L</Tag>
                    )}
                  </>
                )}
                <Tag>{defaultCompanyCount} in daily set</Tag>
              </Stack>
            ) : null}
          </Stack>
        </Paper>
      ) : null}

      {/* Deleted Entries View */}
      {showDeleted ? (
        <Stack spacing={1.5}>
          <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
            <Stack
              direction={{ xs: 'column', md: 'row' }}
              spacing={1}
              alignItems={{ md: 'center' }}
              justifyContent="space-between"
            >
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <TextField
                  select
                  size="small"
                  label="Rig"
                  value={rigId}
                  onChange={event => setRigId(event.target.value)}
                  disabled={!reference.rigs.length}
                  sx={{ minWidth: 230 }}
                >
                  {reference.rigs.map(rig => (
                    <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>
                  ))}
                </TextField>
                <TextField
                  type="date"
                  size="small"
                  label="From"
                  value={dateFrom}
                  onChange={event => setDateFrom(event.target.value)}
                  InputLabelProps={{ shrink: true }}
                  sx={{ width: 155 }}
                />
                <TextField
                  type="date"
                  size="small"
                  label="To"
                  value={dateTo}
                  onChange={event => setDateTo(event.target.value)}
                  InputLabelProps={{ shrink: true }}
                  sx={{ width: 155 }}
                />
                {dateFrom || dateTo ? (
                  <Button size="small" onClick={() => { setDateFrom(''); setDateTo('') }}>
                    Clear dates
                  </Button>
                ) : null}
              </Stack>

              {selectedIds.length ? (
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                  <Typography sx={{ fontWeight: 700, fontSize: 13 }}>{selectedIds.length} selected</Typography>
                  {canRestore ? (
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<RestoreFromTrash fontSize="small" />}
                      onClick={() => runBulkAction(
                        'Restore selected fuel days?',
                        `Restore ${selectedIds.length} fuel day(s) to the active register?`,
                        'Restore selected',
                        'primary',
                        '/fuel-cost/entries/bulk-restore',
                        selectedIds,
                      )}
                    >
                      Restore
                    </Button>
                  ) : null}
                  {canPermanentDelete ? (
                    <Button
                      size="small"
                      color="error"
                      variant="outlined"
                      startIcon={<DeleteForever fontSize="small" />}
                      onClick={() => runBulkAction(
                        'Permanently delete selected fuel days?',
                        `Permanently remove ${selectedIds.length} fuel day(s) and their company consumption lines? This cannot be undone.`,
                        'Delete permanently',
                        'danger',
                        '/fuel-cost/entries/bulk-permanent-delete',
                        selectedIds,
                      )}
                    >
                      Permanently delete
                    </Button>
                  ) : null}
                </Stack>
              ) : null}
            </Stack>
          </Paper>

          <DataTable
            rows={deletedEntries}
            columns={registerColumns}
            fillHeight
            searchPlaceholder="Search deleted fuel days…"
            selectable={canRestore || canPermanentDelete}
            onSelectionChange={rows => setSelectedIds(rows.map(row => row.id))}
            canExport={canExport}
            exportName={`fuel-cost-deleted-${selectedRig?.rig_code ?? 'rig'}`}
            onExport={canExport ? (format, count) => auditExport('deleted', format, count) : undefined}
          />
        </Stack>
      ) : (
        /* Active Multi-Tab Register Workspace */
        <Stack spacing={1.75}>
          <Box sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
            <Tabs
              value={activeTab}
              onChange={(_, next: FuelTab) => setActiveTab(next)}
              variant="scrollable"
              scrollButtons="auto"
              aria-label="Fuel Cost Register views"
            >
              <Tab
                value="entry"
                label={`Daily Entry (Last ${Math.min(5, recentEntries.length || 5)}d)`}
                id="fuel-tab-entry"
                aria-controls="fuel-panel-entry"
              />
              <Tab
                value="register"
                label={`Complete Fuel Register${totalActiveDays ? ` (${totalActiveDays})` : ''}`}
                id="fuel-tab-register"
                aria-controls="fuel-panel-register"
              />
              <Tab
                value="balance"
                label="Material Balance"
                id="fuel-tab-balance"
                aria-controls="fuel-panel-balance"
              />
              <Tab
                value="companies"
                label="Company-wise"
                id="fuel-tab-companies"
                aria-controls="fuel-panel-companies"
              />
              <Tab
                value="categories"
                label="Category-wise"
                id="fuel-tab-categories"
                aria-controls="fuel-panel-categories"
              />
            </Tabs>
          </Box>

          {/* TAB 1: DAILY ENTRY (Compact snapshot + ONLY the last 5 days of entered data) */}
          {activeTab === 'entry' ? (
            <Box role="tabpanel" id="fuel-panel-entry" aria-labelledby="fuel-tab-entry">
              <Stack spacing={1.75}>
                {selectedRig ? (
                  <Box
                    sx={{
                      display: 'grid',
                      gap: 1.25,
                      gridTemplateColumns: {
                        xs: 'repeat(2, minmax(0, 1fr))',
                        md: 'repeat(3, minmax(0, 1fr))',
                        lg: 'repeat(6, minmax(0, 1fr))',
                      },
                    }}
                  >
                    <KpiTile
                      label="Recorded days"
                      value={String(totalActiveDays)}
                      note={rigSummary?.latest_date ? `Latest ${displayDate(rigSummary.latest_date)}` : 'No entries yet'}
                    />
                    <KpiTile
                      label="Latest closing stock"
                      value={`${fuelLitres(recentMetrics.latest?.balance.actual_closing_stock ?? rigSummary?.actual_closing_stock ?? 0)} L`}
                      note={recentMetrics.latest ? displayDate(recentMetrics.latest.cost_date) : 'Carry-forward tank stock'}
                      emphasize
                    />
                    <KpiTile
                      label="Last 5d total AGO"
                      value={`${fuelLitres(recentMetrics.totalAgo)} L`}
                      note="Rig engines + companies"
                      emphasize
                    />
                    <KpiTile
                      label="Last 5d engine AGO"
                      value={`${fuelLitres(recentMetrics.engine)} L`}
                      note={fuelShare(recentMetrics.engine, recentMetrics.totalAgo)}
                    />
                    <KpiTile
                      label="Last 5d company AGO"
                      value={`${fuelLitres(recentMetrics.company)} L`}
                      note={fuelShare(recentMetrics.company, recentMetrics.totalAgo)}
                    />
                    <KpiTile
                      label="Last 5d Rig Saving"
                      value={`${fuelLitres(recentMetrics.rigSaving)} L`}
                      note="AGO saved via gas (separate)"
                    />
                  </Box>
                ) : null}

                <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                  <Stack
                    direction={{ xs: 'column', sm: 'row' }}
                    spacing={1}
                    alignItems={{ xs: 'flex-start', sm: 'center' }}
                    justifyContent="space-between"
                    sx={{ mb: 1.25 }}
                  >
                    <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
                      <Typography sx={{ fontWeight: 800, fontSize: 14.5 }}>
                        Recent daily fuel register (last 5 days entered)
                      </Typography>
                      <Typography color="text.secondary" sx={{ fontSize: 12.5 }}>
                        Showing {recentEntries.length} of {totalActiveDays} entered day(s) · Litres
                      </Typography>
                    </Stack>

                    <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                      {canExport && recentEntries.length > 0 ? (
                        <>
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<Download fontSize="small" />}
                            onClick={event => setRecentExportAnchor(event.currentTarget)}
                          >
                            Export 5d
                          </Button>
                          <Menu
                            anchorEl={recentExportAnchor}
                            open={Boolean(recentExportAnchor)}
                            onClose={() => setRecentExportAnchor(null)}
                          >
                            <MenuItem onClick={() => exportRecentFive('csv')}>Export CSV</MenuItem>
                            <MenuItem onClick={() => exportRecentFive('xlsx')}>Export Excel (.xlsx)</MenuItem>
                            <MenuItem onClick={() => exportRecentFive('pdf')}>Export PDF</MenuItem>
                          </Menu>
                        </>
                      ) : null}
                      <Button
                        size="small"
                        endIcon={<OpenInNew sx={{ fontSize: 15 }} />}
                        onClick={() => setActiveTab('register')}
                      >
                        View complete register{totalActiveDays > 5 ? ` (${totalActiveDays})` : ''}
                      </Button>
                    </Stack>
                  </Stack>

                  {!recentEntries.length ? (
                    <Typography color="text.secondary" sx={{ py: 2, fontSize: 13 }}>
                      No daily fuel records entered for this rig yet. Pick a date above and click <strong>Add consumption</strong>.
                    </Typography>
                  ) : (
                    <TableContainer
                      sx={{
                        border: '1px solid',
                        borderColor: 'divider',
                        borderRadius: 1.5,
                      }}
                    >
                      <Table size="small" aria-label="Last 5 days of daily fuel register">
                        <TableHead>
                          <TableRow>
                            <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>DATE</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>OPENING</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>RECEIPT</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>ENGINE AGO</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>COMPANY AGO</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>TOTAL AGO</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>BOOK CLOSING</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>ACTUAL CLOSING</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>ADJ.</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>RIG SAVING (L)</TableCell>
                            <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>REMARKS</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>ACTIONS</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {recentEntries.map(entry => {
                            const adj = fuelNumber(entry.balance.adjustments)
                            return (
                              <TableRow
                                key={entry.id}
                                hover
                                selected={entry.cost_date === costDate}
                              >
                                <TableCell sx={{ fontSize: 12.5, whiteSpace: 'nowrap', fontWeight: 600 }}>
                                  {displayDate(entry.cost_date)}
                                  {entry.balance.is_first_entry ? (
                                    <Box component="span" sx={{ ml: 0.75 }}>
                                      <Tag tone="info">Day 1</Tag>
                                    </Box>
                                  ) : entry.balance.opening_overridden ? (
                                    <Box component="span" sx={{ ml: 0.75 }}>
                                      <Tag tone="warning">Override</Tag>
                                    </Box>
                                  ) : null}
                                </TableCell>
                                <TableCell align="right" sx={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
                                  {fuelLitres(entry.balance.opening_stock)}
                                </TableCell>
                                <TableCell align="right" sx={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
                                  {fuelLitres(entry.balance.receipt)}
                                </TableCell>
                                <TableCell align="right" sx={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
                                  {fuelLitres(entry.balance.rig_engine_consumption)}
                                </TableCell>
                                <TableCell align="right" sx={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
                                  {fuelLitres(entry.balance.company_consumption)}
                                </TableCell>
                                <TableCell align="right" sx={{ fontSize: 12.5, fontWeight: 800, fontVariantNumeric: 'tabular-nums' }}>
                                  {fuelLitres(entry.balance.total_consumption)}
                                </TableCell>
                                <TableCell align="right" sx={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
                                  {fuelLitres(entry.balance.book_closing_stock)}
                                </TableCell>
                                <TableCell align="right" sx={{ fontSize: 12.5, fontWeight: 800, fontVariantNumeric: 'tabular-nums' }}>
                                  {fuelLitres(entry.balance.actual_closing_stock)}
                                </TableCell>
                                <TableCell
                                  align="right"
                                  sx={{
                                    fontSize: 12.5,
                                    fontVariantNumeric: 'tabular-nums',
                                    color: adj !== 0 ? 'warning.main' : 'text.secondary',
                                    fontWeight: adj !== 0 ? 700 : 400,
                                  }}
                                >
                                  {fuelLitres(adj)}
                                </TableCell>
                                <TableCell align="right" sx={{ fontSize: 12.5, fontVariantNumeric: 'tabular-nums' }}>
                                  {fuelLitres(entryRigSaving(entry))}
                                </TableCell>
                                <TableCell
                                  sx={{
                                    fontSize: 12,
                                    color: 'text.secondary',
                                    maxWidth: 190,
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                  }}
                                  title={entry.remarks}
                                >
                                  {entry.remarks || '—'}
                                </TableCell>
                                <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                                  <Stack direction="row" spacing={0.25} justifyContent="flex-end" alignItems="center">
                                    <Button
                                      size="small"
                                      startIcon={<EditOutlined sx={{ fontSize: 14 }} />}
                                      onClick={() => openConsumption(entry.cost_date)}
                                    >
                                      Open
                                    </Button>
                                    {canDelete ? (
                                      <Tooltip title="Move to Deleted Entries">
                                        <IconButton
                                          size="small"
                                          aria-label={`Delete fuel day ${displayDate(entry.cost_date)}`}
                                          onClick={() => runBulkAction(
                                            'Move fuel day to Deleted Entries?',
                                            `Soft-delete ${entry.display_name}? Carry-forward balances after this date will recalculate automatically.`,
                                            'Move to Deleted Entries',
                                            'danger',
                                            '/fuel-cost/entries/bulk-delete',
                                            [entry.id],
                                          )}
                                        >
                                          <DeleteOutline fontSize="small" />
                                        </IconButton>
                                      </Tooltip>
                                    ) : null}
                                  </Stack>
                                </TableCell>
                              </TableRow>
                            )
                          })}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}
                </Paper>
              </Stack>
            </Box>
          ) : null}

          {/* TAB 2: COMPLETE FUEL REGISTER */}
          {activeTab === 'register' ? (
            <Box role="tabpanel" id="fuel-panel-register" aria-labelledby="fuel-tab-register">
              <Stack spacing={1.5}>
                <DateRangeBar
                  dateFrom={dateFrom}
                  dateTo={dateTo}
                  onDateFrom={setDateFrom}
                  onDateTo={setDateTo}
                  onClear={() => { setDateFrom(''); setDateTo('') }}
                  extra={(
                    <Typography sx={{ fontWeight: 700, fontSize: 13.5 }}>
                      Complete fuel register — {selectedRig?.display_name ?? ''}
                    </Typography>
                  )}
                />

                <Box
                  sx={{
                    display: 'grid',
                    gap: 1.25,
                    gridTemplateColumns: {
                      xs: 'repeat(2, minmax(0, 1fr))',
                      md: 'repeat(3, minmax(0, 1fr))',
                      lg: 'repeat(6, minmax(0, 1fr))',
                    },
                  }}
                >
                  <KpiTile
                    label="Fuel days"
                    value={String(fullEntries.length)}
                    note={dateFrom || dateTo ? 'Filtered range' : 'All recorded days'}
                  />
                  <KpiTile
                    label="Total AGO consumed"
                    value={`${fuelLitres(registerTotals.total)} L`}
                    note="Engines + companies"
                    emphasize
                  />
                  <KpiTile
                    label="Rig engine AGO"
                    value={`${fuelLitres(registerTotals.engine)} L`}
                    note={fuelShare(registerTotals.engine, registerTotals.total)}
                  />
                  <KpiTile
                    label="Company AGO"
                    value={`${fuelLitres(registerTotals.company)} L`}
                    note={fuelShare(registerTotals.company, registerTotals.total)}
                  />
                  <KpiTile
                    label="Rig Saving (litres)"
                    value={`${fuelLitres(registerTotals.rigSaving)} L`}
                    note="AGO saved via gas (excluded)"
                  />
                  <KpiTile
                    label="Closing stock"
                    value={`${fuelLitres(registerTotals.closing)} L`}
                    note={registerTotals.closingDate ? displayDate(registerTotals.closingDate) : 'No saved day'}
                    emphasize
                  />
                </Box>

                {selectedIds.length && canDelete ? (
                  <Paper variant="outlined" sx={{ px: 1.5, py: 1, borderRadius: 2 }}>
                    <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" flexWrap="wrap">
                      <Typography sx={{ fontWeight: 700, fontSize: 13 }}>{selectedIds.length} day(s) selected</Typography>
                      <Button
                        size="small"
                        color="error"
                        variant="outlined"
                        startIcon={<DeleteOutline fontSize="small" />}
                        onClick={() => runBulkAction(
                          'Move selected fuel days to Deleted Entries?',
                          `Soft-delete ${selectedIds.length} fuel day(s)? Carry-forward balances after those dates will recalculate.`,
                          'Move to Deleted Entries',
                          'danger',
                          '/fuel-cost/entries/bulk-delete',
                          selectedIds,
                        )}
                      >
                        Move to Deleted Entries
                      </Button>
                    </Stack>
                  </Paper>
                ) : null}

                <DataTable
                  rows={fullEntries}
                  columns={registerColumns}
                  fillHeight
                  searchPlaceholder="Search date, remarks, stock or AGO consumption…"
                  selectable={canDelete}
                  onSelectionChange={rows => setSelectedIds(rows.map(row => row.id))}
                  canExport={canExport}
                  exportName={`fuel-cost-register-${selectedRig?.rig_code ?? 'rig'}`}
                  onExport={canExport ? (format, count) => auditExport('register', format, count) : undefined}
                />
              </Stack>
            </Box>
          ) : null}

          {/* TAB 3: MATERIAL BALANCE */}
          {activeTab === 'balance' ? (
            <Box role="tabpanel" id="fuel-panel-balance" aria-labelledby="fuel-tab-balance">
              <Stack spacing={1.5}>
                <DateRangeBar
                  dateFrom={dateFrom}
                  dateTo={dateTo}
                  onDateFrom={setDateFrom}
                  onDateTo={setDateTo}
                  onClear={() => { setDateFrom(''); setDateTo('') }}
                  extra={(
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <Button
                        size="small"
                        variant={balanceView === 'daily' ? 'contained' : 'outlined'}
                        aria-pressed={balanceView === 'daily'}
                        onClick={() => setBalanceView('daily')}
                      >
                        Daily chain ({fullEntries.length})
                      </Button>
                      <Button
                        size="small"
                        variant={balanceView === 'monthly' ? 'contained' : 'outlined'}
                        aria-pressed={balanceView === 'monthly'}
                        onClick={() => setBalanceView('monthly')}
                      >
                        Monthly summary ({monthlyBalanceRows.length})
                      </Button>
                    </Stack>
                  )}
                />

                {rigSummary ? (
                  <Box
                    sx={{
                      display: 'grid',
                      gap: 1.1,
                      gridTemplateColumns: {
                        xs: 'repeat(2, minmax(0, 1fr))',
                        sm: 'repeat(4, minmax(0, 1fr))',
                        lg: 'repeat(8, minmax(0, 1fr))',
                      },
                    }}
                  >
                    <KpiTile
                      label="Opening stock"
                      value={`${fuelLitres(rigSummary.opening_stock)} L`}
                      note={rigSummary.earliest_date ? `Start ${displayDate(rigSummary.earliest_date)}` : 'Period start'}
                    />
                    <KpiTile
                      label="Receipts (+)"
                      value={`${fuelLitres(rigSummary.receipt)} L`}
                      note={`${rigSummary.period_days} day(s)`}
                    />
                    <KpiTile
                      label="Total AGO (−)"
                      value={`${fuelLitres(rigSummary.total_consumption)} L`}
                      note="Engines + companies"
                      emphasize
                    />
                    <KpiTile
                      label="Expected closing"
                      value={`${fuelLitres(rigSummary.expected_closing_stock)} L`}
                      note="Open + rcpt − AGO"
                    />
                    <KpiTile
                      label="Actual closing"
                      value={`${fuelLitres(rigSummary.actual_closing_stock)} L`}
                      note={rigSummary.latest_date ? displayDate(rigSummary.latest_date) : 'Physical dip'}
                      emphasize
                    />
                    <KpiTile
                      label="Opening adj."
                      value={`${fuelLitres(rigSummary.opening_adjustment)} L`}
                      note="Overrides"
                    />
                    <KpiTile
                      label="Closing adj."
                      value={`${fuelLitres(rigSummary.closing_adjustment)} L`}
                      note="Dip variance"
                    />
                    <KpiTile
                      label="Rig Saving (L)"
                      value={`${fuelLitres(rigSummary.rig_saving_litres)} L`}
                      note="Gas saving (excluded)"
                    />
                  </Box>
                ) : null}

                {balanceView === 'daily' ? (
                  <DataTable
                    rows={fullEntries}
                    columns={dailyBalanceColumns}
                    fillHeight
                    searchPlaceholder="Search material balance by date or source…"
                    canExport={canExport}
                    exportName={`fuel-material-balance-daily-${selectedRig?.rig_code ?? 'rig'}`}
                    onExport={canExport ? (format, count) => auditExport('material-balance', format, count) : undefined}
                  />
                ) : (
                  <DataTable
                    rows={monthlyBalanceRows}
                    columns={monthlyBalanceColumns}
                    rowKey="month"
                    fillHeight
                    searchPlaceholder="Search month…"
                    canExport={canExport}
                    exportName={`fuel-material-balance-monthly-${selectedRig?.rig_code ?? 'rig'}`}
                    onExport={canExport ? (format, count) => auditExport('material-balance', format, count) : undefined}
                  />
                )}
              </Stack>
            </Box>
          ) : null}

          {/* TAB 4: COMPANY-WISE */}
          {activeTab === 'companies' ? (
            <Box role="tabpanel" id="fuel-panel-companies" aria-labelledby="fuel-tab-companies">
              <Stack spacing={1.5}>
                <DateRangeBar
                  dateFrom={dateFrom}
                  dateTo={dateTo}
                  onDateFrom={setDateFrom}
                  onDateTo={setDateTo}
                  onClear={() => { setDateFrom(''); setDateTo('') }}
                  extra={(
                    <>
                      <Stack direction="row" spacing={0.5} alignItems="center">
                        <Button
                          size="small"
                          variant={companySubView === 'summary' ? 'contained' : 'outlined'}
                          aria-pressed={companySubView === 'summary'}
                          onClick={() => setCompanySubView('summary')}
                        >
                          Company summary ({filteredCompanySummaryRows.length})
                        </Button>
                        <Button
                          size="small"
                          variant={companySubView === 'ledger' ? 'contained' : 'outlined'}
                          aria-pressed={companySubView === 'ledger'}
                          onClick={() => setCompanySubView('ledger')}
                        >
                          Daily company ledger
                        </Button>
                      </Stack>
                      <TextField
                        select
                        size="small"
                        label="Company"
                        value={selectedCompanyId}
                        onChange={event => setSelectedCompanyId(event.target.value)}
                        sx={{ minWidth: 220 }}
                      >
                        <MenuItem value="">All companies</MenuItem>
                        {(classification?.company_rows ?? []).map(comp => (
                          <MenuItem key={comp.company_id} value={comp.company_id}>
                            {comp.company_name} ({fuelLitres(comp.litres)} L)
                          </MenuItem>
                        ))}
                      </TextField>
                      {selectedCompanyId ? (
                        <Button size="small" onClick={() => setSelectedCompanyId('')}>
                          Reset company
                        </Button>
                      ) : null}
                    </>
                  )}
                />

                <Box
                  sx={{
                    display: 'grid',
                    gap: 1.25,
                    gridTemplateColumns: {
                      xs: 'repeat(2, minmax(0, 1fr))',
                      md: 'repeat(5, minmax(0, 1fr))',
                    },
                  }}
                >
                  <KpiTile
                    label="Active companies"
                    value={String(classification?.company_rows?.length ?? 0)}
                    note={`${classification?.active_day_count ?? 0} fuel day(s)`}
                  />
                  <KpiTile
                    label="Company AGO"
                    value={`${fuelLitres(companyTotalAgo)} L`}
                    note="All contractor lines"
                    emphasize
                  />
                  <KpiTile
                    label="Share of rig AGO"
                    value={fuelShare(companyTotalAgo, rigTotalAgoInPeriod)}
                    note="Companies ÷ total AGO"
                  />
                  <KpiTile
                    label="Rig engine AGO"
                    value={`${fuelLitres(rigEngineAgoInPeriod)} L`}
                    note={fuelShare(rigEngineAgoInPeriod, rigTotalAgoInPeriod)}
                  />
                  <KpiTile
                    label="Total rig AGO"
                    value={`${fuelLitres(rigTotalAgoInPeriod)} L`}
                    note="Engines + companies"
                    emphasize
                  />
                </Box>

                {companySubView === 'summary' ? (
                  <DataTable
                    rows={filteredCompanySummaryRows}
                    columns={companySummaryColumns}
                    rowKey="company_id"
                    fillHeight
                    searchPlaceholder="Search company or vendor code…"
                    canExport={canExport}
                    exportName={`fuel-company-wise-${selectedRig?.rig_code ?? 'rig'}`}
                    onExport={canExport ? (format, count) => auditExport('company-consumption', format, count) : undefined}
                  />
                ) : (
                  <FuelLinesLedger
                    rigId={rigId}
                    rigCode={selectedRig?.rig_code ?? ''}
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    companyId={selectedCompanyId}
                    canExport={canExport}
                    title="Daily company consumption ledger"
                    onOpenDate={dateVal => openConsumption(dateVal)}
                  />
                )}
              </Stack>
            </Box>
          ) : null}

          {/* TAB 5: CATEGORY-WISE */}
          {activeTab === 'categories' ? (
            <Box role="tabpanel" id="fuel-panel-categories" aria-labelledby="fuel-tab-categories">
              <Stack spacing={1.5}>
                <DateRangeBar
                  dateFrom={dateFrom}
                  dateTo={dateTo}
                  onDateFrom={setDateFrom}
                  onDateTo={setDateTo}
                  onClear={() => { setDateFrom(''); setDateTo('') }}
                  extra={(
                    <>
                      <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Button
                          size="small"
                          variant={categorySubView === 'summary' ? 'contained' : 'outlined'}
                          aria-pressed={categorySubView === 'summary'}
                          onClick={() => setCategorySubView('summary')}
                        >
                          Category summary ({filteredCategorySummaryRows.length})
                        </Button>
                        <Button
                          size="small"
                          variant={categorySubView === 'breakdown' ? 'contained' : 'outlined'}
                          aria-pressed={categorySubView === 'breakdown'}
                          onClick={() => setCategorySubView('breakdown')}
                        >
                          Company & category ({filteredCategoryBreakdownRows.length})
                        </Button>
                        <Button
                          size="small"
                          variant={categorySubView === 'ledger' ? 'contained' : 'outlined'}
                          aria-pressed={categorySubView === 'ledger'}
                          onClick={() => setCategorySubView('ledger')}
                        >
                          Daily category ledger
                        </Button>
                      </Stack>
                      <TextField
                        select
                        size="small"
                        label="Category"
                        value={selectedCategoryKey}
                        onChange={event => setSelectedCategoryKey(event.target.value)}
                        sx={{ minWidth: 195 }}
                      >
                        <MenuItem value="">All categories</MenuItem>
                        {categoryOptions.map(cat => (
                          <MenuItem key={cat.category_key} value={cat.category_key}>
                            {cat.category_name} ({fuelLitres(cat.litres)} L)
                          </MenuItem>
                        ))}
                      </TextField>
                      {categorySubView !== 'summary' ? (
                        <TextField
                          select
                          size="small"
                          label="Company"
                          value={selectedCompanyId}
                          onChange={event => setSelectedCompanyId(event.target.value)}
                          sx={{ minWidth: 195 }}
                        >
                          <MenuItem value="">All companies</MenuItem>
                          {(classification?.company_rows ?? []).map(comp => (
                            <MenuItem key={comp.company_id} value={comp.company_id}>
                              {comp.company_name}
                            </MenuItem>
                          ))}
                        </TextField>
                      ) : null}
                      {selectedCategoryKey || selectedCompanyId ? (
                        <Button
                          size="small"
                          onClick={() => {
                            setSelectedCategoryKey('')
                            setSelectedCompanyId('')
                          }}
                        >
                          Reset filters
                        </Button>
                      ) : null}
                    </>
                  )}
                />

                <Box
                  sx={{
                    display: 'grid',
                    gap: 1.25,
                    gridTemplateColumns: {
                      xs: 'repeat(2, minmax(0, 1fr))',
                      md: 'repeat(4, minmax(0, 1fr))',
                    },
                  }}
                >
                  <KpiTile
                    label="Categories used"
                    value={String(categoryOptions.length)}
                    note="Includes Uncategorised if present"
                  />
                  <KpiTile
                    label="Categorised AGO"
                    value={`${fuelLitres(Math.max(0, companyTotalAgo - uncategorisedLitres))} L`}
                    note={fuelShare(Math.max(0, companyTotalAgo - uncategorisedLitres), companyTotalAgo)}
                    emphasize
                  />
                  <KpiTile
                    label="Uncategorised AGO"
                    value={`${fuelLitres(uncategorisedLitres)} L`}
                    note={fuelShare(uncategorisedLitres, companyTotalAgo)}
                  />
                  <KpiTile
                    label="Total company AGO"
                    value={`${fuelLitres(companyTotalAgo)} L`}
                    note={`${fuelShare(companyTotalAgo, rigTotalAgoInPeriod)} of rig AGO`}
                    emphasize
                  />
                </Box>

                {categorySubView === 'summary' ? (
                  <DataTable
                    rows={filteredCategorySummaryRows}
                    columns={categorySummaryColumns}
                    rowKey="category_key"
                    fillHeight
                    searchPlaceholder="Search category…"
                    canExport={canExport}
                    exportName={`fuel-category-summary-${selectedRig?.rig_code ?? 'rig'}`}
                    onExport={canExport ? (format, count) => auditExport('category-consumption', format, count) : undefined}
                  />
                ) : categorySubView === 'breakdown' ? (
                  <DataTable
                    rows={filteredCategoryBreakdownRows}
                    columns={companyCategoryBreakdownColumns}
                    rowKey={row => `${row.company_id}:${row.category_id ?? ''}:${row.category_name}`}
                    fillHeight
                    searchPlaceholder="Search company or category…"
                    canExport={canExport}
                    exportName={`fuel-company-category-breakdown-${selectedRig?.rig_code ?? 'rig'}`}
                    onExport={canExport ? (format, count) => auditExport('category-consumption', format, count) : undefined}
                  />
                ) : (
                  <FuelLinesLedger
                    rigId={rigId}
                    rigCode={selectedRig?.rig_code ?? ''}
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    companyId={selectedCompanyId}
                    categoryKey={selectedCategoryKey}
                    canExport={canExport}
                    title="Daily category consumption ledger"
                    onOpenDate={dateVal => openConsumption(dateVal)}
                  />
                )}
              </Stack>
            </Box>
          ) : null}
        </Stack>
      )}

      {/* Consumption Entry / Edit Dialog */}
      <FuelConsumptionDialog
        open={dialogOpen}
        day={dialogDay}
        loading={dialogLoading}
        loadError={dialogLoadError}
        rig={selectedRig}
        costDate={dialogDate}
        companies={reference.companies}
        vendors={reference.vendors}
        canEdit={canEditDialog}
        canManageCompanies={canCreate}
        canOverrideOpening={canOverrideOpening}
        saving={saving}
        saveError={saveError}
        onClose={() => setDialogOpen(false)}
        onSave={saveConsumption}
        onCompaniesChanged={async () => { await loadReference() }}
        onChangeDate={nextDate => { openConsumption(nextDate) }}
      />

      {/* Companies & Categories Management Dialog */}
      <FuelCompanyDialog
        open={companyDialogOpen}
        companies={reference.companies}
        vendors={reference.vendors}
        canCreate={canCreate}
        canUpdate={canUpdate}
        canDelete={canDelete}
        canRestore={canRestore}
        onClose={() => setCompanyDialogOpen(false)}
        onChanged={async () => {
          await loadReference()
          await refreshAll(rigId)
        }}
      />

      {/* Spreadsheet Import Dialog */}
      <ImportDialog
        open={importOpen}
        title="Import fuel consumption"
        subtitle={
          `Upload an Excel or CSV sheet for ${selectedRig?.display_name ?? 'the selected rig'}. `
          + 'Multiple rows on the same DATE combine into one fuel day and its company consumption lines. '
          + 'Both RIG SAVING (LITRES) and legacy GAS CONSUMPTION (LITRES) headers are accepted.'
        }
        headers={FUEL_IMPORT_REQUIRED_HEADERS}
        optionalHeaders={FUEL_IMPORT_OPTIONAL_HEADERS}
        templateName="fuel-cost-import-template.csv"
        sample={FUEL_IMPORT_SAMPLE}
        onClose={() => setImportOpen(false)}
        onRows={async rows => {
          const response = await api<FuelCostImportResponse>('/fuel-cost/import', {
            method: 'POST',
            body: JSON.stringify({ rig_id: rigId, rows: rows.map(fuelImportRow) }),
          })
          await loadReference()
          await refreshAll(rigId)
          await loadSelectedDay(rigId, costDate)
          if (response.imported_count > 0 && !response.errors.length) {
            setNotice(`Imported ${response.imported_count} fuel day(s) and ${response.line_count} company line(s).`)
          }
          return response.errors
        }}
      />

      {/* Bulk / Row Confirmation Dialog */}
      <FormDialog
        open={Boolean(confirmState)}
        title={confirmState?.title ?? 'Confirm action'}
        onClose={() => { if (!confirmBusy) setConfirmState(null) }}
        onSubmit={async () => {
          if (!confirmState) return
          setConfirmBusy(true)
          try {
            await confirmState.action()
            setConfirmState(null)
          } catch (err) {
            setError((err as Error).message)
            setConfirmState(null)
          } finally {
            setConfirmBusy(false)
          }
        }}
        submitLabel={confirmState?.confirmLabel ?? 'Confirm'}
        danger={confirmState?.tone === 'danger'}
        busy={confirmBusy}
        busyLabel="Working..."
        dirty={false}
        maxWidth="xs"
      >
        <Typography color="text.secondary" sx={{ fontSize: 13 }}>
          {confirmState?.message ?? ''}
        </Typography>
      </FormDialog>
    </Stack>
  )
}

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import type { ColDef } from 'ag-grid-community'
import { ArrowBackRounded, Inventory2Outlined, RefreshRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import { DataTable } from '../DataTable'
import { ErrorMessage, PageHeading } from '../Common'
import { useAuth } from '../../context/AuthContext'
import {
  auditExport, EMPTY_FILTERS, fetchMatrix, fetchReference, formatDateText, formatMoney, formatQuantity,
  type UsageDetailRow, type UsageMatrix as UsageMatrixData, type UsageReference,
  type UsageReportFilters, type UsageReportKey,
} from '../../lib/usageReports'
import FiltersCard from './UsageReportFilters'
import MatrixTable from './UsageMatrix'

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return <Paper variant="outlined" sx={{ p: 1.7, borderRadius: 2, minWidth: 0 }}>
    <Typography color="text.secondary" fontSize={10.5} fontWeight={800} letterSpacing={.7} textTransform="uppercase">{label}</Typography>
    <Typography fontSize={22} fontWeight={800} my={.6} className="tnum">{value}</Typography>
    <Typography color="text.secondary" fontSize={11.2}>{note}</Typography>
  </Paper>
}

const moneyFormatter = (currency: string) => (params: { value?: unknown }) =>
  formatMoney(params.value === undefined ? '' : String(params.value), currency)

function detailColumns(report: UsageReportKey, currency: string): ColDef<UsageDetailRow>[] {
  const costOnly = report === 'services' || report === 'vendors'
  const columns: ColDef<UsageDetailRow>[] = [
    { headerName: 'ITEM CODE', field: 'item_code', minWidth: 130 },
    { headerName: 'ITEM NAME', field: 'item_name', minWidth: 200 },
  ]
  if (report === 'mud-chemicals') {
    columns.push(
      { headerName: 'GROUP', field: 'category', minWidth: 150 },
      { headerName: 'MANUFACTURER', field: 'manufacturer', minWidth: 140 },
      { headerName: 'PART NO.', field: 'detail', minWidth: 140 },
    )
  } else if (report === 'drill-bits') {
    columns.push(
      { headerName: 'BIT TYPE', field: 'category', minWidth: 120 },
      { headerName: 'MAKE', field: 'manufacturer', minWidth: 130 },
      { headerName: 'MODEL / SIZE / IADC', field: 'detail', minWidth: 200 },
    )
  } else if (report === 'tangibles') {
    columns.push(
      { headerName: 'CATEGORY', field: 'category', minWidth: 160 },
      { headerName: 'SUBCATEGORY', field: 'subcategory', minWidth: 150 },
      { headerName: 'MANUFACTURER', field: 'manufacturer', minWidth: 140 },
    )
  } else if (report === 'services') {
    columns.push(
      { headerName: 'SERVICE CATEGORY', field: 'category', minWidth: 160 },
      { headerName: 'PROVIDER TYPE', field: 'subcategory', minWidth: 160 },
      { headerName: 'VENDOR', field: 'manufacturer', minWidth: 160 },
      { headerName: 'SERVICE GROUP', field: 'detail', minWidth: 140 },
    )
  } else {
    columns.push(
      { headerName: 'VENDOR TYPE', field: 'category', minWidth: 130 },
      { headerName: 'VENDOR CATEGORY', field: 'subcategory', minWidth: 140 },
      { headerName: 'COST GROUP', field: 'cost_group', minWidth: 140 },
      { headerName: 'NOTE', field: 'detail', minWidth: 200 },
    )
  }
  columns.push(
    { headerName: 'WELL CODE', field: 'well_code', minWidth: 120 },
    { headerName: 'WELL NAME', field: 'well_name', minWidth: 170 },
    { headerName: 'BLOCK', field: 'block_code', minWidth: 110 },
    { headerName: 'SCOPE', field: 'scope', minWidth: 105 },
    { headerName: 'SECTION CODE', field: 'section_code', minWidth: 120 },
    { headerName: 'SECTION NAME', field: 'section_name', minWidth: 170 },
  )
  if (!costOnly) {
    columns.push({
      headerName: 'USAGE QTY', field: 'quantity', minWidth: 120, type: 'numericColumn',
      valueFormatter: params => formatQuantity(params.value === undefined ? '' : String(params.value)),
    })
    columns.push({ headerName: 'UOM', field: 'uom', minWidth: 90 })
  }
  columns.push({
    headerName: `COST (${currency})`, field: 'amount', minWidth: 150, type: 'numericColumn',
    valueFormatter: moneyFormatter(currency),
  })
  return columns
}

export default function UsageReportShell({
  reportKey,
  title,
  eyebrow,
  subtitle,
  matrixTitle,
  matrixHint,
}: {
  reportKey: UsageReportKey
  title: string
  eyebrow: string
  subtitle: string
  matrixTitle: string
  matrixHint: string
}) {
  const { can } = useAuth()
  const canExport = can('daily-cost:export')
  const [reference, setReference] = useState<UsageReference | null>(null)
  const [filters, setFilters] = useState<UsageReportFilters>(EMPTY_FILTERS)
  const [report, setReport] = useState<UsageMatrixData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    let active = true
    fetchReference().then(data => {
      if (!active) return
      setReference(data)
      setFilters(current => ({ ...current, currency: current.currency || data.default_currency || 'USD' }))
    }).catch(caught => {
      if (active) setError(caught instanceof Error ? caught.message : 'Report filters could not be loaded')
    })
    return () => { active = false }
  }, [])

  const patchFilters = useCallback((patch: Partial<UsageReportFilters>) => {
    setFilters(current => ({ ...current, ...patch }))
  }, [])

  const load = useCallback(async () => {
    if (!filters.currency) return
    setLoading(true)
    setError('')
    try {
      setReport(await fetchMatrix(reportKey, filters))
    } catch (caught) {
      setReport(null)
      setError(caught instanceof Error ? caught.message : 'The report could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [reportKey, filters, refreshKey])

  useEffect(() => { void load() }, [load])

  const columns = useMemo(
    () => detailColumns(reportKey, filters.currency || 'USD'),
    [reportKey, filters.currency],
  )
  const costOnly = report?.mode === 'cost'
  const wellsWithUsage = useMemo(
    () => (report?.well_totals ?? []).filter(total => Number(total.amount) > 0).length,
    [report],
  )

  const handleExport = useCallback(async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await auditExport(reportKey, format, recordCount, filters)
  }, [reportKey, filters])

  const kpis: ReactNode = report ? (
    <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }} gap={1.4} mb={1.7}>
      <Stat label={costOnly ? 'Cost lines' : 'Items'} value={String(report.rows.length)} note={`Distinct ${costOnly ? 'records' : 'catalogue items'} in the matrix`} />
      <Stat label="Wells with figures" value={String(wellsWithUsage)} note={`of ${report.wells.length} selected well${report.wells.length === 1 ? '' : 's'}`} />
      {!costOnly && <Stat label="Total usage" value={formatQuantity(report.grand_quantity)} note="Summed per item unit of measure" />}
      <Stat label={`Total cost (${report.currency})`} value={formatMoney(report.grand_amount)} note="Across every selected well and section" />
    </Box>
  ) : null

  return <>
    <PageHeading
      eyebrow={eyebrow}
      title={title}
      subtitle={subtitle}
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/reports" variant="outlined" startIcon={<ArrowBackRounded />}>Reports</Button>
        <Button variant="outlined" startIcon={<RefreshRounded />} onClick={() => setRefreshKey(value => value + 1)} disabled={loading}>Refresh</Button>
      </Box>}
    />
    <FiltersCard reference={reference} filters={filters} onChange={patchFilters} disabled={!reference} />
    <ErrorMessage message={error} />
    {filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo && (
      <Alert severity="warning" sx={{ mb: 1.5 }}>The start date must not be after the end date.</Alert>
    )}
    {report?.excluded_entry_count ? (
      <Alert severity="info" sx={{ mb: 1.5 }}>
        {report.excluded_entry_count} cost sheet{report.excluded_entry_count === 1 ? '' : 's'} use a different standard currency and {report.excluded_entry_count === 1 ? 'is' : 'are'} excluded from {report.currency} totals. Switch the report currency to include them.
      </Alert>
    ) : null}
    {loading && !report ? (
      <Paper variant="outlined" sx={{ minHeight: 220, display: 'grid', placeItems: 'center', borderRadius: 2 }}>
        <CircularProgress size={28} />
      </Paper>
    ) : report ? <>
      {kpis}
      <MatrixTable report={report} title={matrixTitle} hint={matrixHint} />
      <DataTable
        rows={report.detail}
        columns={columns}
        rowKey="row_id"
        searchPlaceholder="Search items, wells, sections, manufacturers or costs…"
        exportName={`${reportKey}-usage-report`}
        canExport={canExport}
        onExport={canExport ? handleExport : undefined}
      />
      <Typography color="text.secondary" fontSize={11.2} mt={1}>
        <Inventory2Outlined sx={{ fontSize: 13, verticalAlign: -2, mr: .5 }} />
        Period: {formatDateText(report.date_from)} to {report.date_to ? formatDateText(report.date_to) : 'latest entry'}
        {' · '}{report.entry_count} included cost sheet{report.entry_count === 1 ? '' : 's'}
        {report.include_draft ? ' (drafts included)' : ' (submitted only)'}
        {' · '}{report.detail.length} detail row{report.detail.length === 1 ? '' : 's'}.
      </Typography>
    </> : null}
  </>
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import type { ColDef } from 'ag-grid-community'
import { ArrowBackRounded, RefreshRounded, ScheduleRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import { DataTable } from '../DataTable'
import { ErrorMessage, PageHeading } from '../Common'
import { useAuth } from '../../context/AuthContext'
import {
  auditExport, EMPTY_FILTERS, fetchNptUpa, fetchReference, formatDateText, formatMoney, formatQuantity,
  type NptUpaDetailRow, type NptUpaReport, type UsageReference, type UsageReportFilters,
} from '../../lib/usageReports'
import FiltersCard from './UsageReportFilters'
import NptUpaMatrix from './NptUpaMatrix'

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return <Paper variant="outlined" sx={{ p: 1.7, borderRadius: 2, minWidth: 0 }}>
    <Typography color="text.secondary" fontSize={10.5} fontWeight={800} letterSpacing={.7} textTransform="uppercase">{label}</Typography>
    <Typography fontSize={22} fontWeight={800} my={.6} className="tnum">{value}</Typography>
    <Typography color="text.secondary" fontSize={11.2}>{note}</Typography>
  </Paper>
}

export default function NptUpaReportView() {
  const { can } = useAuth()
  const canExport = can('daily-cost:export')
  const [reference, setReference] = useState<UsageReference | null>(null)
  const [filters, setFilters] = useState<UsageReportFilters>(EMPTY_FILTERS)
  const [report, setReport] = useState<NptUpaReport | null>(null)
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
      setReport(await fetchNptUpa(filters))
    } catch (caught) {
      setReport(null)
      setError(caught instanceof Error ? caught.message : 'The NPT/UPA report could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [filters, refreshKey])

  useEffect(() => { void load() }, [load])

  const columns = useMemo<ColDef<NptUpaDetailRow>[]>(() => [
    { headerName: 'WELL CODE', field: 'well_code', minWidth: 120 },
    { headerName: 'WELL NAME', field: 'well_name', minWidth: 180 },
    { headerName: 'BLOCK', field: 'block_code', minWidth: 110 },
    { headerName: 'RIG', field: 'rig_code', minWidth: 110 },
    { headerName: 'SCOPE', field: 'scope', minWidth: 110 },
    { headerName: 'CLASSIFICATION', field: 'classification', minWidth: 140 },
    { headerName: 'AFFECTED DATES', field: 'affected_dates', minWidth: 135, type: 'numericColumn' },
    { headerName: 'ALLOCATED HOURS', field: 'hours', minWidth: 140, type: 'numericColumn', valueFormatter: params => formatQuantity(params.value) },
    { headerName: 'ALLOCATED DAYS', field: 'days', minWidth: 135, type: 'numericColumn', valueFormatter: params => formatQuantity(params.value) },
    {
      headerName: `COST (${filters.currency || 'USD'})`, field: 'amount', minWidth: 150, type: 'numericColumn',
      valueFormatter: params => formatMoney(params.value === undefined ? '' : String(params.value), filters.currency || 'USD'),
    },
  ], [filters.currency])

  const handleExport = useCallback(async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await auditExport('npt-upa', format, recordCount, filters)
  }, [filters])

  return <>
    <PageHeading
      eyebrow="REPORTS / NPT / UPA"
      title="NPT/UPA report"
      subtitle="NPT and UPA allocated duration, affected cost dates and costs per well. Duration comes only from deduplicated explicit service-hour allocations; affected dates remain a separate measure."
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
    {report?.overallocated_date_count ? (
      <Alert severity="warning" sx={{ mb: 1.5 }}>
        {report.overallocated_date_count} legacy well-date{report.overallocated_date_count === 1 ? '' : 's'} exceed 24 allocated hours after duplicate service charges are removed. Correct those daily sheets before treating their duration as MIS-ready.
      </Alert>
    ) : null}
    {loading && !report ? (
      <Paper variant="outlined" sx={{ minHeight: 220, display: 'grid', placeItems: 'center', borderRadius: 2 }}>
        <CircularProgress size={28} />
      </Paper>
    ) : report ? <>
      <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }} gap={1.4} mb={1.7}>
        <Stat label="NPT allocated days" value={formatQuantity(report.totals.npt_days)} note={`${formatQuantity(report.totals.npt_hours)} h · ${report.totals.npt_affected_dates} affected date${report.totals.npt_affected_dates === 1 ? '' : 's'}`} />
        <Stat label={`NPT cost (${report.currency})`} value={formatMoney(report.totals.npt_amount)} note="Non-productive time lines" />
        <Stat label="UPA allocated days" value={formatQuantity(report.totals.upa_days)} note={`${formatQuantity(report.totals.upa_hours)} h · ${report.totals.upa_affected_dates} affected date${report.totals.upa_affected_dates === 1 ? '' : 's'}`} />
        <Stat label={`UPA cost (${report.currency})`} value={formatMoney(report.totals.upa_amount)} note="Unplanned activity lines" />
      </Box>
      <NptUpaMatrix report={report} currency={report.currency} />
      <DataTable
        rows={report.detail}
        columns={columns}
        rowKey="row_id"
        searchPlaceholder="Search wells, scopes or classifications…"
        exportName="npt-upa-report"
        canExport={canExport}
        onExport={canExport ? handleExport : undefined}
      />
      <Typography color="text.secondary" fontSize={11.2} mt={1}>
        <ScheduleRounded sx={{ fontSize: 13, verticalAlign: -2, mr: .5 }} />
        Period: {formatDateText(report.date_from)} to {report.date_to ? formatDateText(report.date_to) : 'latest entry'}
        {' · '}{report.entry_count} included cost sheet{report.entry_count === 1 ? '' : 's'}
        {report.include_draft ? ' (drafts included)' : ' (submitted only)'}
        {' · '}{report.detail.length} classification row{report.detail.length === 1 ? '' : 's'}.
      </Typography>
    </> : null}
  </>
}

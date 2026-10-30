import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert, Box, Button, CircularProgress, Divider, MenuItem, Paper, Stack, TextField, Typography,
} from '@mui/material'
import {
  ArrowBackRounded, DownloadRounded, GridOnRounded, PictureAsPdfRounded, PlayArrowRounded,
  RefreshRounded, RestartAltRounded, SearchRounded, TableChartRounded,
} from '@mui/icons-material'
import { api, body, downloadFile } from '../lib/api'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { exportPdf, exportXlsx, type ExportColumn } from '../lib/export'
import { EMPTY_RUN, type ReportDefinition, type ReportRun } from '../lib/reportBuilder'

type Answers = Record<string, string>

export default function CustomReportViewer() {
  const { reportId } = useParams()
  const navigate = useNavigate()
  const { can } = useAuth()
  const canExport = can('custom-reports:export')

  const [report, setReport] = useState<ReportDefinition | null>(null)
  const [run, setRun] = useState<ReportRun>(EMPTY_RUN)
  const [answers, setAnswers] = useState<Answers>({})
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [exporting, setExporting] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const loadReport = useCallback(async () => {
    if (!reportId) {
      setError('That address is missing the report. Open it from Custom Reports instead.')
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const definition = await api<ReportDefinition>(`/report-builder/my-reports/${reportId}`)
      setReport(definition)
      setPageSize(definition.design.page_size || 50)
      setAnswers(Object.fromEntries(definition.design.runtime_filters.map(item => [item.key, item.default_value || ''])))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'That report could not be opened')
    } finally {
      setLoading(false)
    }
  }, [reportId])

  useEffect(() => { void loadReport() }, [loadReport])

  const execute = useCallback(async (options: { page?: number; pageSize?: number; allRows?: boolean } = {}) => {
    if (!reportId) return null
    setRunning(true)
    setError('')
    try {
      const result = await api<ReportRun>(`/report-builder/my-reports/${reportId}/run`, {
        method: 'POST', action: `Running “${report?.name ?? 'the report'}”`,
        body: body({
          date_from: dateFrom, date_to: dateTo, filters: answers, search,
          page: options.allRows ? 1 : options.page ?? page,
          page_size: options.allRows ? 500 : options.pageSize ?? pageSize,
          all_rows: Boolean(options.allRows),
        }),
      })
      if (!options.allRows) setRun(result)
      return result
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The report could not be run')
      return null
    } finally {
      setRunning(false)
    }
  }, [answers, dateFrom, dateTo, page, pageSize, report?.name, reportId, search])

  useEffect(() => {
    if (!report) return
    void execute({ page: 1 })
    // Run once per report, with the reader's defaults; later runs are explicit.
  }, [report]) // eslint-disable-line react-hooks/exhaustive-deps

  const reset = () => {
    if (!report) return
    setAnswers(Object.fromEntries(report.design.runtime_filters.map(item => [item.key, item.default_value || ''])))
    setDateFrom('')
    setDateTo('')
    setSearch('')
    setPage(1)
    void execute({ page: 1 })
  }

  const fetchAll = async (): Promise<ReportRun | null> => {
    const result = await execute({ allRows: true })
    if (!result) return null
    return result
  }

  const exportAs = async (format: 'csv' | 'xlsx' | 'pdf') => {
    if (!report) return
    setExporting(format)
    setError('')
    try {
      if (format === 'csv') {
        const query = new URLSearchParams({
          date_from: dateFrom, date_to: dateTo, search, filters: JSON.stringify(answers),
        })
        await downloadFile(`/report-builder/my-reports/${report.id}/export.csv?${query.toString()}`, `${report.name}.csv`)
        setNotice(`Downloaded every matching row of “${report.name}” as CSV.`)
      } else {
        const all = await fetchAll()
        if (!all) return
        const file = report.name.replace(/[^A-Za-z0-9 _-]/g, '-')
        const exportColumns: ExportColumn<Record<string, string>>[] = all.columns.map(column => ({ header: column.label, value: row => row[column.key] ?? '' }))
        if (format === 'xlsx') await exportXlsx(`${file}.xlsx`, all.rows, exportColumns)
        else await exportPdf(`${file}.pdf`, report.name, all.rows, exportColumns)
        await api('/report-builder/export-audit', {
          method: 'POST', silent: true,
          body: body({ report_id: report.id, report_name: report.name, format, row_count: all.total_rows }),
        })
        setNotice(`Exported ${all.total_rows.toLocaleString()} rows as ${format.toUpperCase()}.`)
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The export could not be produced')
    } finally {
      setExporting('')
    }
  }

  if (loading) return <Box py={12} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box>
  if (!report) return <>
    <PageHeading eyebrow="REPORTS / CUSTOM REPORTS" title="Report unavailable" subtitle="This report is not published for you, or it was withdrawn." />
    <ErrorMessage message={error}/>
    <Button variant="outlined" startIcon={<ArrowBackRounded/>} onClick={() => navigate('/reports/custom')}>All custom reports</Button>
  </>

  const design = report.design
  const questions = design.runtime_filters
  const missingAnswer = questions.find(question => question.required && !(answers[question.key] ?? '').trim())

  return <>
    <PageHeading
      eyebrow="REPORTS / CUSTOM REPORTS"
      title={report.name}
      subtitle={report.description || 'A published report over this workspace.'}
      action={<>
        <Button variant="outlined" startIcon={<ArrowBackRounded/>} onClick={() => navigate('/reports/custom')}>All reports</Button>
        <Button variant="outlined" startIcon={<RestartAltRounded/>} onClick={reset} disabled={running}>Reset</Button>
        <Button variant="contained" startIcon={<PlayArrowRounded/>} disabled={running || Boolean(missingAnswer)} onClick={() => { setPage(1); void execute({ page: 1 }) }}>
          {running ? 'Running...' : 'Run report'}
        </Button>
      </>}
    />
    <ErrorMessage message={error}/>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}

    <Paper variant="outlined" sx={{ p: 2, mb: 2, borderRadius: 2 }}>
      <Box sx={{ display: 'grid', gap: 1.6, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' } }}>
        {design.date_basis !== 'NONE' && <>
          <TextField size="small" type="date" label="From" value={dateFrom} InputLabelProps={{ shrink: true }}
            onChange={event => setDateFrom(event.target.value)} helperText={design.date_basis === 'CREATED_AT' ? 'Filtered on when the record was created' : design.date_basis === 'UPDATED_AT' ? 'Filtered on the last change' : `Filtered on ${design.date_column}`}/>
          <TextField size="small" type="date" label="To" value={dateTo} InputLabelProps={{ shrink: true }}
            onChange={event => setDateTo(event.target.value)} helperText="Inclusive"/>
        </>}
        {questions.map(question => question.filter_type === 'select'
          ? <TextField key={question.key} size="small" select label={question.label} value={answers[question.key] ?? ''}
            required={question.required} helperText={question.required ? 'Required' : 'Leave blank for all'}
            onChange={event => setAnswers(current => ({ ...current, [question.key]: event.target.value }))}>
            <MenuItem value="">All</MenuItem>
            {question.options.map(option => <MenuItem key={option} value={option}>{option}</MenuItem>)}
          </TextField>
          : question.filter_type === 'boolean'
            ? <TextField key={question.key} size="small" select label={question.label} value={answers[question.key] ?? ''}
              onChange={event => setAnswers(current => ({ ...current, [question.key]: event.target.value }))}>
              <MenuItem value="">All</MenuItem>
              <MenuItem value="true">Yes</MenuItem>
              <MenuItem value="false">No</MenuItem>
            </TextField>
            : <TextField key={question.key} size="small" label={question.label} value={answers[question.key] ?? ''}
              required={question.required} type={question.filter_type === 'date' ? 'date' : question.filter_type === 'number' ? 'number' : 'text'}
              InputLabelProps={question.filter_type === 'date' ? { shrink: true } : undefined}
              helperText={question.required ? 'Required' : 'Leave blank for all'}
              onChange={event => setAnswers(current => ({ ...current, [question.key]: event.target.value }))}/>)}
        <TextField size="small" label="Search the results" value={search}
          onChange={event => setSearch(event.target.value)}
          InputProps={{ startAdornment: <SearchRounded sx={{ fontSize: 17, mr: .6, color: 'text.secondary' }}/> }}
          helperText="Matches any visible column"/>
        <TextField size="small" select label="Rows per page" value={pageSize} onChange={event => setPageSize(Number(event.target.value))}>
          {[20, 50, 100].map(size => <MenuItem key={size} value={size}>{size}</MenuItem>)}
        </TextField>
      </Box>
      {missingAnswer && <Typography color="error" fontSize={12} sx={{ mt: 1.2 }}>“{missingAnswer.label || missingAnswer.key}” must be answered before this report can run.</Typography>}
      {design.date_basis === 'NONE' && <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 1.2 }}>This report has no date filter; it always shows the whole table.</Typography>}
    </Paper>

    {(run.warnings ?? []).map(warning => <Alert key={warning} severity="warning" sx={{ mb: 1.5 }}>{warning}</Alert>)}

    <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1.5} px={2} py={1.4} flexWrap="wrap" sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
          <Typography fontWeight={800} fontSize={13}>{run.total_rows.toLocaleString()} row{run.total_rows === 1 ? '' : 's'}</Typography>
          {run.grouped && <Tag tone="info">Grouped</Tag>}
          {run.matrix && <Tag tone="info">Matrix</Tag>}
          <Typography color="text.secondary" fontSize={11.5}>
            {run.stats?.elapsed_ms ? `calculated in ${run.stats.elapsed_ms} ms` : ''}
            {run.stats?.scanned ? ` · ${run.stats.scanned.toLocaleString()} rows scanned` : ''}
          </Typography>
        </Box>
        <Box display="flex" gap={.8} flexWrap="wrap">
          <Button size="small" variant="outlined" startIcon={<RefreshRounded/>} disabled={running} onClick={() => void execute({ page })}>Refresh</Button>
          {canExport && <>
            <Button size="small" variant="outlined" startIcon={<TableChartRounded/>} disabled={Boolean(exporting)} onClick={() => void exportAs('csv')}>{exporting === 'csv' ? 'Preparing...' : 'CSV'}</Button>
            <Button size="small" variant="outlined" startIcon={<GridOnRounded/>} disabled={Boolean(exporting)} onClick={() => void exportAs('xlsx')}>{exporting === 'xlsx' ? 'Preparing...' : 'Excel'}</Button>
            <Button size="small" variant="outlined" startIcon={<PictureAsPdfRounded/>} disabled={Boolean(exporting)} onClick={() => void exportAs('pdf')}>{exporting === 'pdf' ? 'Preparing...' : 'PDF'}</Button>
          </>}
        </Box>
      </Box>

      <Box sx={{ overflow: 'auto', maxHeight: '58vh' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              {run.columns.map(column => <th key={column.key} style={{
                textAlign: column.align === 'right' ? 'right' : 'left', padding: '9px 12px', fontWeight: 800,
                fontSize: 10.5, letterSpacing: 1.1, textTransform: 'uppercase', whiteSpace: 'nowrap',
                borderBottom: '1px solid var(--wcp-line)', position: 'sticky', top: 0, zIndex: 1,
                background: 'var(--wcp-paper)',
              }}>{column.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {run.rows.length === 0 && <tr><td colSpan={Math.max(1, run.columns.length)} style={{ padding: 24, color: 'var(--wcp-muted)' }}>
              {design.empty_text || 'Nothing matches the answers you gave. Widen the date range or clear a filter.'}
            </td></tr>}
            {run.rows.map((row, index) => <tr key={index} style={{ background: index % 2 ? 'var(--wcp-surface-alt)' : 'transparent' }}>
              {run.columns.map(column => <td key={column.key} style={{
                padding: '7px 12px', textAlign: column.align === 'right' ? 'right' : 'left',
                borderBottom: '1px solid var(--wcp-line)', fontVariantNumeric: 'tabular-nums',
              }}>{row[column.key] ?? ''}</td>)}
            </tr>)}
            {run.totals && Object.keys(run.totals).length > 0 && <tr>
              {run.columns.map(column => <td key={column.key} style={{
                padding: '9px 12px', fontWeight: 800, textAlign: column.align === 'right' ? 'right' : 'left',
                borderTop: '2px solid var(--wcp-line-strong)', fontVariantNumeric: 'tabular-nums',
              }}>{run.totals?.[column.key] ?? (run.columns[0]?.key === column.key ? 'Total' : '')}</td>)}
            </tr>}
          </tbody>
        </table>
      </Box>
      <Divider/>
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} px={2} py={1.2} flexWrap="wrap">
        <Typography color="text.secondary" fontSize={12}>
          Page {run.page} of {run.pages} · {run.rows.length} shown
        </Typography>
        <Box display="flex" gap={.8} alignItems="center">
          <Button size="small" variant="outlined" disabled={running || run.page <= 1} onClick={() => { const next = run.page - 1; setPage(next); void execute({ page: next }) }}>Previous</Button>
          <Button size="small" variant="outlined" disabled={running || run.page >= run.pages} onClick={() => { const next = run.page + 1; setPage(next); void execute({ page: next }) }}>Next</Button>
          <Button size="small" startIcon={<DownloadRounded sx={{ fontSize: 16 }}/>} disabled={!canExport || Boolean(exporting)} onClick={() => void exportAs('csv')}>Download all</Button>
        </Box>
      </Box>
    </Paper>

    {run.notes.length > 0 && <Stack spacing={.4} sx={{ mt: 1.5 }}>
      {run.notes.map(note => <Typography key={note} color="text.secondary" fontSize={11.5}>{note}</Typography>)}
    </Stack>}
    <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 1.5 }}>
      Generated {run.generated_at ? new Date(run.generated_at).toLocaleString() : '—'} · {design.source_table} · {report.design.columns.length} columns · version {report.version}
    </Typography>
    {run.rows.length === 0 && run.total_rows > 0 && <Typography color="text.secondary" fontSize={11.5}>
      Use “Download all” to export every matching row, not only this page.
    </Typography>}
  </>
}

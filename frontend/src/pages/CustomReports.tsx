import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import { ArrowForwardRounded, InsightsOutlined, RefreshRounded } from '@mui/icons-material'
import { api } from '../lib/api'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { reportTypeLabel, type ReportDefinitionList } from '../lib/reportBuilder'

function when(value: string | null): string {
  if (!value) return 'never run'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'never run' : `last run ${date.toLocaleDateString(undefined, { month: 'short', day: '2-digit', year: 'numeric' })}`
}

export default function CustomReports() {
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportDefinitionList | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setReports(await api<ReportDefinitionList>('/report-builder/my-reports'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Your reports could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const items = reports?.items ?? []

  return <>
    <PageHeading
      eyebrow="REPORTS / CUSTOM REPORTS"
      title="Custom Reports"
      subtitle="Every report that was published for you. Open one, answer its questions, then read, print or download the result — the report only ever shows data from this workspace."
      action={<Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={busy}>{busy ? 'Refreshing...' : 'Refresh'}</Button>}
    />
    <ErrorMessage message={error}/>
    {busy && !reports ? <Box py={10} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
      : items.length === 0
        ? <Paper variant="outlined" sx={{ p: 3.5, borderRadius: 2, textAlign: 'center' }}>
          <InsightsOutlined sx={{ fontSize: 30, color: 'text.secondary' }}/>
          <Typography fontWeight={800} sx={{ mt: 1 }}>No reports have been shared with you yet</Typography>
          <Typography color="text.secondary" fontSize={12.5} sx={{ mt: .6 }}>
            A report appears here once its designer publishes it and either shares it with everybody or names you or one of your roles.
          </Typography>
        </Paper>
        : <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(3, minmax(0, 1fr))' } }}>
          {items.map(report => <Paper key={report.id} variant="outlined" sx={{ p: 2.2, borderRadius: 2, display: 'flex', flexDirection: 'column' }}>
            <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} mb={.8}>
              <Typography fontWeight={800} fontSize={14}>{report.name}</Typography>
              <Tag tone="info">{reportTypeLabel(report.report_type)}</Tag>
            </Box>
            <Typography color="text.secondary" fontSize={12} sx={{ flex: 1 }}>{report.description || 'No description was given for this report.'}</Typography>
            <Typography color="text.secondary" fontSize={11.2} sx={{ mt: 1 }}>
              {report.design.columns.length} columns · {(report.run_count ?? 0).toLocaleString()} runs · {when(report.last_run_at)}
            </Typography>
            <Button variant="contained" size="small" endIcon={<ArrowForwardRounded/>} sx={{ mt: 1.8, alignSelf: 'flex-start' }}
              onClick={() => navigate(`/reports/custom/${report.id}`)}>Open report</Button>
          </Paper>)}
        </Box>}
    {reports && reports.counts.mine > 0 && <Alert severity="info" sx={{ mt: 2.5 }}>
      {reports.counts.mine} of these report{reports.counts.mine === 1 ? ' is' : 's are'} your own design. Use Report Builder to change them.
    </Alert>}
  </>
}

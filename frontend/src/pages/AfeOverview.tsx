import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { ArrowForwardRounded, DescriptionOutlined, FactCheckOutlined, LayersOutlined, RefreshRounded, TaskAltOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, List, ListItem, ListItemText, Paper, Typography, useTheme } from '@mui/material'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import { api } from '../lib/api'
import { totalsText, type AfeOverview as AfeOverviewData } from '../lib/afe'

function StatCard({ label, value, hint, icon }: { label: string; value: number; hint: string; icon: ReactNode }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon">{icon}</Box>
    </Box>
    <Typography className="stat-value" sx={{ fontSize: 28, my: 1 }}>{value.toLocaleString()}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
  </Paper>
}

function timeLabel(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export default function AfeOverview() {
  const { can } = useAuth()
  const theme = useTheme()
  const { mode } = useColorMode()
  const [overview, setOverview] = useState<AfeOverviewData | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setOverview(await api<AfeOverviewData>('/afe/overview'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AFE overview could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const textColor = mode === 'dark' ? '#E6EDF5' : '#16283F'
  const mutedColor = mode === 'dark' ? '#A7B8CB' : '#5B6B7F'
  const statusColors: Record<string, string> = {
    draft: mode === 'dark' ? '#6E9DD0' : '#4A6F96',
    submitted: mode === 'dark' ? '#8FB8E4' : '#2E6DA4',
    review: mode === 'dark' ? '#E0B24D' : '#A7741A',
    approval: mode === 'dark' ? '#5FBF8F' : '#1E7A4E',
  }
  const statusOption: EChartsOption = {
    animation: false,
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: mutedColor }, itemWidth: 12, itemHeight: 8 },
    series: [{
      type: 'pie',
      radius: ['52%', '76%'],
      center: ['50%', '43%'],
      avoidLabelOverlap: true,
      label: { show: true, color: textColor, formatter: '{b}\n{c}' },
      itemStyle: { borderColor: theme.palette.background.paper, borderWidth: 3 },
      data: (overview?.statuses ?? []).map(item => ({ name: item.label, value: item.count, itemStyle: { color: statusColors[item.status] } })),
    }],
  }
  const topWells = [...(overview?.top_wells ?? [])].reverse()
  const wellOption: EChartsOption = {
    animation: false,
    grid: { left: 10, right: 60, top: 12, bottom: 12, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', axisLabel: { color: mutedColor }, splitLine: { lineStyle: { color: theme.palette.divider } } },
    yAxis: { type: 'category', data: topWells.map(item => item.label), axisLabel: { color: textColor, width: 180, overflow: 'truncate' }, axisLine: { lineStyle: { color: theme.palette.divider } } },
    series: [{
      type: 'bar',
      data: topWells.map(item => Number(item.total)),
      barMaxWidth: 20,
      itemStyle: { color: theme.palette.primary.main, borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: 'right', color: mutedColor },
    }],
  }

  return <>
    <PageHeading
      eyebrow="AFE MANAGEMENT / OVERVIEW"
      title="AFE Management"
      subtitle="Well-scoped AFEs for drilling and completion, their cost estimates and approval progress across the workspace."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={load} disabled={busy}>{busy ? 'Refreshing...' : 'Refresh'}</Button>
        <Button component={RouterLink} to="/afe/register" variant="contained" endIcon={<ArrowForwardRounded/>}>Open AFE register</Button>
      </Box>}
    />
    <ErrorMessage message={error}/>
    {overview && overview.warning_afes > 0 && <Alert severity="warning" sx={{ mb: 2 }} action={<Button component={RouterLink} to="/afe/register?tab=estimation" size="small">Review</Button>}>
      {overview.warning_afes} AFE{overview.warning_afes === 1 ? '' : 's'} carry estimate warnings. Review them in AFE cost estimation before submitting.
    </Alert>}

    {busy && !overview ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : overview && <>
      <Box display="grid" gap={1.6} mb={2} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' } }}>
        <StatCard label="Active AFEs" value={overview.active_afes} hint={`${overview.drilling_afes} drilling · ${overview.completion_afes} completion`} icon={<DescriptionOutlined fontSize="small"/>}/>
        <StatCard label="Approved" value={overview.approved_afes} hint={`Approved value ${totalsText(overview.approved_by_currency)}`} icon={<TaskAltOutlined fontSize="small"/>}/>
        <StatCard label="Wells with AFEs" value={overview.wells_with_afes} hint="Wells carrying at least one active AFE" icon={<LayersOutlined fontSize="small"/>}/>
        <StatCard label="Deleted AFEs" value={overview.deleted_afes} hint="Recoverable from Deleted Entries" icon={<FactCheckOutlined fontSize="small"/>}/>
      </Box>

      <Box display="grid" gap={2} sx={{ gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1.1fr) minmax(0, 1fr)' } }}>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Typography fontWeight={800} fontSize={15}>Approval progress</Typography>
          <Typography color="text.secondary" fontSize={12} mt={.35} mb={overview.conversion_pending_afes ? .6 : 1.5}>Estimated value across all active AFEs, each in its standard currency: {totalsText(overview.totals_by_currency)}</Typography>
        {overview.conversion_pending_afes > 0 && <Typography color="warning.main" fontSize={12} mb={1.5}>{overview.conversion_pending_afes} AFE{overview.conversion_pending_afes === 1 ? ' is' : 's are'} left out until its currency conversion rates are entered.</Typography>}
          <Box height={300}><ReactECharts option={statusOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Typography fontWeight={800} fontSize={15}>Highest-cost wells</Typography>
          <Typography color="text.secondary" fontSize={12} mt={.35} mb={1.5}>Total estimate of active AFEs per well. Wells with mixed currencies show the amount without conversion.</Typography>
          {overview.top_wells.length
            ? <Box height={300}><ReactECharts option={wellOption} notMerge lazyUpdate style={{ height: '100%', width: '100%' }}/></Box>
            : <Typography color="text.secondary" fontSize={13} py={6} textAlign="center">No AFEs with estimates yet.</Typography>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Typography fontWeight={800} fontSize={15}>Status counts</Typography>
          <List dense disablePadding sx={{ mt: 1 }}>
            {overview.statuses.map(item => <ListItem key={item.status} divider disableGutters sx={{ py: 1 }}>
              <ListItemText primary={item.label} secondary={`${item.count.toLocaleString()} AFE${item.count === 1 ? '' : 's'}`}/>
              <Tag tone={item.status === 'approval' ? 'success' : item.status === 'review' ? 'warning' : item.status === 'submitted' ? 'info' : 'neutral'}>{item.label}</Tag>
            </ListItem>)}
          </List>
          <Box mt={1.5} display="flex" gap={1} flexWrap="wrap">
            {can('afe:estimate') && <Button component={RouterLink} to="/afe/register?tab=estimation" size="small" variant="outlined">Cost estimation</Button>}
            {can('afe:create') && <Button component={RouterLink} to="/afe/register" size="small" variant="outlined">Create AFE</Button>}
          </Box>
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
          <Typography fontWeight={800} fontSize={15}>Recent activity</Typography>
          <Typography color="text.secondary" fontSize={12} mt={.35} mb={1}>Latest AFE, estimate and export events from the audit trail.</Typography>
          {overview.recent_activity.length
            ? <List dense disablePadding>
              {overview.recent_activity.map(item => <ListItem key={item.id} divider disableGutters sx={{ py: 1 }}>
                <ListItemText
                  primary={item.summary || `${item.action} ${item.entity_label}`}
                  secondary={`${timeLabel(item.created_at)} · ${item.entity_label}`}
                  primaryTypographyProps={{ fontSize: 13, noWrap: true }}
                  secondaryTypographyProps={{ fontSize: 11.5 }}
                />
              </ListItem>)}
            </List>
            : <Typography color="text.secondary" fontSize={13} py={3}>No AFE activity recorded yet.</Typography>}
        </Paper>
      </Box>
    </>}
  </>
}

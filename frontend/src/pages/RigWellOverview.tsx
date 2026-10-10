import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { AddRounded, BusinessOutlined, FactCheckOutlined, LanguageOutlined, RefreshRounded, TaskAltOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, List, ListItem, ListItemText, Paper, Typography, useTheme } from '@mui/material'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import { api } from '../lib/api'
import type { RigWellOverview as RigWellOverviewData } from '../lib/rigWell'

function StatCard({ label, value, hint, icon, tone = 'navy' }: {
  label: string
  value: number
  hint: string
  icon: ReactNode
  tone?: 'navy' | 'slate' | 'blue'
}) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon" sx={{ bgcolor: tone === 'blue' ? 'primary.light' : tone === 'slate' ? 'action.hover' : 'primary.light', color: tone === 'blue' ? 'primary.main' : 'text.secondary' }}>{icon}</Box>
    </Box>
    <Typography className="stat-value" sx={{ fontSize: 28, my: 1 }}>{value.toLocaleString()}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
  </Paper>
}

function timeLabel(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export default function RigWellOverview() {
  const { can } = useAuth()
  const theme = useTheme()
  const { mode } = useColorMode()
  const [overview, setOverview] = useState<RigWellOverviewData | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setOverview(await api<RigWellOverviewData>('/rig-well/overview'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Rig & Well Management overview could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const textColor = mode === 'dark' ? '#E6EDF5' : '#16283F'
  const mutedColor = mode === 'dark' ? '#A7B8CB' : '#5B6B7F'
  const barOption: EChartsOption = {
    animation: false,
    grid: { left: 10, right: 22, top: 12, bottom: 12, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', minInterval: 1, axisLabel: { color: mutedColor }, splitLine: { lineStyle: { color: theme.palette.divider } } },
    yAxis: { type: 'category', data: [...(overview?.activity_counts ?? [])].reverse().map(item => item.label), axisLabel: { color: textColor, width: 180, overflow: 'truncate' }, axisLine: { lineStyle: { color: theme.palette.divider } } },
    series: [{ type: 'bar', data: [...(overview?.activity_counts ?? [])].reverse().map(item => item.count), barMaxWidth: 20, itemStyle: { color: theme.palette.primary.main, borderRadius: [0, 3, 3, 0] }, label: { show: true, position: 'right', color: mutedColor } }],
  }
  const lifecycleOption: EChartsOption = {
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
      data: [
        { name: 'Draft', value: overview?.draft_wells ?? 0, itemStyle: { color: mode === 'dark' ? '#6E9DD0' : '#4A6F96' } },
        { name: 'Configured', value: overview?.configured_wells ?? 0, itemStyle: { color: mode === 'dark' ? '#8FB8E4' : '#123A63' } },
        { name: 'Completed', value: overview?.completed_wells ?? 0, itemStyle: { color: mode === 'dark' ? '#445F7D' : '#9BAFC5' } },
      ],
    }],
  }

  return <>
    <PageHeading
      eyebrow="BUSINESS OPERATIONS / RIG & WELL MANAGEMENT"
      title="Rig & Well Management"
      subtitle="A single operational directory for rigs, rig-scoped wells, well plans and well-scoped sub activities."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={busy}>Refresh</Button>
        {can('rig-well:create') && <Button component={RouterLink} to="/rig-well/rigs" variant="outlined" startIcon={<AddRounded/>}>Add rig</Button>}
        {can('rig-well:create') && <Button component={RouterLink} to="/rig-well/wells" variant="contained" startIcon={<AddRounded/>}>Add well</Button>}
      </Box>}
    />

    <ErrorMessage message={error}/>
    {busy && !overview ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box> : overview && <>
      <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', sm: 'repeat(3, minmax(0, 1fr))', lg: 'repeat(6, minmax(0, 1fr))' }, mb: 2.5 }}>
        <StatCard label="Active rigs" value={overview.active_rigs} hint={`${overview.deleted_rigs} retained in Deleted Entries`} icon={<BusinessOutlined sx={{ fontSize: 18 }}/>}/>
        <StatCard label="Active wells" value={overview.active_wells} hint={`${overview.deleted_wells} deleted wells`} icon={<LanguageOutlined sx={{ fontSize: 18 }}/> } tone="blue"/>
        <StatCard label="In planning" value={overview.draft_wells} hint="Active wells with a draft plan" icon={<FactCheckOutlined sx={{ fontSize: 18 }}/> } tone="slate"/>
        <StatCard label="Configured" value={overview.configured_wells} hint={`${overview.completed_wells} completed wells`} icon={<TaskAltOutlined sx={{ fontSize: 18 }}/> } tone="blue"/>
        <StatCard label="Sub activities" value={overview.active_sub_activities} hint={`${overview.deleted_sub_activities} retained in Deleted Entries`} icon={<TaskAltOutlined sx={{ fontSize: 18 }}/>}/>
        <Paper className="stat-card" variant="outlined" sx={{ p: 2.2, borderRadius: 2, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">Operational structure</Typography>
          <Typography fontWeight={800} fontSize={15} mt={1}>Rig → Well → Sub activity</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.6}>Activities, phases and hole sections are managed in Master Data.</Typography>
        </Paper>
      </Box>

      {overview.active_rigs === 0 && <Alert severity="info" sx={{ mb: 2.2 }}>
        Start with a rig. Wells are created under a rig, and well sub activities are classified by an Activity in Master Data.
      </Alert>}

      <Box display="grid" gridTemplateColumns={{ xs: '1fr', lg: '1.1fr .9fr' }} gap={2.2}>
        <Paper variant="outlined" sx={{ p: { xs: 2, sm: 2.5 }, borderRadius: 2, minHeight: 330 }}>
          <Typography fontFamily="Manrope" fontWeight={800} fontSize={15}>Sub activities by Master Data Activity</Typography>
          <Typography color="text.secondary" fontSize={12} mt={.35} mb={1.5}>Active well sub activities grouped by their assigned Activity.</Typography>
          {overview.activity_counts.length ? <ReactECharts option={barOption} style={{ height: 245, width: '100%' }}/> : <Box minHeight={220} display="grid" sx={{ placeItems: 'center' }}><Typography color="text.secondary" fontSize={13} textAlign="center">Activity distribution will appear after sub activities are entered under wells.</Typography></Box>}
        </Paper>
        <Paper variant="outlined" sx={{ p: { xs: 2, sm: 2.5 }, borderRadius: 2, minHeight: 330 }}>
          <Typography fontFamily="Manrope" fontWeight={800} fontSize={15}>Well lifecycle</Typography>
          <Typography color="text.secondary" fontSize={12} mt={.35} mb={1}>Draft, configured and completed status across active wells.</Typography>
          <ReactECharts option={lifecycleOption} style={{ height: 268, width: '100%' }}/>
        </Paper>
      </Box>

      {can('audit:read') && <Paper variant="outlined" sx={{ mt: 2.2, p: { xs: 2, sm: 2.5 }, borderRadius: 2 }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={.5}>
          <Box><Typography fontFamily="Manrope" fontWeight={800} fontSize={15}>Recent module activity</Typography><Typography color="text.secondary" fontSize={12} mt={.35}>The latest audited rig, well, configuration and sub activity changes.</Typography></Box>
          <Button component={RouterLink} to="/audit" size="small" variant="outlined">Open audit log</Button>
        </Box>
        {overview.recent_activity.length ? <List disablePadding>
          {overview.recent_activity.map(item => <ListItem key={item.id} divider sx={{ px: 0, py: 1.1, gap: 1.4, alignItems: 'flex-start' }}>
            <Tag tone="info">{item.action.replaceAll('_', ' ')}</Tag>
            <ListItemText
              primary={<Typography fontSize={12.5} fontWeight={700}>{item.summary}</Typography>}
              secondary={<Typography component="span" fontSize={11} color="text.secondary">{item.entity_label} · {timeLabel(item.created_at)}</Typography>}
              sx={{ my: 0 }}
            />
          </ListItem>)}
        </List> : <Typography color="text.secondary" fontSize={13} py={3}>No audited rig or well activity yet.</Typography>}
      </Paper>}
    </>}
  </>
}

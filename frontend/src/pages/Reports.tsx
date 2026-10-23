import { useEffect, useState, type ComponentType, type ReactNode } from 'react'
import {
  AssessmentOutlined, ArrowForwardRounded, BuildOutlined, HistoryOutlined, Inventory2Outlined,
  PrecisionManufacturingOutlined, QueryStatsOutlined, ScheduleRounded, ScienceOutlined,
  StorefrontOutlined, WaterDropOutlined,
} from '@mui/icons-material'
import { Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { ErrorMessage, PageHeading } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import type { AfeOverview } from '../lib/afe'
import type { DailyCostOverview } from '../lib/dailyCost'
import type { RigWellOverview } from '../lib/rigWell'

const USAGE_REPORT_CARDS = [
  {
    path: '/reports/mud-chemicals-usage', title: 'Mud chemicals usage', icon: ScienceOutlined,
    description: 'Matrix of chemicals by well and hole section, with usage quantities, costs and section sub headers.',
  },
  {
    path: '/reports/drill-bits-usage', title: 'Drill bits usage', icon: PrecisionManufacturingOutlined,
    description: 'Drill bit matrix with make, model, size and IADC details, section usage and costs per well.',
  },
  {
    path: '/reports/tangibles-usage', title: 'Tangibles usage', icon: Inventory2Outlined,
    description: 'Categorized tangible matrix with category and subcategory grouping, section usage and costs per well.',
  },
  {
    path: '/reports/service-wise-cost', title: 'Service-wise cost', icon: BuildOutlined,
    description: 'Total service costs per well and hole section across every daily cost sheet in the selected range.',
  },
  {
    path: '/reports/vendor-wise-cost', title: 'Vendor/company-wise cost', icon: StorefrontOutlined,
    description: 'Total costs booked per vendor or recorded company, with cost-group and section breakdowns per well.',
  },
  {
    path: '/reports/npt-upa', title: 'NPT/UPA report', icon: ScheduleRounded,
    description: 'NPT and UPA days and costs per well, alongside planned activity, for the selected filters.',
  },
]

function ReportCard({ path, title, description, icon: Icon }: {
  path: string; title: string; description: string; icon: ComponentType
}) {
  return <Paper variant="outlined" sx={{ p: 2.2, borderRadius: 2, height: '100%', display: 'flex', flexDirection: 'column' }}>
    <Box display="flex" alignItems="center" gap={1.2} mb={1}>
      <Box className="table-icon"><Icon /></Box>
      <Typography fontWeight={800} fontSize={14}>{title}</Typography>
    </Box>
    <Typography color="text.secondary" fontSize={12} sx={{ flex: 1 }}>{description}</Typography>
    <Button component={RouterLink} to={path} variant="contained" size="small" endIcon={<ArrowForwardRounded />} sx={{ mt: 1.7, alignSelf: 'flex-start' }}>
      Open report
    </Button>
  </Paper>
}

type Activity = { id: string; action: string; entity_type: string; entity_label: string; summary: string; created_at: string }
type Dashboard = { wells: RigWellOverview | null; afes: AfeOverview | null; daily: DailyCostOverview | null; activity: Activity[] }

function StatCard({ label, value, note, icon }: { label: string; value: string | number; note: string; icon: ReactNode }) {
  return <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, minWidth: 0 }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={10.5} fontWeight={800} letterSpacing={.75} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon">{icon}</Box>
    </Box>
    <Typography sx={{ fontSize: 23, my: .8, fontWeight: 800 }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11.2}>{note}</Typography>
  </Paper>
}

export default function Reports() {
  const { can } = useAuth()
  const canReadRig = can('rig-well:read')
  const canReadAfe = can('afe:read')
  const canReadDaily = can('daily-cost:read')
  const [dashboard, setDashboard] = useState<Dashboard>({ wells: null, afes: null, daily: null, activity: [] })
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const requests = Promise.allSettled([
      canReadRig ? api<RigWellOverview>('/rig-well/overview') : Promise.resolve(null),
      canReadAfe ? api<AfeOverview>('/afe/overview') : Promise.resolve(null),
      canReadDaily ? api<DailyCostOverview>('/daily-cost/overview') : Promise.resolve(null),
    ])
    requests.then(results => {
      if (!active) return
      const errors: string[] = []
      const wells = results[0].status === 'fulfilled' ? results[0].value : null
      const afes = results[1].status === 'fulfilled' ? results[1].value : null
      const daily = results[2].status === 'fulfilled' ? results[2].value : null
      results.forEach((result, index) => {
        if (result.status === 'rejected') errors.push(`${['Rig & Well', 'AFE', 'Daily Cost'][index]} summary: ${result.reason instanceof Error ? result.reason.message : 'could not be loaded'}`)
      })
      const activity = [
        ...(wells?.recent_activity ?? []),
        ...(afes?.recent_activity ?? []),
        ...(daily?.recent_activity ?? []),
      ].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 8)
      setDashboard({ wells, afes, daily, activity })
      setError(errors.join(' · '))
    }).finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [canReadRig, canReadAfe, canReadDaily])

  const reportCount = Number(canReadRig && (canReadAfe || canReadDaily)) + Number(canReadDaily) * 7

  return <>
    <PageHeading
      eyebrow="REPORTS / OVERVIEW"
      title="Reports"
      subtitle="Consolidated views of well plans, AFE budgets and actual costs across your workspace."
    />
    <ErrorMessage message={error}/>
    {busy ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box> : <>
      <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }} gap={1.5} mb={2}>
        <StatCard label="Available reports" value={reportCount} note="Consolidated workspace reports" icon={<AssessmentOutlined/>}/>
        {canReadRig && <StatCard
          label="Active wells"
          value={dashboard.wells?.active_wells ?? '—'}
          note="Wells in the workspace register"
          icon={<QueryStatsOutlined/>}
        />}
        {canReadAfe && <StatCard label="Active AFEs" value={dashboard.afes?.active_afes ?? '—'} note="Current AFE records" icon={<AssessmentOutlined/>}/>}
        {canReadDaily && <StatCard label="Wells with actuals" value={dashboard.daily?.wells_tracked ?? '—'} note="Wells with daily cost entries" icon={<HistoryOutlined/>}/>}
      </Box>
      {!canReadAfe && <Typography color="text.secondary" fontSize={12} sx={{ mb: 1.5 }}>AFE figures are shown only to users with AFE read access.</Typography>}
      {!canReadDaily && <Typography color="text.secondary" fontSize={12} sx={{ mb: 1.5 }}>Actual cost figures are shown only to users with daily cost read access.</Typography>}
      {canReadRig && (canReadAfe || canReadDaily) && <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 }, borderRadius: 2 }}>
        <Box display="flex" alignItems="flex-start" gap={2}>
          <Box className="table-icon" sx={{ width: 42, height: 42, flex: '0 0 auto' }}><AssessmentOutlined/></Box>
          <Box minWidth={0} flex={1}>
            <Typography variant="overline" color="text.secondary">AVAILABLE REPORT</Typography>
            <Typography variant="h5" sx={{ mt: .25 }}>Well-wise cost comparisons</Typography>
            <Typography color="text.secondary" fontSize={13} sx={{ mt: .75, maxWidth: 760 }}>
              Compare configured wells, AFE totals and daily actuals. Review planned versus actual days, remaining budget and cost utilisation, then open a well's detailed cost analysis.
            </Typography>
            <Button
              component={RouterLink}
              to="/reports/well-cost-comparison"
              variant="contained"
              endIcon={<ArrowForwardRounded/>}
              sx={{ mt: 2 }}
            >Open report</Button>
          </Box>
        </Box>
      </Paper>}
      {canReadDaily && <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 }, borderRadius: 2, mt: 2 }}>
        <Box display="flex" alignItems="flex-start" gap={2}>
          <Box className="table-icon" sx={{ width: 42, height: 42, flex: '0 0 auto' }}><WaterDropOutlined/></Box>
          <Box minWidth={0} flex={1}>
            <Typography variant="overline" color="text.secondary">AVAILABLE REPORT</Typography>
            <Typography variant="h5" sx={{ mt: .25 }}>Consumption and losses</Typography>
            <Typography color="text.secondary" fontSize={13} sx={{ mt: .75, maxWidth: 760 }}>
              Review cumulative surface and other mud losses as a section-by-mud-type matrix, then drill through by date, month or a required date range and export the filtered detail.
            </Typography>
            <Button component={RouterLink} to="/reports/consumption-losses" variant="contained" endIcon={<ArrowForwardRounded/>} sx={{ mt: 2 }}>Open report</Button>
          </Box>
        </Box>
      </Paper>}
      {canReadDaily && <>
        <Box display="flex" alignItems="center" gap={1} mt={2.5} mb={1.2}>
          <AssessmentOutlined sx={{ color: 'text.secondary', fontSize: 19 }}/>
          <Typography variant="h5">Usage, cost and NPT/UPA reports</Typography>
        </Box>
        <Box display="grid" gap={1.6} gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(3, minmax(0, 1fr))' }}>
          {USAGE_REPORT_CARDS.map(card => (
            <ReportCard key={card.path} path={card.path} title={card.title} description={card.description} icon={card.icon}/>
          ))}
        </Box>
      </>}
      <Paper variant="outlined" sx={{ p: { xs: 2, sm: 2.5 }, borderRadius: 2, mt: 2 }}>
        <Box display="flex" alignItems="center" gap={1} mb={1.2}>
          <HistoryOutlined sx={{ color: 'text.secondary', fontSize: 18 }}/>
          <Box>
            <Typography fontWeight={800} fontSize={14}>Recent source activity</Typography>
            <Typography color="text.secondary" fontSize={11.5}>Latest updates from the modules contributing to reports.</Typography>
          </Box>
        </Box>
        {dashboard.activity.length === 0
          ? <Typography color="text.secondary" fontSize={12.5}>No recent source activity is available.</Typography>
          : dashboard.activity.map(item => <Box key={`${item.entity_type}-${item.id}`} display="grid" gridTemplateColumns={{ xs: '1fr', md: '180px 1fr 180px' }} gap={1} alignItems="center" sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1 }}>
              <Typography fontSize={11.5} color="text.secondary" className="tnum">{new Date(item.created_at).toLocaleString()}</Typography>
              <Typography fontSize={12.5}>{item.summary || `${item.action} ${item.entity_type}`}</Typography>
              <Typography fontSize={11.5} color="text.secondary" noWrap>{item.entity_label || item.entity_type.replace(/_/g, ' ')}</Typography>
            </Box>)}
      </Paper>
    </>}
  </>
}

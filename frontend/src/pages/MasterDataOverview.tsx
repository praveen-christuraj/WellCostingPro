import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { ArrowForwardRounded, DeleteOutlineRounded, Inventory2Outlined, LibraryBooksOutlined, StorageOutlined } from '@mui/icons-material'
import { Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import { api } from '../lib/api'
import type { MasterDataActivity, MasterDataOverview as OverviewData } from '../lib/masterData'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'

// Vendors and PO/SO Orders have their own pages; the reference lists share one.
const CONSUMABLE_KEYS = ['mud-chemicals', 'cement-additives', 'fuel-types', 'drill-bits']

const modulePath = (key: string) => {
  if (key === 'vendors' || key === 'po-so-orders' || key === 'services') return `/master-data/${key}`
  if (key === 'tangibles') return '/master-data/tangibles'
  if (CONSUMABLE_KEYS.includes(key)) return `/master-data/consumables?type=${key}`
  return `/master-data/records?module=${key}`
}

function activityTone(action: string): 'neutral' | 'success' | 'info' | 'warning' {
  if (action === 'create' || action === 'restore' || action === 'import') return 'success'
  if (action === 'soft_delete' || action === 'permanent_delete') return 'warning'
  return 'info'
}

function RecentActivity({ entries }: { entries: MasterDataActivity[] }) {
  if (!entries.length) {
    return <Box display="grid" sx={{ placeItems: 'center', minHeight: 200, color: 'text.secondary' }}>
      <Typography fontSize={13}>Master data activity will appear here.</Typography>
    </Box>
  }
  return <Box>
    {entries.map(entry => <Box key={entry.id} display="flex" alignItems="flex-start" gap={1.2} sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1.45 }}>
      <Tag tone={activityTone(entry.action)}>{entry.action.replaceAll('_', ' ')}</Tag>
      <Box flex={1} minWidth={0}>
        <Typography fontSize={12} fontWeight={700} noWrap>{entry.entity_label}</Typography>
        <Typography color="text.secondary" fontSize={11.5}>{entry.summary}</Typography>
        <Typography color="text.disabled" fontSize={10.5} mt={.35}>{new Date(entry.created_at).toLocaleString()}</Typography>
      </Box>
    </Box>)}
  </Box>
}

export default function MasterDataOverview() {
  const [data, setData] = useState<OverviewData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<OverviewData>('/master-data/overview')
      .then(setData)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : 'Could not load the module summary'))
  }, [])

  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / OVERVIEW"
      title="Master Data Management"
      subtitle="Workspace-wide reference data: units, currencies, well activities, drilling and completion services, vendors, and their PO/SO orders with attachments."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/master-data/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        <Button component={RouterLink} to="/master-data/records" variant="contained" endIcon={<ArrowForwardRounded/>}>Manage master data</Button>
      </Box>}
    />
    <ErrorMessage message={error}/>
    {!data ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box> : <>
      <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' } }}>
        <Paper className="stat-card" variant="outlined">
          <Box className="stat-icon" sx={{ color: 'primary.main', bgcolor: 'var(--surface-accent)' }}><StorageOutlined sx={{ fontSize: 21 }}/></Box>
          <Typography className="stat-value">{data.active_records}</Typography>
          <Typography fontWeight={700} fontSize={13}>Active records</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.5}>Available to well-costing workflows</Typography>
        </Paper>
        <Paper className="stat-card" variant="outlined">
          <Box className="stat-icon" sx={{ color: 'warning.main', bgcolor: 'var(--surface-muted)' }}><DeleteOutlineRounded sx={{ fontSize: 21 }}/></Box>
          <Typography className="stat-value">{data.deleted_records}</Typography>
          <Typography fontWeight={700} fontSize={13}>Deleted entries</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.5}>Recoverable until permanently removed</Typography>
        </Paper>
        <Paper className="stat-card" variant="outlined">
          <Box className="stat-icon" sx={{ color: 'secondary.main', bgcolor: 'var(--surface-accent)' }}><LibraryBooksOutlined sx={{ fontSize: 21 }}/></Box>
          <Typography className="stat-value">{data.module_count}</Typography>
          <Typography fontWeight={700} fontSize={13}>Reference data types</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.5}>Reference lists, vendors, and PO/SO orders</Typography>
        </Paper>
      </Box>

      <Box className="overview-grid">
        <Paper className="content-card" variant="outlined">
          <Box display="flex" justifyContent="space-between" alignItems="start" mb={1.5}>
            <Box>
              <Typography fontWeight={800} fontFamily="Manrope" fontSize={16}>Data by type</Typography>
              <Typography fontSize={12} color="text.secondary" mt={.5}>Active and deleted workspace records</Typography>
            </Box>
            <Tag tone="info">{data.active_records + data.deleted_records} total</Tag>
          </Box>
          {data.modules.map(module => <Box key={module.key} display="flex" alignItems="center" gap={1.5} sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1.6 }}>
            <Box className="table-icon"><Inventory2Outlined sx={{ fontSize: 17 }}/></Box>
            <Box flex={1} minWidth={0}>
              <Typography fontSize={12.5} fontWeight={700}>{module.label}</Typography>
              <Typography color="text.secondary" fontSize={11}>{module.active_count} active · {module.deleted_count} deleted</Typography>
            </Box>
            <Button component={RouterLink} to={modulePath(module.key)} size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 16 }}/>}>Open</Button>
          </Box>)}
        </Paper>

        <Paper className="content-card" variant="outlined">
          <Box display="flex" justifyContent="space-between" alignItems="start" mb={2.2}>
            <Box>
              <Typography fontWeight={800} fontFamily="Manrope" fontSize={16}>Recent activity</Typography>
              <Typography fontSize={12} color="text.secondary" mt={.5}>Changes and lifecycle events, audit logged</Typography>
            </Box>
            <Tag tone="success">Audit enabled</Tag>
          </Box>
          <RecentActivity entries={data.recent_activity}/>
        </Paper>
      </Box>
    </>}
  </>
}

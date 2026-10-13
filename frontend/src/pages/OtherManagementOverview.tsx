import { useEffect, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import { ArrowForwardRounded, HistoryOutlined, StorageOutlined, TableRowsOutlined } from '@mui/icons-material'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import type { AuditPage } from '../lib/types'
import type { TableCatalogue } from '../lib/databaseBrowser'

function StatCard({ label, value, hint, icon }: { label: string; value: string | number | undefined; hint: string; icon: ReactNode }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon" sx={{ bgcolor: 'primary.light', color: 'text.secondary' }}>{icon}</Box>
    </Box>
    <Typography className="stat-value" sx={{ fontSize: 28, my: 1 }}>{value === undefined ? '…' : typeof value === 'number' ? value.toLocaleString() : value}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
  </Paper>
}

// Module dashboard for Other Managements. Each figure comes from an endpoint the user is
// allowed to call; the API stays the authority, so a missing permission simply hides the card.
export default function OtherManagementOverview() {
  const { can } = useAuth()
  const canAudit = can('audit:read')
  const canBrowse = can('database-browser:read')
  const [audit, setAudit] = useState<AuditPage | null>(null)
  const [weekTotal, setWeekTotal] = useState<number | undefined>(undefined)
  const [catalogue, setCatalogue] = useState<TableCatalogue | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const weekAgo = new Date(Date.now() - 6 * 24 * 60 * 60 * 1000)
    const from = `${weekAgo.getFullYear()}-${String(weekAgo.getMonth() + 1).padStart(2, '0')}-${String(weekAgo.getDate()).padStart(2, '0')}`
    const tasks: Promise<void>[] = []
    if (canAudit) {
      tasks.push(api<AuditPage>('/audit?page=1&page_size=20').then(page => { if (active) setAudit(page) }))
      tasks.push(api<AuditPage>(`/audit?page=1&page_size=20&date_from=${from}`).then(page => { if (active) setWeekTotal(page.total) }))
    }
    if (canBrowse) tasks.push(api<TableCatalogue>('/database-browser/tables').then(data => { if (active) setCatalogue(data) }))
    Promise.all(tasks)
      .catch(caught => { if (active) setError(caught instanceof Error ? caught.message : 'The module summary could not be loaded') })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [canAudit, canBrowse])

  return <>
    <PageHeading
      eyebrow="DASHBOARD / OTHER MANAGEMENTS"
      title="Other Managements"
      subtitle="The audit trail and workspace database tools: review who changed what, and browse the data and structure behind every module."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        {canAudit && <Button component={RouterLink} to="/other-management/audit" variant="outlined" endIcon={<ArrowForwardRounded/>}>Audit Log</Button>}
        {canBrowse && <Button component={RouterLink} to="/other-management/database" variant="contained" endIcon={<ArrowForwardRounded/>}>Database Browser</Button>}
      </Box>}
    />
    <ErrorMessage message={error}/>
    {busy ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box> : <>
      <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }, mb: 2.5 }}>
        {canAudit && <StatCard label="Audit entries" value={audit?.total} hint="Recorded actions in this workspace" icon={<HistoryOutlined sx={{ fontSize: 18 }}/>}/>}
        {canAudit && <StatCard label="Last 7 days" value={weekTotal} hint="Actions recorded this week" icon={<HistoryOutlined sx={{ fontSize: 18 }}/>}/>}
        {canBrowse && <StatCard label="Database tables" value={catalogue?.total_tables} hint="Tables available to browse" icon={<StorageOutlined sx={{ fontSize: 18 }}/>}/>}
        {canBrowse && <StatCard label="Database records" value={catalogue?.total_rows} hint="Rows across the workspace tables" icon={<TableRowsOutlined sx={{ fontSize: 18 }}/>}/>}
      </Box>

      {canAudit && <Paper variant="outlined" sx={{ p: { xs: 2, sm: 2.5 }, borderRadius: 2, borderColor: 'divider' }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" mb={1.5}>
          <Box>
            <Typography fontFamily="Manrope" fontWeight={800} fontSize={15}>Recent activity</Typography>
            <Typography color="text.secondary" fontSize={12} mt={.35}>The latest actions across the workspace, from the audit trail.</Typography>
          </Box>
          <Tag tone="info">Read-only</Tag>
        </Box>
        {audit && audit.items.length === 0 && <Typography color="text.secondary" fontSize={13}>No actions recorded yet.</Typography>}
        {audit?.items.slice(0, 8).map(entry => <Box key={entry.id} display="grid" gridTemplateColumns={{ xs: '1fr', md: '190px 1fr 200px' }} gap={1.2} alignItems="center" sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1.1 }}>
          <Typography fontSize={12} color="text.secondary" className="tnum">{new Date(entry.created_at).toLocaleString()}</Typography>
          <Typography fontSize={12.5} noWrap>{entry.summary || `${entry.action} ${entry.entity_type}`}</Typography>
          <Typography fontSize={12} color="text.secondary" noWrap>{entry.actor_name || 'System'} · {entry.entity_type.replace(/_/g, ' ')}</Typography>
        </Box>)}
      </Paper>}
      {!canAudit && !canBrowse && <Typography color="text.secondary" fontSize={13}>No Other Managements tools are assigned to your role.</Typography>}
    </>}
  </>
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Box, Button, MenuItem, TextField, Typography } from '@mui/material'
import { FilterListRounded, RefreshRounded } from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { api } from '../lib/api'
import type { AuditEntry, AuditPage } from '../lib/types'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { DataTable } from '../components/DataTable'

const ACTIONS = ['login', 'login_failed', 'logout', 'create', 'update', 'delete', 'soft_delete', 'restore', 'permanent_delete', 'import', 'export', 'assign']
const ENTITIES = ['auth', 'user', 'role', 'permission', 'master_data', 'rig', 'well', 'well_configuration', 'well_sub_activity', 'rig_well_export', 'rig_well_deleted']

// Auditing module: read-only action trail with server-side filters and export.
export default function AuditLog() {
  const [rows, setRows] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [action, setAction] = useState('')
  const [entityType, setEntityType] = useState('')
  const [actor, setActor] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const load = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const params = new URLSearchParams({ page: '1', page_size: '100' })
      if (action) params.set('action', action)
      if (entityType) params.set('entity_type', entityType)
      if (actor.trim()) params.set('actor', actor.trim())
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo) params.set('date_to', dateTo)
      const page = await api<AuditPage>(`/audit?${params.toString()}`)
      setRows(page.items)
      setTotal(page.total)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }, [action, entityType, actor, dateFrom, dateTo])
  useEffect(() => { load() }, [load])

  const columns = useMemo<ColDef<AuditEntry>[]>(() => [
    { headerName: 'TIME', field: 'created_at', minWidth: 155, valueFormatter: p => p.value ? new Date(p.value).toLocaleString() : '' },
    { headerName: 'ACTOR', field: 'actor_email', minWidth: 190, cellRenderer: ({ data }: { data: AuditEntry }) => data && <Box display="flex" alignItems="center" height="100%"><Box><Typography fontWeight={700} fontSize={12}>{data.actor_name || 'System'}</Typography><Typography color="text.secondary" fontSize={11}>{data.actor_email}</Typography></Box></Box> },
    { headerName: 'ACTION', field: 'action', width: 130, flex: 0, cellRenderer: ({ value }: { value: string }) => <Box display="flex" alignItems="center" height="100%\"><Tag tone={value.includes('failed') ? 'warning' : 'info'}>{String(value).replace('_', ' ')}</Tag></Box> },
    { headerName: 'ENTITY', field: 'entity_type', minWidth: 170, cellRenderer: ({ data }: { data: AuditEntry }) => data && <Box display="flex" alignItems="center" height="100%" gap={.8}><Tag>{data.entity_type}</Tag><Typography fontSize={11.5} color="text.secondary" noWrap>{data.entity_label}</Typography></Box> },
    { headerName: 'SUMMARY', field: 'summary', minWidth: 260 },
    { headerName: 'IP ADDRESS', field: 'ip_address', minWidth: 125, valueFormatter: p => p.value || '—' },
  ], [])

  return <><PageHeading eyebrow="AUDITING / ACTION TRAIL" title="Audit Log" subtitle="Every action across the workspace, with actor, entity and source. Read-only." action={<Button variant="contained" startIcon={<RefreshRounded/>} onClick={load} disabled={busy}>{busy ? 'Refreshing...' : 'Refresh'}</Button>}/>
    <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 2, mb: 2.2, bgcolor: 'background.paper' }}>
      <Box display="flex" alignItems="center" gap={1} mb={1.6}><FilterListRounded sx={{ fontSize: 17, color: 'text.secondary' }}/><Typography fontWeight={800} fontSize={12} textTransform="uppercase" letterSpacing={0.8}>Filters</Typography></Box>
      <Box display="flex" gap={1.5} flexWrap="wrap" alignItems="center">
        <TextField select size="small" label="Action" value={action} onChange={e => setAction(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="">All actions</MenuItem>
          {ACTIONS.map(a => <MenuItem key={a} value={a}>{a.replace('_', ' ')}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Entity" value={entityType} onChange={e => setEntityType(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="">All entities</MenuItem>
          {ENTITIES.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
        </TextField>
        <TextField size="small" label="Actor (name or email)" value={actor} onChange={e => setActor(e.target.value)} sx={{ minWidth: 200 }}/>
        <Typography color="text.secondary" fontSize={12} fontWeight={700} textTransform="uppercase" letterSpacing={0.8} ml={1}>Date range</Typography>
        <TextField size="small" type="date" label="From" value={dateFrom} onChange={e => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }}/>
        <Typography color="text.secondary" fontSize={12}>to</Typography>
        <TextField size="small" type="date" label="To" value={dateTo} onChange={e => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }}/>
        {(action || entityType || actor || dateFrom || dateTo) && <Button color="inherit" size="small" onClick={() => { setAction(''); setEntityType(''); setActor(''); setDateFrom(''); setDateTo('') }}>Clear</Button>}
      </Box>
    </Box>
    <ErrorMessage message={error}/>
    <DataTable rows={rows} columns={columns} searchPlaceholder="Search loaded entries..." exportName="audit-log"/>
    {total > rows.length && <Typography fontSize={12} color="text.secondary" mt={1.5}>Showing the latest {rows.length} of {total} matching entries. Narrow the date range to see older records.</Typography>}
  </>
}

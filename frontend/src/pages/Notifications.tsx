import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Autocomplete, Box, Button, Checkbox, CircularProgress, Divider, Menu, MenuItem, Paper, Tab, Table,
  TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, Tabs, TextField, Tooltip, Typography,
} from '@mui/material'
import {
  CampaignRounded, CheckRounded, DeleteOutlineRounded, DoneAllRounded, FilterListRounded, MarkEmailUnreadRounded,
  OpenInNewRounded, RefreshRounded,
} from '@mui/icons-material'
import { useNavigate } from 'react-router-dom'
import { ErrorMessage, FormDialog, PageHeading, Tag, type Tone } from '../components/Common'
import { api, body } from '../lib/api'
import { exportCsv, exportPdf, exportXlsx, type ExportColumn } from '../lib/export'
import type { Announcement, AnnouncementPage, NotificationOverview, NotificationPage, UserNotification } from '../lib/workflowTypes'
import { notifyNotificationsChanged, onNotificationsChanged } from '../lib/uiEvents'
import type { Role, User } from '../lib/types'
import { useAuth } from '../context/AuthContext'

const PAGE_SIZES = [20, 50, 100]
const SEVERITIES = ['info', 'success', 'warning', 'error'] as const
const SEVERITY_TONE: Record<string, Tone> = { info: 'info', success: 'success', warning: 'warning', error: 'error' }
const SEVERITY_LABEL: Record<string, string> = { info: 'Information', success: 'Success', warning: 'Warning', error: 'Urgent' }
const emptyAnnouncement = { title: '', message: '', severity: 'info', action_path: '', audience: 'all' as 'all' | 'roles' | 'users' }

function StatCard({ label, value, hint, tone = 'info' }: { label: string; value: number | undefined; hint: string; tone?: Tone }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
    <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
    <Typography className="stat-value" sx={{ fontSize: 26, my: .8 }}>{value === undefined ? '…' : value}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
    <Box sx={{ mt: 1, height: 3, borderRadius: 2, bgcolor: `var(--wcp-tone-${tone}-border)` }}/>
  </Paper>
}

export default function Notifications() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const canManage = can('notifications:manage')
  const [tab, setTab] = useState<'inbox' | 'sent'>('inbox')
  const [overview, setOverview] = useState<NotificationOverview | null>(null)
  const [items, setItems] = useState<UserNotification[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [exportAnchor, setExportAnchor] = useState<HTMLElement | null>(null)

  // Filters (server-side, so the pager and the totals always agree)
  const [status, setStatus] = useState('')
  const [severity, setSeverity] = useState('')
  const [type, setType] = useState('')
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(20)
  const [types, setTypes] = useState<string[]>([])

  // Announcement composer
  const [composer, setComposer] = useState(false)
  const [form, setForm] = useState(emptyAnnouncement)
  const [roleChoices, setRoleChoices] = useState<Role[]>([])
  const [userChoices, setUserChoices] = useState<User[]>([])
  const [chosenRoles, setChosenRoles] = useState<Role[]>([])
  const [chosenUsers, setChosenUsers] = useState<User[]>([])
  const [busy, setBusy] = useState(false)
  const [dialogError, setDialogError] = useState('')

  // Sent announcements
  const [sent, setSent] = useState<Announcement[]>([])
  const [sentTotal, setSentTotal] = useState(0)
  const [sentPage, setSentPage] = useState(0)
  const [sentPageSize, setSentPageSize] = useState(20)
  const [recallTarget, setRecallTarget] = useState<Announcement | null>(null)

  const loadInbox = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    setError('')
    const params = new URLSearchParams({ page: String(page + 1), page_size: String(pageSize) })
    if (status) params.set('status', status)
    if (severity) params.set('severity', severity)
    if (type) params.set('type', type)
    if (search.trim()) params.set('search', search.trim())
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    try {
      const [data, summary] = await Promise.all([
        api<NotificationPage>(`/notifications?${params.toString()}`, { action: 'Load the notification inbox' }),
        api<NotificationOverview>('/notifications/overview', { action: 'Load the notification summary' }),
      ])
      setItems(data.items); setTotal(data.total); setOverview(summary)
      setTypes(current => Array.from(new Set([...current, ...Object.keys(summary.by_type)])))
      setSelected(ids => ids.filter(id => data.items.some(item => item.id === id)))
    } catch (caught) { setError((caught as Error).message) } finally { setLoading(false) }
  }, [page, pageSize, status, severity, type, search, dateFrom, dateTo])
  useEffect(() => { void loadInbox() }, [loadInbox])
  // The bell changes the same rows. A quiet reload keeps the list truthful
  // without flashing the table spinner on every mark-read.
  useEffect(() => onNotificationsChanged(() => void loadInbox(true)), [loadInbox])

  const loadSent = useCallback(async () => {
    if (!canManage) return
    try {
      const params = new URLSearchParams({ page: String(sentPage + 1), page_size: String(sentPageSize) })
      const data = await api<AnnouncementPage>(`/notifications/announcements?${params.toString()}`, { action: 'Load sent announcements' })
      setSent(data.items); setSentTotal(data.total)
    } catch (caught) { setError((caught as Error).message) }
  }, [canManage, sentPage, sentPageSize])
  useEffect(() => { void loadSent() }, [loadSent])

  const clearFilters = () => {
    setStatus(''); setSeverity(''); setType(''); setSearch(''); setDateFrom(''); setDateTo(''); setPage(0)
  }
  const activeFilters = !!(status || severity || type || search || dateFrom || dateTo)

  const openItem = async (item: UserNotification) => {
    if (!item.read_at) {
      await api(`/notifications/${item.id}/read`, { method: 'POST', action: 'Mark the notification read' })
      setItems(rows => rows.map(row => row.id === item.id ? { ...row, read_at: new Date().toISOString() } : row))
      setOverview(current => current ? { ...current, unread: Math.max(0, current.unread - 1) } : current)
      notifyNotificationsChanged()
    }
    if (item.action_path) navigate(item.action_path)
  }

  const toggleRead = async (item: UserNotification) => {
    if (item.read_at) {
      await api(`/notifications/${item.id}/unread`, { method: 'POST', action: 'Mark the notification unread' })
      setItems(rows => rows.map(row => row.id === item.id ? { ...row, read_at: null } : row))
      setOverview(current => current ? { ...current, unread: current.unread + 1 } : current)
    } else {
      await api(`/notifications/${item.id}/read`, { method: 'POST', action: 'Mark the notification read' })
      setItems(rows => rows.map(row => row.id === item.id ? { ...row, read_at: new Date().toISOString() } : row))
      setOverview(current => current ? { ...current, unread: Math.max(0, current.unread - 1) } : current)
    }
    notifyNotificationsChanged()
  }

  const markAll = async () => {
    await api('/notifications/read-all', { method: 'POST', action: 'Mark every notification read' })
    setNotice('Every notification is marked read.')
    notifyNotificationsChanged()
  }

  const markSelectedRead = async () => {
    if (!selected.length) return
    await api('/notifications/read', { method: 'POST', body: body({ ids: selected }), action: 'Mark the selected notifications read' })
    setNotice(`${selected.length} notification(s) marked read.`)
    setSelected([])
    notifyNotificationsChanged()
  }

  const dismissSelected = async () => {
    if (!selected.length) return
    await Promise.all(selected.map(id => api(`/notifications/${id}`, { method: 'DELETE', action: 'Dismiss the notification' })))
    setNotice(`${selected.length} notification(s) dismissed.`)
    setSelected([])
    notifyNotificationsChanged()
  }

  const dismissOne = async (item: UserNotification) => {
    await api(`/notifications/${item.id}`, { method: 'DELETE', action: 'Dismiss the notification' })
    setNotice('Notification dismissed.')
    notifyNotificationsChanged()
  }

  const openComposer = async () => {
    setComposer(true); setDialogError(''); setForm(emptyAnnouncement); setChosenRoles([]); setChosenUsers([])
    const loads: Promise<void>[] = []
    if (can('roles:read')) loads.push(api<Role[]>('/roles', { action: 'Load roles', silent: true }).then(setRoleChoices).catch(() => setRoleChoices([])))
    if (can('users:read')) loads.push(api<User[]>('/users', { action: 'Load users', silent: true }).then(setUserChoices).catch(() => setUserChoices([])))
    await Promise.all(loads)
  }

  const sendAnnouncement = async () => {
    setBusy(true); setDialogError('')
    try {
      await api('/notifications', {
        method: 'POST',
        action: 'Send the announcement',
        body: body({
          title: form.title.trim(),
          message: form.message.trim(),
          severity: form.severity,
          action_path: form.action_path.trim(),
          recipient_user_ids: form.audience === 'users' ? chosenUsers.map(item => item.id) : [],
          recipient_role_ids: form.audience === 'roles' ? chosenRoles.map(item => item.id) : [],
        }),
      })
      const audience = form.audience === 'all' ? 'every active user' : `${form.audience === 'roles' ? chosenRoles.length : chosenUsers.length} selected ${form.audience === 'roles' ? 'role(s)' : 'user(s)'}`
      setComposer(false); setForm(emptyAnnouncement); setNotice(`Announcement sent to ${audience}.`)
      await Promise.all([loadInbox(), loadSent()])
    } catch (caught) { setDialogError((caught as Error).message) } finally { setBusy(false) }
  }

  const recall = async () => {
    if (!recallTarget) return
    setBusy(true); setDialogError('')
    try {
      await api(`/notifications/announcements/${recallTarget.id}/recall`, { method: 'POST', action: 'Recall the announcement' })
      setNotice(`“${recallTarget.title}” recalled. Unread copies were withdrawn; messages already read stay in the record.`)
      notifyNotificationsChanged()
      setRecallTarget(null); await Promise.all([loadInbox(), loadSent()])
    } catch (caught) { setDialogError((caught as Error).message) } finally { setBusy(false) }
  }

  const inboxColumns = useMemo<ExportColumn<UserNotification>[]>(() => [
    { header: 'Received', value: row => new Date(row.created_at).toLocaleString() },
    { header: 'Type', value: row => row.notification_type },
    { header: 'Severity', value: row => SEVERITY_LABEL[row.severity] ?? row.severity },
    { header: 'Title', value: row => row.title },
    { header: 'Message', value: row => row.message },
    { header: 'Read', value: row => row.read_at ? 'Yes' : 'No' },
    { header: 'Link', value: row => row.action_path },
  ], [])

  const sentColumns = useMemo<ExportColumn<Announcement>[]>(() => [
    { header: 'Sent', value: row => new Date(row.created_at).toLocaleString() },
    { header: 'Title', value: row => row.title },
    { header: 'Message', value: row => row.message },
    { header: 'Audience', value: row => row.audience_label },
    { header: 'Recipients', value: row => String(row.recipient_count) },
    { header: 'Read', value: row => String(row.read_count) },
    { header: 'Sent by', value: row => row.created_by_name },
    { header: 'Recalled', value: row => row.recalled_at ? new Date(row.recalled_at).toLocaleString() : 'No' },
  ], [])

  const exportWith = (format: 'csv' | 'xlsx' | 'pdf') => {
    const stamp = new Date().toISOString().slice(0, 10)
    const onSent = tab === 'sent'
    const rows = onSent ? sent : items
    const columns = onSent ? sentColumns : inboxColumns
    const title = onSent ? 'Sent announcements' : 'Notification inbox'
    const base = onSent ? `announcements-sent-${stamp}` : `notification-inbox-${stamp}`
    if (format === 'csv') exportCsv(`${base}.csv`, rows as never[], columns as never[])
    else if (format === 'xlsx') void exportXlsx(`${base}.xlsx`, rows as never[], columns as never[])
    else void exportPdf(`${base}.pdf`, title, rows as never[], columns as never[])
  }

  const allPageSelected = items.length > 0 && items.every(item => selected.includes(item.id))

  return <>
    <PageHeading
      eyebrow="OTHER MANAGEMENTS / NOTIFICATION CENTRE"
      title="Notification centre"
      subtitle="Security, task and workspace messages for your account, plus the announcements your administrators have sent."
      action={<>
        {overview && overview.unread > 0 && <Button startIcon={<DoneAllRounded/>} onClick={() => void markAll()}>Mark all read</Button>}
        <Button onClick={event => setExportAnchor(event.currentTarget)}>Export</Button>
        <Menu anchorEl={exportAnchor} open={!!exportAnchor} onClose={() => setExportAnchor(null)}>
          <MenuItem onClick={() => { setExportAnchor(null); exportWith('csv') }}>CSV (.csv)</MenuItem>
          <MenuItem onClick={() => { setExportAnchor(null); exportWith('xlsx') }}>Excel (.xlsx)</MenuItem>
          <MenuItem onClick={() => { setExportAnchor(null); exportWith('pdf') }}>PDF (.pdf)</MenuItem>
        </Menu>
        <Button startIcon={<RefreshRounded/>} onClick={() => void Promise.all([loadInbox(), loadSent()])} disabled={loading}>Refresh</Button>
        {canManage && <Button variant="contained" startIcon={<CampaignRounded/>} onClick={() => void openComposer()}>Send announcement</Button>}
      </>}
    />

    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>

    <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }, mb: 2.5, mt: 1 }}>
      <StatCard label="Unread" value={overview?.unread} hint={overview?.oldest_unread_days ? `Oldest is ${overview.oldest_unread_days} day(s) old` : 'Nothing waiting for you'} tone={overview?.unread ? 'warning' : 'neutral'}/>
      <StatCard label="In your inbox" value={overview?.total} hint="Messages delivered to this account" tone="info"/>
      <StatCard label="Warnings and urgent" value={overview ? (overview.by_severity.warning ?? 0) + (overview.by_severity.error ?? 0) : undefined} hint="Needs attention" tone={overview && (overview.by_severity.warning || overview.by_severity.error) ? 'error' : 'neutral'}/>
      <StatCard label="Announcements" value={overview?.announcements_sent} hint="Sent across this workspace" tone="info"/>
    </Box>

    <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
      {canManage && <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ px: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Tab value="inbox" label="Inbox"/>
        <Tab value="sent" label="Sent announcements"/>
      </Tabs>}

      {tab === 'inbox' ? <>
        <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
          <Box display="flex" alignItems="center" gap={1} mb={1.4}><FilterListRounded sx={{ fontSize: 17, color: 'text.secondary' }}/><Typography fontWeight={800} fontSize={12} textTransform="uppercase" letterSpacing={0.8}>Filters</Typography></Box>
          <Box display="flex" gap={1.5} flexWrap="wrap" alignItems="center">
            <TextField size="small" label="Search title or message" value={search} onChange={event => { setSearch(event.target.value); setPage(0) }} sx={{ minWidth: 230 }}/>
            <TextField select size="small" label="Read state" value={status} onChange={event => { setStatus(event.target.value); setPage(0) }} sx={{ minWidth: 140 }}>
              <MenuItem value="">All</MenuItem>
              <MenuItem value="unread">Unread</MenuItem>
              <MenuItem value="read">Read</MenuItem>
            </TextField>
            <TextField select size="small" label="Severity" value={severity} onChange={event => { setSeverity(event.target.value); setPage(0) }} sx={{ minWidth: 140 }}>
              <MenuItem value="">All</MenuItem>
              {SEVERITIES.map(key => <MenuItem key={key} value={key}>{SEVERITY_LABEL[key]}</MenuItem>)}
            </TextField>
            <TextField select size="small" label="Type" value={type} onChange={event => { setType(event.target.value); setPage(0) }} sx={{ minWidth: 150 }}>
              <MenuItem value="">All</MenuItem>
              {types.map(key => <MenuItem key={key} value={key}>{key}</MenuItem>)}
            </TextField>
            <Typography color="text.secondary" fontSize={12} fontWeight={700} textTransform="uppercase" letterSpacing={0.8} ml={1}>Date range</Typography>
            <TextField size="small" type="date" label="From" value={dateFrom} onChange={event => { setDateFrom(event.target.value); setPage(0) }} InputLabelProps={{ shrink: true }}/>
            <Typography color="text.secondary" fontSize={12}>to</Typography>
            <TextField size="small" type="date" label="To" value={dateTo} onChange={event => { setDateTo(event.target.value); setPage(0) }} InputLabelProps={{ shrink: true }}/>
            {activeFilters && <Button size="small" color="inherit" onClick={clearFilters}>Clear</Button>}
          </Box>
        </Box>

        {selected.length > 0 && <Box sx={{ px: 2, py: 1.2, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'action.hover' }} display="flex" alignItems="center" gap={1} flexWrap="wrap">
          <Typography fontSize={12.5} fontWeight={700}>{selected.length} selected</Typography>
          <Divider orientation="vertical" flexItem/>
          <Button size="small" startIcon={<CheckRounded/>} onClick={() => void markSelectedRead()}>Mark read</Button>
          <Button size="small" color="error" startIcon={<DeleteOutlineRounded/>} onClick={() => void dismissSelected()}>Dismiss</Button>
          <Button size="small" color="inherit" sx={{ ml: 'auto' }} onClick={() => setSelected([])}>Clear selection</Button>
        </Box>}

        {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress/></Box> : items.length === 0
          ? <Box sx={{ p: 6, textAlign: 'center' }}>
            <Typography color="text.secondary" fontSize={13}>
              {activeFilters ? 'No notification matches these filters.' : 'Your inbox is empty. Security decisions and task assignments arrive here.'}
            </Typography>
            {activeFilters && <Button size="small" sx={{ mt: 1 }} onClick={clearFilters}>Clear filters</Button>}
          </Box>
          : <TableContainer><Table size="small">
            <TableHead><TableRow>
              <TableCell padding="checkbox">
                <Checkbox size="small" checked={allPageSelected} indeterminate={!allPageSelected && items.some(item => selected.includes(item.id))}
                  onChange={event => setSelected(event.target.checked ? items.map(item => item.id) : selected.filter(id => !items.some(item => item.id === id)))}
                  inputProps={{ 'aria-label': 'Select every notification on this page' }}/>
              </TableCell>
              <TableCell>Notification</TableCell><TableCell>Type</TableCell><TableCell>Received</TableCell><TableCell align="right">Actions</TableCell>
            </TableRow></TableHead>
            <TableBody>{items.map(item => <TableRow key={item.id} hover sx={{ bgcolor: item.read_at ? 'transparent' : 'action.hover' }}>
              <TableCell padding="checkbox">
                <Checkbox size="small" checked={selected.includes(item.id)}
                  onChange={event => setSelected(event.target.checked ? [...selected, item.id] : selected.filter(id => id !== item.id))}
                  inputProps={{ 'aria-label': `Select ${item.title}` }}/>
              </TableCell>
              <TableCell sx={{ maxWidth: 620 }}>
                <Box display="flex" alignItems="center" gap={.8} flexWrap="wrap">
                  <Tag tone={SEVERITY_TONE[item.severity] ?? 'neutral'}>{SEVERITY_LABEL[item.severity] ?? item.severity}</Tag>
                  <Typography fontWeight={item.read_at ? 650 : 800} fontSize={12.8}>{item.title}</Typography>
                  {!item.read_at && <Tag tone="warning">Unread</Tag>}
                </Box>
                <Typography color="text.secondary" fontSize={12} sx={{ mt: .4, lineHeight: 1.5 }}>{item.message}</Typography>
              </TableCell>
              <TableCell><Typography fontSize={11.5} color="text.secondary">{item.notification_type}</Typography></TableCell>
              <TableCell><Typography fontSize={12}>{new Date(item.created_at).toLocaleString()}</Typography></TableCell>
              <TableCell align="right"><Box display="flex" justifyContent="flex-end" gap={.25} flexWrap="wrap">
                {item.action_path && <Tooltip title={item.action_path}><Button size="small" startIcon={<OpenInNewRounded sx={{ fontSize: 15 }}/>} onClick={() => void openItem(item)}>Open</Button></Tooltip>}
                <Tooltip title={item.read_at ? 'Mark unread' : 'Mark read'}>
                  <Button size="small" startIcon={item.read_at ? <MarkEmailUnreadRounded sx={{ fontSize: 15 }}/> : <CheckRounded sx={{ fontSize: 15 }}/>} onClick={() => void toggleRead(item)}>
                    {item.read_at ? 'Unread' : 'Read'}
                  </Button>
                </Tooltip>
                <Tooltip title="Dismiss from your inbox"><Button size="small" color="error" onClick={() => void dismissOne(item)} aria-label={`Dismiss ${item.title}`}><DeleteOutlineRounded sx={{ fontSize: 16 }}/></Button></Tooltip>
              </Box></TableCell>
            </TableRow>)}</TableBody>
          </Table></TableContainer>}
        {!loading && <TablePagination component="div" count={total} page={page} rowsPerPage={pageSize} rowsPerPageOptions={PAGE_SIZES}
          onPageChange={(_, value) => setPage(value)}
          onRowsPerPageChange={event => { setPageSize(Number(event.target.value)); setPage(0) }}/>}
      </> : <>
        <Box sx={{ p: 3 }}>
          <Typography fontWeight={800} fontSize={15} mb={.5}>Announcements this workspace has sent</Typography>
          <Typography color="text.secondary" fontSize={12.5} mb={2}>
            Each row is one broadcast. “Read” counts the recipients who opened it; recalling withdraws only the unread copies, so the
            message that people already saw stays in their record.
          </Typography>
          {sent.length === 0 ? <Typography color="text.secondary" fontSize={13}>No announcement has been sent yet.</Typography>
            : <TableContainer><Table size="small">
              <TableHead><TableRow><TableCell>Announcement</TableCell><TableCell>Audience</TableCell><TableCell>Recipients</TableCell><TableCell>Read</TableCell><TableCell>Sent</TableCell><TableCell align="right">Action</TableCell></TableRow></TableHead>
              <TableBody>{sent.map(item => <TableRow key={item.id} hover>
                <TableCell sx={{ maxWidth: 420 }}>
                  <Box display="flex" alignItems="center" gap={.8} flexWrap="wrap">
                    <Tag tone={SEVERITY_TONE[item.severity] ?? 'neutral'}>{SEVERITY_LABEL[item.severity] ?? item.severity}</Tag>
                    <Typography fontWeight={750} fontSize={12.5}>{item.title}</Typography>
                    {item.recalled_at && <Tag tone="error">Recalled</Tag>}
                  </Box>
                  <Typography color="text.secondary" fontSize={11.5} sx={{ mt: .3 }}>{item.message}</Typography>
                </TableCell>
                <TableCell><Typography fontSize={12}>{item.audience_label}</Typography></TableCell>
                <TableCell>{item.recipient_count}</TableCell>
                <TableCell>{item.read_count}</TableCell>
                <TableCell>
                  <Typography fontSize={12}>{new Date(item.created_at).toLocaleString()}</Typography>
                  <Typography color="text.secondary" fontSize={11}>by {item.created_by_name}</Typography>
                </TableCell>
                <TableCell align="right">{!item.recalled_at && <Button size="small" color="error" onClick={() => { setRecallTarget(item); setDialogError('') }}>Recall</Button>}</TableCell>
              </TableRow>)}</TableBody>
            </Table></TableContainer>}
          <TablePagination component="div" count={sentTotal} page={sentPage} rowsPerPage={sentPageSize} rowsPerPageOptions={PAGE_SIZES}
            onPageChange={(_, value) => setSentPage(value)}
            onRowsPerPageChange={event => { setSentPageSize(Number(event.target.value)); setSentPage(0) }}/>
        </Box>
      </>}
    </Paper>

    <FormDialog open={composer} title="Send an announcement" maxWidth="sm"
      subtitle="Delivered to each recipient's inbox and to their notification bell. The delivery is audited."
      onClose={() => setComposer(false)} onSubmit={() => void sendAnnouncement()} busy={busy}
      submitLabel="Send announcement"
      submitDisabled={form.title.trim().length < 3 || form.message.trim().length < 3 || (form.audience !== 'all' && (form.audience === 'roles' ? chosenRoles.length === 0 : chosenUsers.length === 0))}>
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Title" required value={form.title} onChange={event => setForm(value => ({ ...value, title: event.target.value }))} inputProps={{ maxLength: 160 }}/>
        <TextField label="Message" required multiline minRows={3} value={form.message} onChange={event => setForm(value => ({ ...value, message: event.target.value }))} inputProps={{ maxLength: 1000 }}/>
        <TextField select label="Severity" value={form.severity} onChange={event => setForm(value => ({ ...value, severity: event.target.value }))}>
          {SEVERITIES.map(key => <MenuItem key={key} value={key}>{SEVERITY_LABEL[key]}</MenuItem>)}
        </TextField>
        <TextField select label="Audience" value={form.audience} onChange={event => setForm(value => ({ ...value, audience: event.target.value as typeof value.audience }))}
          helperText={form.audience !== 'all' && !can('users:read') && form.audience === 'users' ? 'Listing accounts needs users:read. Choose roles or all users instead.' : 'Everyone addressed must be an active account in this workspace.'}>
          <MenuItem value="all">Every active user</MenuItem>
          <MenuItem value="roles" disabled={!can('roles:read')}>Selected roles</MenuItem>
          <MenuItem value="users" disabled={!can('users:read')}>Selected people</MenuItem>
        </TextField>
        {form.audience === 'roles' && <Autocomplete multiple options={roleChoices} getOptionLabel={option => option.name} value={chosenRoles}
          onChange={(_, value) => setChosenRoles(value)} renderInput={params => <TextField {...params} label="Roles"/>}/>}
        {form.audience === 'users' && <Autocomplete multiple options={userChoices} getOptionLabel={option => `${option.full_name} · ${option.email}`}
          value={chosenUsers} onChange={(_, value) => setChosenUsers(value)} renderInput={params => <TextField {...params} label="People"/>}/>}
        <TextField label="Application path (optional)" placeholder="/daily-cost" value={form.action_path}
          onChange={event => setForm(value => ({ ...value, action_path: event.target.value }))}
          helperText="Where “Open” takes the recipient, for example /other-management/tasks."/>
        <ErrorMessage message={dialogError}/>
      </Box>
    </FormDialog>

    <FormDialog open={!!recallTarget} title="Recall this announcement?" danger maxWidth="sm"
      subtitle={`“${recallTarget?.title ?? ''}” will be withdrawn from the inboxes that have not opened it yet.`}
      onClose={() => setRecallTarget(null)} onSubmit={() => void recall()} busy={busy} submitLabel="Recall announcement">
      <Box display="grid" gap={2} pt={.5}>
        <Alert severity="warning">Messages already read stay in the recipient's record, and the recall itself is audited.</Alert>
        <ErrorMessage message={dialogError}/>
      </Box>
    </FormDialog>
  </>
}

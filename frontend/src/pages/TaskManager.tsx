import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, CircularProgress, Divider, Menu, MenuItem, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TablePagination, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import {
  AddRounded, AssignmentTurnedInRounded, CancelRounded, FilterListRounded, OpenInNewRounded, RefreshRounded,
  RestartAltRounded, VisibilityOutlined,
} from '@mui/icons-material'
import { useNavigate } from 'react-router-dom'
import { ErrorMessage, FormDialog, PageHeading, PanelDialog, Tag, type Tone } from '../components/Common'
import { api, body } from '../lib/api'
import { exportCsv, exportPdf, exportXlsx, type ExportColumn } from '../lib/export'
import type { TaskEvent, TaskOverview, TaskPage, TaskPriority, TaskStatus, WorkflowTask } from '../lib/workflowTypes'
import type { User } from '../lib/types'
import { useAuth } from '../context/AuthContext'

const PAGE_SIZES = [20, 50, 100]
const PRIORITY_TONE: Record<TaskPriority, Tone> = { low: 'neutral', normal: 'info', high: 'warning', critical: 'error' }
const STATUS_TONE: Record<TaskStatus, Tone> = { open: 'warning', in_progress: 'info', completed: 'success', cancelled: 'neutral' }
const STATUS_LABEL: Record<TaskStatus, string> = { open: 'Open', in_progress: 'In progress', completed: 'Completed', cancelled: 'Cancelled' }
const emptyTask = { title: '', description: '', priority: 'normal' as TaskPriority, assignee_user_id: '', due_at: '', action_path: '' }

function StatCard({ label, value, hint, tone = 'info' }: { label: string; value: number | undefined; hint: string; tone?: Tone }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
    <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
    <Typography className="stat-value" sx={{ fontSize: 26, my: .8 }}>{value === undefined ? '…' : value}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
    <Box sx={{ mt: 1, height: 3, borderRadius: 2, bgcolor: `var(--wcp-tone-${tone}-border)` }}/>
  </Paper>
}

function dueLabel(value: string | null): { text: string; tone: Tone } {
  if (!value) return { text: 'No due date', tone: 'neutral' }
  const due = new Date(value)
  const diff = Math.ceil((due.getTime() - Date.now()) / 86400000)
  const text = due.toLocaleDateString()
  if (diff < 0) return { text: `Overdue · ${text}`, tone: 'error' }
  if (diff === 0) return { text: `Due today · ${due.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`, tone: 'warning' }
  return { text, tone: diff <= 2 ? 'warning' : 'neutral' }
}

export default function TaskManager() {
  const navigate = useNavigate()
  const { can, user } = useAuth()
  const canManage = user?.is_owner || can('tasks:manage')
  const [rows, setRows] = useState<WorkflowTask[]>([])
  const [total, setTotal] = useState(0)
  const [overview, setOverview] = useState<TaskOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // Filters
  const [status, setStatus] = useState('active')
  const [priority, setPriority] = useState('')
  const [type, setType] = useState('')
  const [assignee, setAssignee] = useState('')
  const [due, setDue] = useState('')
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(20)
  const [types, setTypes] = useState<string[]>([])
  const [people, setPeople] = useState<User[]>([])

  // Selection and dialogs
  const [selected, setSelected] = useState<string[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState(emptyTask)
  const [busy, setBusy] = useState(false)
  const [dialogError, setDialogError] = useState('')
  const [detail, setDetail] = useState<WorkflowTask | null>(null)
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [comment, setComment] = useState('')
  const [detailBusy, setDetailBusy] = useState(false)
  const [cancelTarget, setCancelTarget] = useState<WorkflowTask | null>(null)
  const [assignTarget, setAssignTarget] = useState<{ ids: string[]; one?: WorkflowTask } | null>(null)
  const [assignTo, setAssignTo] = useState('')
  const [exportAnchor, setExportAnchor] = useState<HTMLElement | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    const params = new URLSearchParams({ page: String(page + 1), page_size: String(pageSize) })
    if (status) params.set('status', status)
    if (priority) params.set('priority', priority)
    if (type) params.set('type', type)
    if (assignee) params.set('assignee', assignee)
    if (due) params.set('due', due)
    if (search.trim()) params.set('search', search.trim())
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    try {
      // The queue is the page's authoritative data. The overview was added
      // later and must not make the whole Task Manager fail while API nodes
      // are rolling from an older release.
      const data = await api<TaskPage>(`/tasks?${params.toString()}`, { action: 'Load the task queue' })
      setRows(data.items); setTotal(data.total)
      setSelected(ids => ids.filter(id => data.items.some(row => row.id === id)))
      setTypes(current => Array.from(new Set([...current, ...data.items.map(row => row.task_type)])))
      try {
        const summary = await api<TaskOverview>('/tasks/overview', { action: 'Load the task summary', silent: true })
        setOverview(summary)
        setTypes(current => Array.from(new Set([...current, ...Object.keys(summary.by_type)])))
      } catch {
        const active = data.items.filter(row => row.status === 'open' || row.status === 'in_progress')
        setOverview({
          open: data.items.filter(row => row.status === 'open').length,
          in_progress: data.items.filter(row => row.status === 'in_progress').length,
          overdue: active.filter(row => row.overdue).length,
          due_today: active.filter(row => row.due_at && new Date(row.due_at).toDateString() === new Date().toDateString()).length,
          completed_7d: data.items.filter(row => row.status === 'completed' && row.completed_at && Date.now() - new Date(row.completed_at).getTime() <= 7 * 86400000).length,
          mine: active.filter(row => row.is_mine).length,
          unassigned: active.filter(row => !row.assignee_user_id).length,
          by_priority: {}, by_type: {},
        })
      }
    } catch (caught) { setError((caught as Error).message) } finally { setLoading(false) }
  }, [page, pageSize, status, priority, type, assignee, due, search, dateFrom, dateTo])
  useEffect(() => { void load() }, [load])

  useEffect(() => {
    if (!can('users:read')) return
    api<User[]>('/users', { action: 'Load workspace accounts', silent: true }).then(setPeople).catch(() => setPeople([]))
  }, [can])

  const clearFilters = () => {
    setStatus(''); setPriority(''); setType(''); setAssignee(''); setDue(''); setSearch(''); setDateFrom(''); setDateTo(''); setPage(0)
  }
  const activeFilters = !!(priority || type || assignee || due || search || dateFrom || dateTo || status !== 'active')

  const update = async (row: WorkflowTask, payload: Record<string, unknown>, action: string) => {
    try {
      await api(`/tasks/${row.id}`, { method: 'PATCH', body: body(payload), action })
      setNotice(`${action} · ${row.task_number}`)
      await load()
      if (detail?.id === row.id) await openDetail(row.id)
    } catch { /* the global pop-up already explains the failure */ }
  }

  const openDetail = async (taskId: string) => {
    setDetailBusy(true); setDialogError('')
    try {
      const [task, history] = await Promise.all([
        api<WorkflowTask>(`/tasks/${taskId}`, { action: 'Load the task' }),
        api<TaskEvent[]>(`/tasks/${taskId}/events`, { action: 'Load the task history' }),
      ])
      setDetail(task)
      setEvents(history)
    } catch (caught) { setDialogError((caught as Error).message) } finally { setDetailBusy(false) }
  }

  const addComment = async () => {
    if (!detail || !comment.trim()) return
    setDetailBusy(true); setDialogError('')
    try {
      await api(`/tasks/${detail.id}/comments`, { method: 'POST', body: body({ notes: comment.trim() }), action: 'Add the comment' })
      setComment('')
      setEvents(await api<TaskEvent[]>(`/tasks/${detail.id}/events`, { action: 'Load the task history' }))
      await load()
    } catch (caught) { setDialogError((caught as Error).message) } finally { setDetailBusy(false) }
  }

  const createTask = async () => {
    setBusy(true); setDialogError('')
    try {
      await api('/tasks', {
        method: 'POST', action: 'Create the task',
        body: body({
          title: form.title.trim(),
          description: form.description.trim(),
          priority: form.priority,
          assignee_user_id: form.assignee_user_id || null,
          due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
          action_path: form.action_path.trim(),
        }),
      })
      setCreateOpen(false); setForm(emptyTask); setNotice('Task created.')
      await load()
    } catch (caught) { setDialogError((caught as Error).message) } finally { setBusy(false) }
  }

  const runBulk = async (action: 'claim' | 'complete' | 'reopen' | 'cancel', ids: string[]) => {
    if (!ids.length) return
    setBusy(true); setDialogError('')
    try {
      const result = await api<{ affected: number; skipped: number }>('/tasks/bulk', {
        method: 'POST', body: body({ task_ids: ids, action, notes: `Bulk ${action} from the task manager` }), action: `Bulk ${action}`,
      })
      setNotice(`${result.affected} task(s) updated${result.skipped ? `, ${result.skipped} skipped` : ''}.`)
      setSelected([]); setCancelTarget(null); await load()
    } catch (caught) { setDialogError((caught as Error).message) } finally { setBusy(false) }
  }

  const assign = async () => {
    if (!assignTarget || !assignTo) return
    setBusy(true); setDialogError('')
    try {
      if (assignTarget.one) {
        await api(`/tasks/${assignTarget.one.id}`, { method: 'PATCH', body: body({ assignee_user_id: assignTo }), action: 'Assign the task' })
        setNotice(`${assignTarget.one.task_number} reassigned.`)
      } else {
        const result = await api<{ affected: number; skipped: number }>('/tasks/bulk', {
          method: 'POST', body: body({ task_ids: assignTarget.ids, action: 'assign', assignee_user_id: assignTo }), action: 'Assign the tasks',
        })
        setNotice(`${result.affected} task(s) reassigned${result.skipped ? `, ${result.skipped} skipped` : ''}.`)
        setSelected([])
      }
      setAssignTarget(null); setAssignTo(''); await load()
    } catch (caught) { setDialogError((caught as Error).message) } finally { setBusy(false) }
  }

  const columns = useMemo<ExportColumn<WorkflowTask>[]>(() => [
    { header: 'Task', value: row => row.task_number },
    { header: 'Title', value: row => row.title },
    { header: 'Description', value: row => row.description },
    { header: 'Type', value: row => row.task_type.replaceAll('_', ' ') },
    { header: 'Priority', value: row => row.priority },
    { header: 'Status', value: row => row.status },
    { header: 'Assignee', value: row => row.assignee_name },
    { header: 'Raised by', value: row => row.created_by_name },
    { header: 'Due', value: row => row.due_at ? new Date(row.due_at).toLocaleString() : '' },
    { header: 'Overdue', value: row => row.overdue ? 'Yes' : 'No' },
    { header: 'Created', value: row => new Date(row.created_at).toLocaleString() },
    { header: 'Related record', value: row => row.related_entity_label || row.related_entity_type },
  ], [])

  const exportWith = (format: 'csv' | 'xlsx' | 'pdf') => {
    const stamp = new Date().toISOString().slice(0, 10)
    if (format === 'csv') exportCsv(`task-queue-${stamp}.csv`, rows, columns)
    else if (format === 'xlsx') void exportXlsx(`task-queue-${stamp}.xlsx`, rows, columns)
    else void exportPdf(`task-queue-${stamp}.pdf`, 'Task queue', rows, columns)
  }

  const allPageSelected = rows.length > 0 && rows.every(row => selected.includes(row.id))
  const canAct = (row: WorkflowTask) => row.can_manage

  return <>
    <PageHeading
      eyebrow="OTHER MANAGEMENTS / TASK MANAGER"
      title="Task manager"
      subtitle="One queue for manual work and for the approvals the costing modules raise automatically. Claim, complete and hand over work here without leaving the page."
      action={<>
        <Button onClick={event => setExportAnchor(event.currentTarget)}>Export</Button>
        <Menu anchorEl={exportAnchor} open={!!exportAnchor} onClose={() => setExportAnchor(null)}>
          <MenuItem onClick={() => { setExportAnchor(null); exportWith('csv') }}>CSV (.csv)</MenuItem>
          <MenuItem onClick={() => { setExportAnchor(null); exportWith('xlsx') }}>Excel (.xlsx)</MenuItem>
          <MenuItem onClick={() => { setExportAnchor(null); exportWith('pdf') }}>PDF (.pdf)</MenuItem>
        </Menu>
        <Button startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</Button>
        {can('tasks:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={() => { setCreateOpen(true); setForm(emptyTask); setDialogError('') }}>Add task</Button>}
      </>}
    />

    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>

    <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(5, minmax(0, 1fr))' }, mb: 2.5, mt: 1 }}>
      <StatCard label="Open" value={overview?.open} hint="Not started yet" tone="warning"/>
      <StatCard label="In progress" value={overview?.in_progress} hint="Claimed by somebody" tone="info"/>
      <StatCard label="Overdue" value={overview?.overdue} hint="Past the due date" tone={overview?.overdue ? 'error' : 'neutral'}/>
      <StatCard label="Due today" value={overview?.due_today} hint="Needs attention now" tone={overview?.due_today ? 'warning' : 'neutral'}/>
      <StatCard label="My open work" value={overview?.mine} hint={`${overview?.completed_7d ?? 0} completed in 7 days`} tone="info"/>
    </Box>

    <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
      <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Box display="flex" alignItems="center" gap={1} mb={1.4}><FilterListRounded sx={{ fontSize: 17, color: 'text.secondary' }}/><Typography fontWeight={800} fontSize={12} textTransform="uppercase" letterSpacing={0.8}>Filters</Typography></Box>
        <Box display="flex" gap={1.5} flexWrap="wrap" alignItems="center">
          <TextField size="small" label="Search task, number or record" value={search} onChange={event => { setSearch(event.target.value); setPage(0) }} sx={{ minWidth: 240 }}/>
          <TextField select size="small" label="Status" value={status} onChange={event => { setStatus(event.target.value); setPage(0) }} sx={{ minWidth: 150 }}>
            <MenuItem value="active">Active (open + in progress)</MenuItem>
            <MenuItem value="">All statuses</MenuItem>
            <MenuItem value="open">Open</MenuItem>
            <MenuItem value="in_progress">In progress</MenuItem>
            <MenuItem value="completed">Completed</MenuItem>
            <MenuItem value="cancelled">Cancelled</MenuItem>
          </TextField>
          <TextField select size="small" label="Priority" value={priority} onChange={event => { setPriority(event.target.value); setPage(0) }} sx={{ minWidth: 130 }}>
            <MenuItem value="">All</MenuItem>
            {(['critical', 'high', 'normal', 'low'] as TaskPriority[]).map(key => <MenuItem key={key} value={key}>{key}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Type" value={type} onChange={event => { setType(event.target.value); setPage(0) }} sx={{ minWidth: 150 }}>
            <MenuItem value="">All types</MenuItem>
            {types.map(key => <MenuItem key={key} value={key}>{key.replaceAll('_', ' ')}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Assignee" value={assignee} onChange={event => { setAssignee(event.target.value); setPage(0) }} sx={{ minWidth: 170 }}>
            <MenuItem value="">Anyone</MenuItem>
            <MenuItem value="me">Assigned to me</MenuItem>
            <MenuItem value="unassigned">Unassigned</MenuItem>
            {people.map(person => <MenuItem key={person.id} value={person.id}>{person.full_name}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Due" value={due} onChange={event => { setDue(event.target.value); setPage(0) }} sx={{ minWidth: 140 }}>
            <MenuItem value="">Any date</MenuItem>
            <MenuItem value="overdue">Overdue</MenuItem>
            <MenuItem value="today">Due today</MenuItem>
            <MenuItem value="week">Next 7 days</MenuItem>
            <MenuItem value="none">No due date</MenuItem>
          </TextField>
          <Typography color="text.secondary" fontSize={12} fontWeight={700} textTransform="uppercase" letterSpacing={0.8} ml={1}>Created</Typography>
          <TextField size="small" type="date" label="From" value={dateFrom} onChange={event => { setDateFrom(event.target.value); setPage(0) }} InputLabelProps={{ shrink: true }}/>
          <Typography color="text.secondary" fontSize={12}>to</Typography>
          <TextField size="small" type="date" label="To" value={dateTo} onChange={event => { setDateTo(event.target.value); setPage(0) }} InputLabelProps={{ shrink: true }}/>
          {activeFilters && <Button size="small" color="inherit" onClick={clearFilters}>Clear</Button>}
        </Box>
      </Box>

      {selected.length > 0 && <Box sx={{ px: 2, py: 1.2, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'action.hover' }} display="flex" alignItems="center" gap={1} flexWrap="wrap">
        <Typography fontSize={12.5} fontWeight={700}>{selected.length} selected</Typography>
        <Divider orientation="vertical" flexItem/>
        <Button size="small" onClick={() => void runBulk('claim', selected)}>Claim</Button>
        <Button size="small" startIcon={<AssignmentTurnedInRounded sx={{ fontSize: 15 }}/>} onClick={() => void runBulk('complete', selected)}>Complete</Button>
        <Button size="small" startIcon={<RestartAltRounded sx={{ fontSize: 15 }}/>} onClick={() => void runBulk('reopen', selected)}>Reopen</Button>
        {canManage && <Button size="small" onClick={() => { setAssignTarget({ ids: selected }); setAssignTo(''); setDialogError('') }}>Reassign</Button>}
        <Button size="small" color="error" startIcon={<CancelRounded sx={{ fontSize: 15 }}/>} onClick={() => { const first = rows.find(row => selected.includes(row.id)); if (first) { setCancelTarget(first); setDialogError('') } }}>Cancel</Button>
        <Button size="small" color="inherit" sx={{ ml: 'auto' }} onClick={() => setSelected([])}>Clear selection</Button>
      </Box>}

      {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress/></Box>
        : <TableContainer><Table size="small">
          <TableHead><TableRow>
            <TableCell padding="checkbox">
              <Checkbox size="small" checked={allPageSelected} indeterminate={!allPageSelected && rows.some(row => selected.includes(row.id))}
                onChange={event => setSelected(event.target.checked ? rows.map(row => row.id) : selected.filter(id => !rows.some(row => row.id === id)))}
                inputProps={{ 'aria-label': 'Select every task on this page' }}/>
            </TableCell>
            <TableCell>Task</TableCell><TableCell>Type</TableCell><TableCell>Priority</TableCell>
            <TableCell>Assignee</TableCell><TableCell>Due</TableCell><TableCell>Status</TableCell><TableCell align="right">Actions</TableCell>
          </TableRow></TableHead>
          <TableBody>
            {rows.length === 0 ? <TableRow><TableCell colSpan={8} align="center" sx={{ py: 6, color: 'text.secondary' }}>
              {activeFilters ? 'No task matches these filters.' : 'Nothing is waiting for you. New approvals and manual tasks appear here.'}
            </TableCell></TableRow> : rows.map(row => {
              const dueInfo = dueLabel(row.due_at)
              return <TableRow key={row.id} hover>
                <TableCell padding="checkbox">
                  <Checkbox size="small" checked={selected.includes(row.id)}
                    onChange={event => setSelected(event.target.checked ? [...selected, row.id] : selected.filter(id => id !== row.id))}
                    inputProps={{ 'aria-label': `Select ${row.title}` }}/>
                </TableCell>
                <TableCell sx={{ maxWidth: 380 }}>
                  <Typography fontWeight={750} fontSize={12.5}>{row.title}</Typography>
                  <Typography color="text.secondary" fontSize={11}>{row.task_number} · raised by {row.created_by_name}
                    {row.related_entity_label ? ` · ${row.related_entity_label}` : ''}</Typography>
                  {row.description && <Typography color="text.secondary" fontSize={11.5} sx={{ mt: .3, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{row.description}</Typography>}
                </TableCell>
                <TableCell><Typography fontSize={11.5}>{row.task_type.replaceAll('_', ' ')}</Typography></TableCell>
                <TableCell><Tag tone={PRIORITY_TONE[row.priority]}>{row.priority}</Tag></TableCell>
                <TableCell>
                  <Typography fontSize={12}>{row.assignee_name}</Typography>
                  {row.is_mine && <Typography color="text.secondary" fontSize={10.5}>You</Typography>}
                </TableCell>
                <TableCell><Tag tone={dueInfo.tone}>{dueInfo.text}</Tag></TableCell>
                <TableCell><Tag tone={STATUS_TONE[row.status]}>{STATUS_LABEL[row.status]}</Tag></TableCell>
                <TableCell align="right">
                  <Box display="flex" justifyContent="flex-end" gap={.25} flexWrap="wrap">
                    <Tooltip title="Open the full task, history and comments"><Button size="small" startIcon={<VisibilityOutlined sx={{ fontSize: 15 }}/>} onClick={() => void openDetail(row.id)}>Details</Button></Tooltip>
                    {row.action_path && <Tooltip title={row.action_path}><Button size="small" startIcon={<OpenInNewRounded sx={{ fontSize: 15 }}/>} onClick={() => navigate(row.action_path)}>Open</Button></Tooltip>}
                    {canAct(row) && row.status === 'open' && <Button size="small" onClick={() => void update(row, { status: 'in_progress' }, 'Claim the task')}>Claim</Button>}
                    {canAct(row) && row.status === 'in_progress' && <Button size="small" variant="contained" onClick={() => void update(row, { status: 'completed' }, 'Complete the task')}>Complete</Button>}
                    {canAct(row) && (row.status === 'completed' || row.status === 'cancelled') && <Button size="small" startIcon={<RestartAltRounded sx={{ fontSize: 15 }}/>} onClick={() => void update(row, { status: 'open' }, 'Reopen the task')}>Reopen</Button>}
                    {canManage && <Button size="small" onClick={() => { setAssignTarget({ ids: [row.id], one: row }); setAssignTo(row.assignee_user_id ?? ''); setDialogError('') }}>Assign</Button>}
                  </Box>
                </TableCell>
              </TableRow>
            })}
          </TableBody>
        </Table></TableContainer>}
      {!loading && <TablePagination component="div" count={total} page={page} rowsPerPage={pageSize} rowsPerPageOptions={PAGE_SIZES}
        onPageChange={(_, value) => setPage(value)}
        onRowsPerPageChange={event => { setPageSize(Number(event.target.value)); setPage(0) }}/>}
    </Paper>

    {/* Create a manual task */}
    <FormDialog open={createOpen} title="Add a task" maxWidth="sm" subtitle="A manual work item for yourself or a colleague. Approval tasks are raised automatically by their module."
      onClose={() => setCreateOpen(false)} onSubmit={() => void createTask()} busy={busy} submitLabel="Create task" submitDisabled={form.title.trim().length < 3}>
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Title" required value={form.title} onChange={event => setForm(value => ({ ...value, title: event.target.value }))} inputProps={{ maxLength: 200 }}/>
        <TextField label="Description" multiline minRows={3} value={form.description} onChange={event => setForm(value => ({ ...value, description: event.target.value }))} inputProps={{ maxLength: 2000 }}/>
        <TextField select label="Priority" value={form.priority} onChange={event => setForm(value => ({ ...value, priority: event.target.value as TaskPriority }))}>
          {(['low', 'normal', 'high', 'critical'] as TaskPriority[]).map(key => <MenuItem key={key} value={key}>{key}</MenuItem>)}
        </TextField>
        <TextField select label="Assignee" value={form.assignee_user_id} onChange={event => setForm(value => ({ ...value, assignee_user_id: event.target.value }))}
          helperText={can('users:read') ? 'Leave unassigned to keep it in the shared queue.' : 'Listing accounts needs users:read, so this task stays unassigned.'}>
          <MenuItem value="">Unassigned</MenuItem>
          {people.map(person => <MenuItem key={person.id} value={person.id}>{person.full_name} · {person.email}</MenuItem>)}
        </TextField>
        <TextField label="Due date and time" type="datetime-local" InputLabelProps={{ shrink: true }} value={form.due_at}
          onChange={event => setForm(value => ({ ...value, due_at: event.target.value }))}/>
        <TextField label="Application path (optional)" placeholder="/afe/register" value={form.action_path}
          onChange={event => setForm(value => ({ ...value, action_path: event.target.value }))}
          helperText="The page the “Open” button takes the assignee to."/>
        <ErrorMessage message={dialogError}/>
      </Box>
    </FormDialog>

    {/* Task detail with history and comments */}
    <PanelDialog open={!!detail} title={detail?.title ?? 'Task'} maxWidth="md"
      subtitle={detail ? `${detail.task_number} · ${detail.task_type.replaceAll('_', ' ')} · raised by ${detail.created_by_name}` : ''}
      onClose={() => { setDetail(null); setEvents([]); setComment(''); setDialogError('') }}
      footer={<>
        <Button onClick={() => { setDetail(null); setEvents([]); setComment(''); setDialogError('') }}>Close</Button>
        {detail?.action_path && <Button onClick={() => navigate(detail.action_path)}>Open record</Button>}
        {detail && canAct(detail) && detail.status === 'completed' && <Button variant="contained" onClick={() => void update(detail, { status: 'open' }, 'Reopen the task')}>Reopen</Button>}
        {detail && canAct(detail) && detail.status !== 'completed' && <Button variant="contained" onClick={() => void update(detail, { status: 'completed' }, 'Complete the task')}>Complete</Button>}
      </>}>
      {detail && <Box display="grid" gap={2.5}>
        <Box display="flex" gap={.8} flexWrap="wrap">
          <Tag tone={STATUS_TONE[detail.status]}>{STATUS_LABEL[detail.status]}</Tag>
          <Tag tone={PRIORITY_TONE[detail.priority]}>{detail.priority}</Tag>
          <Tag tone={dueLabel(detail.due_at).tone}>{dueLabel(detail.due_at).text}</Tag>
          <Tag>{detail.assignee_name}</Tag>
        </Box>
        {detail.description && <Typography fontSize={13} sx={{ lineHeight: 1.6 }}>{detail.description}</Typography>}
        <Box display="grid" gap={.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' } }}>
          <Typography fontSize={12} color="text.secondary">Created: <strong>{new Date(detail.created_at).toLocaleString()}</strong></Typography>
          <Typography fontSize={12} color="text.secondary">Updated: <strong>{new Date(detail.updated_at).toLocaleString()}</strong></Typography>
          <Typography fontSize={12} color="text.secondary">Related record: <strong>{detail.related_entity_label || '—'}</strong></Typography>
          <Typography fontSize={12} color="text.secondary">Required capability: <strong>{detail.required_permission || 'None'}</strong></Typography>
        </Box>
        <Divider/>
        <Box>
          <Typography fontWeight={800} fontSize={13} mb={1}>History</Typography>
          {detailBusy && events.length === 0 ? <CircularProgress size={18}/> : <Box display="grid" gap={1}>
            {events.length === 0 && <Typography color="text.secondary" fontSize={12.5}>No history recorded yet.</Typography>}
            {events.map(event => <Box key={event.id} sx={{ borderLeft: '2px solid', borderColor: event.event_type === 'comment' ? 'primary.main' : 'divider', pl: 1.5, py: .3 }}>
              <Typography fontSize={12.5} fontWeight={event.event_type === 'comment' ? 650 : 600}>
                {event.event_type === 'comment' ? 'Comment' : event.event_type.replaceAll('_', ' ')}
                {event.new_status && event.old_status && event.old_status !== event.new_status ? ` · ${event.old_status} → ${event.new_status}` : ''}
              </Typography>
              {event.notes && <Typography fontSize={12} color="text.secondary" sx={{ lineHeight: 1.5 }}>{event.notes}</Typography>}
              <Typography fontSize={11} color="text.secondary">{event.actor_name} · {new Date(event.created_at).toLocaleString()}</Typography>
            </Box>)}
          </Box>}
        </Box>
        {detail.can_manage
          ? <Box display="flex" gap={1} alignItems="flex-start">
            <TextField fullWidth size="small" label="Add a comment" value={comment} onChange={event => setComment(event.target.value)} inputProps={{ maxLength: 1000 }}/>
            <Button variant="contained" disabled={!comment.trim() || detailBusy} onClick={() => void addComment()}>Post</Button>
          </Box>
          : <Typography color="text.secondary" fontSize={12}>
            Only the assignee, the person who raised this task or a task manager can add a comment, so the box is hidden here.
          </Typography>}
        <ErrorMessage message={dialogError}/>
      </Box>}
    </PanelDialog>

    {/* Reassign */}
    <FormDialog open={!!assignTarget} title="Assign this work" maxWidth="sm"
      subtitle={assignTarget?.one ? `${assignTarget.one.task_number} · ${assignTarget.one.title}` : `${assignTarget?.ids.length ?? 0} selected task(s) will move to one person.`}
      onClose={() => { setAssignTarget(null); setAssignTo(''); setDialogError('') }} onSubmit={() => void assign()} busy={busy} submitLabel="Assign"
      submitDisabled={!assignTo}>
      <Box display="grid" gap={2} pt={.5}>
        <TextField select label="Assignee" value={assignTo} onChange={event => setAssignTo(event.target.value)}
          helperText={!can('users:read') ? 'Listing accounts needs users:read. Your own account is always available.' : 'Only active accounts can hold work.'}>
          {user && <MenuItem value={user.id}>Me · {user.email}</MenuItem>}
          {people.filter(person => person.id !== user?.id).map(person => <MenuItem key={person.id} value={person.id}>{person.full_name} · {person.email}</MenuItem>)}
        </TextField>
        <ErrorMessage message={dialogError}/>
      </Box>
    </FormDialog>

    {/* Cancel confirmation */}
    <FormDialog open={!!cancelTarget} title="Cancel this work?" danger maxWidth="sm"
      subtitle="The task closes as cancelled and stays in the record for the audit trail."
      onClose={() => setCancelTarget(null)} onSubmit={() => void runBulk('cancel', selected.length ? selected : cancelTarget ? [cancelTarget.id] : [])}
      busy={busy} submitLabel="Cancel task">
      <Box display="grid" gap={2} pt={.5}>
        <Typography fontSize={12.5}>{cancelTarget?.task_number} · {cancelTarget?.title}</Typography>
        <Alert severity="warning">Cancelling does not delete the record and does not change the underlying costing document.</Alert>
        <ErrorMessage message={dialogError}/>
      </Box>
    </FormDialog>
  </>
}

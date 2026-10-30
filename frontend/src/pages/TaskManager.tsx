import { useEffect, useState } from 'react'
import { Alert, Box, Button, Chip, CircularProgress, MenuItem, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@mui/material'
import { AddRounded, OpenInNewRounded } from '@mui/icons-material'
import { useNavigate } from 'react-router-dom'
import { FormDialog, PageHeading } from '../components/Common'
import { api, body } from '../lib/api'
import type { WorkflowTask } from '../lib/workflowTypes'
import { useAuth } from '../context/AuthContext'

const empty = { title: '', description: '', priority: 'normal', due_at: '', action_path: '' }
export default function TaskManager() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const [rows, setRows] = useState<WorkflowTask[]>([])
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState('')
  const [dialog, setDialog] = useState(false)
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load = () => { setLoading(true); api<{ items: WorkflowTask[] }>(`/tasks?page_size=100${status ? `&status=${status}` : ''}`).then(data => setRows(data.items)).finally(() => setLoading(false)) }
  useEffect(load, [status]) // eslint-disable-line react-hooks/exhaustive-deps
  const create = async () => { setBusy(true); setError(''); try { await api('/tasks', { method: 'POST', body: body({ ...form, due_at: form.due_at || null }) }); setDialog(false); setForm(empty); load() } catch (err) { setError((err as Error).message) } finally { setBusy(false) } }
  const update = async (row: WorkflowTask, next: WorkflowTask['status']) => { await api(`/tasks/${row.id}`, { method: 'PATCH', body: body({ status: next, notes: next === 'in_progress' ? 'Claimed from task manager' : 'Updated from task manager' }) }); load() }
  return <>
    <PageHeading eyebrow="Other Managements" title="Task manager" subtitle="A single work queue for manual tasks and existing approval flows. AFE review and approval tasks appear automatically without changing the AFE workflow." action={can('tasks:create') ? <Button variant="contained" startIcon={<AddRounded/>} onClick={() => { setDialog(true); setError('') }}>Add task</Button> : undefined}/>
    <Box display="flex" mb={2}><TextField select size="small" label="Status" value={status} onChange={event => setStatus(event.target.value)} sx={{ minWidth: 180 }}><MenuItem value="">All tasks</MenuItem><MenuItem value="open">Open</MenuItem><MenuItem value="in_progress">In progress</MenuItem><MenuItem value="completed">Completed</MenuItem><MenuItem value="cancelled">Cancelled</MenuItem></TextField></Box>
    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress/></Box> : <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Task</TableCell><TableCell>Type</TableCell><TableCell>Priority</TableCell><TableCell>Assignee</TableCell><TableCell>Due</TableCell><TableCell>Status</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead><TableBody>
      {rows.length === 0 ? <TableRow><TableCell colSpan={7} align="center" sx={{ py: 6, color: 'text.secondary' }}>No tasks match this view.</TableCell></TableRow> : rows.map(row => <TableRow key={row.id} hover><TableCell sx={{ maxWidth: 360 }}><Typography fontWeight={750} fontSize={12.5}>{row.title}</Typography><Typography fontSize={11} color="text.secondary">{row.task_number} · {row.description}</Typography></TableCell><TableCell>{row.task_type.replaceAll('_', ' ')}</TableCell><TableCell><Chip size="small" label={row.priority} color={row.priority === 'critical' ? 'error' : row.priority === 'high' ? 'warning' : 'default'}/></TableCell><TableCell>{row.assignee_name}</TableCell><TableCell>{row.due_at ? new Date(row.due_at).toLocaleDateString() : '—'}</TableCell><TableCell><Chip size="small" label={row.status.replaceAll('_', ' ')} color={row.status === 'completed' ? 'success' : row.status === 'in_progress' ? 'info' : 'default'}/></TableCell><TableCell align="right"><Box display="flex" justifyContent="flex-end" gap={.5}>{row.action_path && <Button size="small" startIcon={<OpenInNewRounded/>} onClick={() => navigate(row.action_path)}>Open</Button>}{row.status === 'open' && <Button size="small" onClick={() => void update(row, 'in_progress')}>Claim</Button>}{row.status === 'in_progress' && <Button size="small" variant="contained" onClick={() => void update(row, 'completed')}>Complete</Button>}</Box></TableCell></TableRow>)}
    </TableBody></Table></TableContainer>}
    <FormDialog open={dialog} title="Add a task" subtitle="Create a work item for yourself or your team." onClose={() => setDialog(false)} onSubmit={() => void create()} busy={busy} submitLabel="Create task" submitDisabled={!form.title.trim()}>
      <Box display="grid" gap={2}><TextField label="Title" required value={form.title} onChange={event => setForm(value => ({ ...value, title: event.target.value }))}/><TextField label="Description" multiline minRows={3} value={form.description} onChange={event => setForm(value => ({ ...value, description: event.target.value }))}/><TextField select label="Priority" value={form.priority} onChange={event => setForm(value => ({ ...value, priority: event.target.value }))}><MenuItem value="low">Low</MenuItem><MenuItem value="normal">Normal</MenuItem><MenuItem value="high">High</MenuItem><MenuItem value="critical">Critical</MenuItem></TextField><TextField label="Due date and time" type="datetime-local" InputLabelProps={{ shrink: true }} value={form.due_at} onChange={event => setForm(value => ({ ...value, due_at: event.target.value }))}/><TextField label="Application path (optional)" placeholder="/afe/register" value={form.action_path} onChange={event => setForm(value => ({ ...value, action_path: event.target.value }))}/>{error && <Alert severity="error">{error}</Alert>}</Box>
    </FormDialog>
  </>
}

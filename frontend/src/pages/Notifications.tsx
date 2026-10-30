import { useEffect, useState } from 'react'
import { Alert, Box, Button, Chip, CircularProgress, MenuItem, Paper, TextField, Typography } from '@mui/material'
import { CampaignRounded, DoneAllRounded } from '@mui/icons-material'
import { FormDialog, PageHeading } from '../components/Common'
import { api, body } from '../lib/api'
import type { UserNotification } from '../lib/workflowTypes'
import { useAuth } from '../context/AuthContext'

const empty = { title: '', message: '', severity: 'info', action_path: '' }
export default function Notifications() {
  const { can } = useAuth()
  const [items, setItems] = useState<UserNotification[]>([])
  const [unread, setUnread] = useState(0)
  const [loading, setLoading] = useState(true)
  const [dialog, setDialog] = useState(false)
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load = () => { setLoading(true); api<{ items: UserNotification[]; unread_count: number }>('/notifications?limit=100').then(data => { setItems(data.items); setUnread(data.unread_count) }).finally(() => setLoading(false)) }
  useEffect(load, [])
  const markAll = async () => { await api('/notifications/read-all', { method: 'POST' }); load() }
  const send = async () => { setBusy(true); setError(''); try { await api('/notifications', { method: 'POST', body: body({ ...form, recipient_user_ids: [] }) }); setDialog(false); setForm(empty); load() } catch (err) { setError((err as Error).message) } finally { setBusy(false) } }
  return <>
    <PageHeading eyebrow="Other Managements" title="Notification centre" subtitle="Security, task and workspace messages in one place." action={<>{unread > 0 && <Button startIcon={<DoneAllRounded/>} onClick={() => void markAll()}>Mark all read</Button>}{can('notifications:manage') && <Button variant="contained" startIcon={<CampaignRounded/>} onClick={() => setDialog(true)}>Send announcement</Button>}</>}/>
    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress/></Box> : <Box display="grid" gap={1.25}>{items.length === 0 && <Paper variant="outlined" sx={{ p: 6, textAlign: 'center', color: 'text.secondary' }}>No notifications yet.</Paper>}{items.map(item => <Paper key={item.id} variant="outlined" sx={{ p: 2, bgcolor: item.read_at ? 'background.paper' : 'action.hover' }}><Box display="flex" justifyContent="space-between" gap={2}><Box><Box display="flex" alignItems="center" gap={1}><Typography fontWeight={item.read_at ? 700 : 850}>{item.title}</Typography><Chip size="small" label={item.severity}/></Box><Typography color="text.secondary" fontSize={13} mt={.5}>{item.message}</Typography></Box><Typography color="text.secondary" fontSize={11} whiteSpace="nowrap">{new Date(item.created_at).toLocaleString()}</Typography></Box></Paper>)}</Box>}
    <FormDialog open={dialog} title="Send workspace announcement" subtitle="This creates one notification for every active user in the current workspace." onClose={() => setDialog(false)} onSubmit={() => void send()} busy={busy} submitLabel="Send announcement" submitDisabled={!form.title.trim() || !form.message.trim()}>
      <Box display="grid" gap={2}><TextField label="Title" required value={form.title} onChange={event => setForm(value => ({ ...value, title: event.target.value }))}/><TextField label="Message" required multiline minRows={4} value={form.message} onChange={event => setForm(value => ({ ...value, message: event.target.value }))}/><TextField select label="Severity" value={form.severity} onChange={event => setForm(value => ({ ...value, severity: event.target.value }))}><MenuItem value="info">Information</MenuItem><MenuItem value="success">Success</MenuItem><MenuItem value="warning">Warning</MenuItem><MenuItem value="error">Urgent / error</MenuItem></TextField><TextField label="Application path (optional)" value={form.action_path} onChange={event => setForm(value => ({ ...value, action_path: event.target.value }))}/>{error && <Alert severity="error">{error}</Alert>}</Box>
    </FormDialog>
  </>
}

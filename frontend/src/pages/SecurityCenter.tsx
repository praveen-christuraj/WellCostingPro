import { useEffect, useState } from 'react'
import { Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@mui/material'
import { ContentCopyRounded, RefreshRounded } from '@mui/icons-material'
import { PageHeading } from '../components/Common'
import { api, body } from '../lib/api'
import type { PasswordResetRequest } from '../lib/workflowTypes'
import { useAuth } from '../context/AuthContext'

export default function SecurityCenter() {
  const { can } = useAuth()
  const [rows, setRows] = useState<PasswordResetRequest[]>([])
  const [users, setUsers] = useState<Array<{ id: string; full_name: string; email: string; is_active: boolean; failed_logins: number; locked_until: string | null }>>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<PasswordResetRequest | null>(null)
  const [decision, setDecision] = useState<'approve' | 'reject' | null>(null)
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [issued, setIssued] = useState<{ code: string; expires: string; email: string } | null>(null)
  const load = () => { setLoading(true); Promise.all([
    api<PasswordResetRequest[]>('/security/password-reset-requests'),
    api<Array<{ id: string; full_name: string; email: string; is_active: boolean; failed_logins: number; locked_until: string | null }>>('/security/users'),
  ]).then(([requests, accounts]) => { setRows(requests); setUsers(accounts) }).finally(() => setLoading(false)) }
  useEffect(load, [])
  const decide = async () => {
    if (!selected || !decision) return
    setBusy(true); setError('')
    try {
      if (decision === 'approve') {
        const result = await api<{ reset_code: string; expires_at: string }>(`/security/password-reset-requests/${selected.id}/approve`, { method: 'POST', body: body({ notes }) })
        setIssued({ code: result.reset_code, expires: result.expires_at, email: selected.user_email })
      } else await api(`/security/password-reset-requests/${selected.id}/reject`, { method: 'POST', body: body({ notes }) })
      setSelected(null); setDecision(null); setNotes(''); load()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  return <>
    <PageHeading eyebrow="User Management" title="Security centre" subtitle="Review password recovery requests and issue short-lived, single-use reset codes. Every decision is recorded in the audit log." action={<Button startIcon={<RefreshRounded/>} onClick={load}>Refresh</Button>}/>
    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress/></Box> : <TableContainer component={Paper} variant="outlined"><Table size="small">
      <TableHead><TableRow><TableCell>Request</TableCell><TableCell>User</TableCell><TableCell>Reason</TableCell><TableCell>Requested</TableCell><TableCell>Status</TableCell><TableCell align="right">Action</TableCell></TableRow></TableHead>
      <TableBody>{rows.length === 0 ? <TableRow><TableCell colSpan={6} align="center" sx={{ py: 6, color: 'text.secondary' }}>No password reset requests.</TableCell></TableRow> : rows.map(row => <TableRow key={row.id} hover>
        <TableCell><Typography fontWeight={750} fontSize={12}>{row.request_number}</Typography><Typography color="text.secondary" fontSize={11}>{row.requested_by_ip}</Typography></TableCell>
        <TableCell><Typography fontWeight={700} fontSize={12.5}>{row.user_name}</Typography><Typography color="text.secondary" fontSize={11.5}>{row.user_email}</Typography></TableCell>
        <TableCell sx={{ maxWidth: 300 }}>{row.reason || 'No reason supplied'}</TableCell><TableCell>{new Date(row.requested_at).toLocaleString()}</TableCell>
        <TableCell><Chip size="small" label={row.status} color={row.status === 'pending' ? 'warning' : row.status === 'completed' ? 'success' : 'default'}/></TableCell>
        <TableCell align="right">{row.status === 'pending' && can('security:password-reset') && <Box display="flex" justifyContent="flex-end" gap={1}><Button size="small" color="error" onClick={() => { setSelected(row); setDecision('reject'); setError('') }}>Reject</Button><Button size="small" variant="contained" onClick={() => { setSelected(row); setDecision('approve'); setError('') }}>Approve</Button></Box>}</TableCell>
      </TableRow>)}</TableBody>
    </Table></TableContainer>}
    {!loading && <Box mt={4}><Typography variant="h6" fontSize={17} fontWeight={800} mb={.5}>User account security</Typography><Typography color="text.secondary" fontSize={12.5} mb={1.5}>Current activation and temporary lockout state. Unlock only after verifying the user.</Typography><TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>User</TableCell><TableCell>Account</TableCell><TableCell>Lockout</TableCell><TableCell align="right">Action</TableCell></TableRow></TableHead><TableBody>{users.map(account => { const locked = !!account.locked_until && new Date(account.locked_until).getTime() > Date.now(); return <TableRow key={account.id}><TableCell><Typography fontWeight={700} fontSize={12.5}>{account.full_name}</Typography><Typography color="text.secondary" fontSize={11.5}>{account.email}</Typography></TableCell><TableCell><Chip size="small" label={account.is_active ? 'Active' : 'Inactive'} color={account.is_active ? 'success' : 'default'}/></TableCell><TableCell>{locked ? `Locked until ${new Date(account.locked_until!).toLocaleString()}` : 'Not locked'}</TableCell><TableCell align="right">{locked && can('security:unlock') && <Button size="small" onClick={async () => { await api(`/security/users/${account.id}/unlock`, { method: 'POST' }); load() }}>Unlock account</Button>}</TableCell></TableRow> })}</TableBody></Table></TableContainer></Box>}
    <Dialog open={!!selected} onClose={() => !busy && setSelected(null)} fullWidth maxWidth="sm"><DialogTitle>{decision === 'approve' ? 'Approve password reset' : 'Reject password reset'}</DialogTitle><DialogContent><Box display="grid" gap={2} pt={1}><Typography fontSize={13}>Request for <strong>{selected?.user_email}</strong>. {decision === 'approve' ? 'The code is shown only once after approval.' : 'The user can submit another request later.'}</Typography><TextField label="Administrative notes" multiline minRows={3} value={notes} onChange={event => setNotes(event.target.value)}/>{error && <Alert severity="error">{error}</Alert>}</Box></DialogContent><DialogActions><Button onClick={() => setSelected(null)}>Cancel</Button><Button color={decision === 'reject' ? 'error' : 'primary'} variant="contained" disabled={busy} onClick={() => void decide()}>{busy ? 'Saving…' : decision === 'approve' ? 'Approve and issue code' : 'Reject request'}</Button></DialogActions></Dialog>
    <Dialog open={!!issued} onClose={() => setIssued(null)} fullWidth maxWidth="sm"><DialogTitle>Reset code issued</DialogTitle><DialogContent><Alert severity="warning" sx={{ mb: 2 }}>This code is displayed only now. Share it with {issued?.email} using an approved secure channel.</Alert><TextField fullWidth value={issued?.code || ''} label="Single-use reset code" InputProps={{ readOnly: true }} helperText={issued ? `Expires ${new Date(issued.expires).toLocaleString()}` : ''}/></DialogContent><DialogActions><Button startIcon={<ContentCopyRounded/>} onClick={() => issued && navigator.clipboard.writeText(issued.code)}>Copy code</Button><Button variant="contained" onClick={() => setIssued(null)}>Done</Button></DialogActions></Dialog>
  </>
}

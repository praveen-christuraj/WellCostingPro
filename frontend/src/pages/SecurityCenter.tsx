import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, CircularProgress, Divider, Menu, MenuItem, Paper, Tab, Table, TableBody,
  TableCell, TableContainer, TableHead, TablePagination, TableRow, Tabs, TextField, Tooltip, Typography,
} from '@mui/material'
import {
  ContentCopyRounded, FilterListRounded, KeyRounded, LockOpenRounded, LockRounded, LogoutRounded,
  ManageAccountsRounded, RefreshRounded, SecurityRounded,
} from '@mui/icons-material'
import { ErrorMessage, FormDialog, PageHeading, PanelDialog, Tag, type Tone } from '../components/Common'
import { api, body } from '../lib/api'
import { exportCsv, exportPdf, exportXlsx, type ExportColumn } from '../lib/export'
import type { PasswordResetRequest, ResetCode, SecurityAccount, SecurityBulkAction, SecurityOverview } from '../lib/workflowTypes'
import { useAuth } from '../context/AuthContext'

type AccountAction = 'reset-code' | 'force-password-change' | 'revoke-sessions' | 'lock' | 'unlock'

const PAGE_SIZES = [20, 50, 100]
const STATUS_TONE: Record<string, Tone> = {
  pending: 'warning', approved: 'info', completed: 'success', rejected: 'neutral', expired: 'neutral',
}
const REQUEST_STATUSES = ['pending', 'approved', 'completed', 'rejected', 'expired'] as const

const ACTION_COPY: Record<AccountAction, { title: string; subtitle: string; submit: string; danger?: boolean }> = {
  'reset-code': {
    title: 'Issue a one-time reset code',
    subtitle: 'The account holder does not need to have asked for help. The code is shown once and lasts for the configured window.',
    submit: 'Issue code',
  },
  'force-password-change': {
    title: 'Force a new password',
    subtitle: 'The account is flagged immediately, every session is revoked, and the workspace stays closed until the password is changed.',
    submit: 'Force password change',
    danger: true,
  },
  'revoke-sessions': {
    title: 'Revoke all sessions',
    subtitle: 'Every signed-in device is signed out on the next request. The password itself is not changed.',
    submit: 'Revoke sessions',
    danger: true,
  },
  lock: {
    title: 'Lock the account',
    subtitle: 'The account can no longer sign in until somebody with the unlock capability releases it. All sessions are revoked.',
    submit: 'Lock account',
    danger: true,
  },
  unlock: {
    title: 'Unlock the account',
    subtitle: 'Clears the lockout and the failed sign-in counter so the account holder can sign in again.',
    submit: 'Unlock account',
  },
}

const BULK_COPY: Record<SecurityBulkAction, string> = {
  'force-password-change': 'Force a new password',
  'revoke-sessions': 'Revoke all sessions',
  lock: 'Lock accounts',
  unlock: 'Unlock accounts',
}

function days(value: string | null): string {
  if (!value) return 'Never recorded'
  const diff = Math.floor((Date.now() - new Date(value).getTime()) / 86400000)
  if (diff <= 0) return 'Today'
  return `${diff} day${diff === 1 ? '' : 's'} ago`
}

function StatCard({ label, value, hint, tone = 'info' }: { label: string; value: number | string | undefined; hint: string; tone?: Tone }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
    <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
    <Typography className="stat-value" sx={{ fontSize: 26, my: .8 }}>{value === undefined ? '…' : value}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
    <Box sx={{ mt: 1, height: 3, borderRadius: 2, bgcolor: `var(--wcp-tone-${tone}-border)` }}/>
  </Paper>
}

export default function SecurityCenter() {
  const { can, user } = useAuth()
  const [overview, setOverview] = useState<SecurityOverview | null>(null)
  const [requests, setRequests] = useState<PasswordResetRequest[]>([])
  const [accounts, setAccounts] = useState<SecurityAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'requests' | 'accounts' | 'policy'>('requests')

  // Requests view state
  const [requestStatus, setRequestStatus] = useState('pending')
  const [requestSearch, setRequestSearch] = useState('')
  const [requestFrom, setRequestFrom] = useState('')
  const [requestTo, setRequestTo] = useState('')
  const [requestPage, setRequestPage] = useState(0)
  const [requestPageSize, setRequestPageSize] = useState(20)

  // Accounts view state
  const [accountSearch, setAccountSearch] = useState('')
  const [accountState, setAccountState] = useState('all')
  const [accountPage, setAccountPage] = useState(0)
  const [accountPageSize, setAccountPageSize] = useState(20)
  const [selected, setSelected] = useState<string[]>([])

  // Dialogs
  const [decision, setDecision] = useState<{ row: PasswordResetRequest; action: 'approve' | 'reject' } | null>(null)
  const [accountAction, setAccountAction] = useState<{ account: SecurityAccount; action: AccountAction } | null>(null)
  const [bulkAction, setBulkAction] = useState<SecurityBulkAction | null>(null)
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [dialogError, setDialogError] = useState('')
  const [issued, setIssued] = useState<{ code: string; expires: string; email: string; request: string } | null>(null)
  const [notice, setNotice] = useState('')
  const [exportAnchor, setExportAnchor] = useState<HTMLElement | null>(null)

  // A reviewer may hold only security:password-reset (the reset queue), and an
  // unlock-only role may hold neither register. Ask only for what the capability
  // set allows, so the page never opens on a wall of 403s.
  const canReadRegisters = can('security:read')
  const canSeeQueue = canReadRegisters || can('security:password-reset')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [summary, resetRows, accountRows] = await Promise.all([
        api<SecurityOverview>('/security/overview', { action: 'Load the security summary' }),
        canSeeQueue
          ? api<PasswordResetRequest[]>('/security/password-reset-requests', { action: 'Load password reset requests' })
          : Promise.resolve([] as PasswordResetRequest[]),
        canReadRegisters
          ? api<SecurityAccount[]>('/security/users', { action: 'Load workspace accounts' })
          : Promise.resolve([] as SecurityAccount[]),
      ])
      setOverview(summary); setRequests(resetRows); setAccounts(accountRows)
      setSelected(ids => ids.filter(id => accountRows.some(account => account.id === id)))
      // Land on the first tab this viewer can actually use: an unlock-only role
      // sees the accounts, a queue-only reviewer sees the requests.
      setTab(current => {
        if (current === 'requests' && !canSeeQueue) return canReadRegisters ? 'accounts' : 'policy'
        if (current === 'accounts' && !canReadRegisters) return canSeeQueue ? 'requests' : 'policy'
        return current
      })
    } catch (caught) {
      setError((caught as Error).message)
    } finally { setLoading(false) }
  }, [canReadRegisters, canSeeQueue])
  useEffect(() => { void load() }, [load])

  const resetDialogs = () => { setDecision(null); setAccountAction(null); setBulkAction(null); setNotes(''); setDialogError('') }

  const runDecision = async () => {
    if (!decision) return
    setBusy(true); setDialogError('')
    try {
      if (decision.action === 'approve') {
        const result = await api<ResetCode>(`/security/password-reset-requests/${decision.row.id}/approve`, {
          method: 'POST', body: body({ notes }), action: 'Approve the reset request',
        })
        setIssued({ code: result.reset_code, expires: result.expires_at, email: decision.row.user_email, request: decision.row.request_number })
        setNotice(`Reset request ${decision.row.request_number} approved.`)
      } else {
        await api(`/security/password-reset-requests/${decision.row.id}/reject`, {
          method: 'POST', body: body({ notes }), action: 'Reject the reset request',
        })
        setNotice(`Reset request ${decision.row.request_number} rejected.`)
      }
      resetDialogs(); await load()
    } catch (caught) { setDialogError((caught as Error).message) } finally { setBusy(false) }
  }

  const runAccountAction = async () => {
    if (!accountAction) return
    setBusy(true); setDialogError('')
    try {
      if (accountAction.action === 'reset-code') {
        const result = await api<ResetCode>(`/security/users/${accountAction.account.id}/reset-code`, {
          method: 'POST', body: body({ notes }), action: 'Issue a reset code',
        })
        setIssued({ code: result.reset_code, expires: result.expires_at, email: accountAction.account.email, request: result.request.request_number })
        setNotice(`One-time reset code issued for ${accountAction.account.email}.`)
      } else if (accountAction.action === 'unlock') {
        await api(`/security/users/${accountAction.account.id}/unlock`, { method: 'POST', action: 'Unlock the account' })
        setNotice(`${accountAction.account.email} unlocked.`)
      } else {
        await api(`/security/users/${accountAction.account.id}/${accountAction.action}`, {
          method: 'POST', body: body({ notes }), action: ACTION_COPY[accountAction.action].title,
        })
        setNotice(`${ACTION_COPY[accountAction.action].title} applied to ${accountAction.account.email}.`)
      }
      resetDialogs(); await load()
    } catch (caught) { setDialogError((caught as Error).message) } finally { setBusy(false) }
  }

  const runBulk = async () => {
    if (!bulkAction) return
    setBusy(true); setDialogError('')
    try {
      const result = await api<{ affected: number; skipped: number }>('/security/users/bulk', {
        method: 'POST',
        body: body({ user_ids: selected, action: bulkAction, notes }),
        action: BULK_COPY[bulkAction],
      })
      setNotice(`${BULK_COPY[bulkAction]}: ${result.affected} account(s) updated${result.skipped ? `, ${result.skipped} skipped` : ''}.`)
      setSelected([]); resetDialogs(); await load()
    } catch (caught) { setDialogError((caught as Error).message) } finally { setBusy(false) }
  }

  const filteredRequests = useMemo(() => {
    const needle = requestSearch.trim().toLowerCase()
    return requests.filter(row => {
      if (requestStatus && row.status !== requestStatus) return false
      if (needle && ![row.request_number, row.user_name, row.user_email, row.reason].some(value => (value || '').toLowerCase().includes(needle))) return false
      if (requestFrom && new Date(row.requested_at) < new Date(`${requestFrom}T00:00:00`)) return false
      if (requestTo && new Date(row.requested_at) > new Date(`${requestTo}T23:59:59`)) return false
      return true
    })
  }, [requests, requestStatus, requestSearch, requestFrom, requestTo])

  const filteredAccounts = useMemo(() => {
    const needle = accountSearch.trim().toLowerCase()
    const locked = (account: SecurityAccount) => !!account.locked_until && new Date(account.locked_until).getTime() > Date.now()
    return accounts.filter(account => {
      if (needle && ![account.full_name, account.email, ...account.role_names].some(value => (value || '').toLowerCase().includes(needle))) return false
      if (accountState === 'locked') return locked(account)
      if (accountState === 'active') return account.is_active && !locked(account)
      if (accountState === 'inactive') return !account.is_active
      if (accountState === 'must-change') return account.must_change_password
      if (accountState === 'expired') return account.password_expired
      if (accountState === 'expiring') return !account.password_expired && account.password_days_remaining !== null && account.password_days_remaining <= 14
      if (accountState === 'signed-in') return account.active_sessions > 0
      return true
    })
  }, [accounts, accountSearch, accountState])

  const requestColumns = useMemo<ExportColumn<PasswordResetRequest>[]>(() => [
    { header: 'Request', value: row => row.request_number },
    { header: 'User', value: row => `${row.user_name} <${row.user_email}>` },
    { header: 'Initiated by', value: row => row.initiated_by === 'administrator' ? 'Administrator' : 'User request' },
    { header: 'Reason', value: row => row.reason || '' },
    { header: 'Requested', value: row => new Date(row.requested_at).toLocaleString() },
    { header: 'Status', value: row => row.status },
    { header: 'Review notes', value: row => row.review_notes || '' },
  ], [])

  const accountColumns = useMemo<ExportColumn<SecurityAccount>[]>(() => [
    { header: 'User', value: row => row.full_name },
    { header: 'Email', value: row => row.email },
    { header: 'Roles', value: row => row.role_names.join(', ') },
    { header: 'Active', value: row => row.is_active ? 'Yes' : 'No' },
    { header: 'Locked until', value: row => row.locked_until ? new Date(row.locked_until).toLocaleString() : '' },
    { header: 'Must change password', value: row => row.must_change_password ? 'Yes' : 'No' },
    { header: 'Password changed', value: row => row.password_changed_at ? new Date(row.password_changed_at).toLocaleString() : 'Never recorded' },
    {
      header: 'Password expires',
      value: row => row.password_expired ? 'Expired — change required'
        : row.password_expires_at ? `${new Date(row.password_expires_at).toLocaleDateString()} (${row.password_days_remaining ?? 0} days)`
          : 'Never (policy disabled)',
    },
    { header: 'Last sign-in', value: row => row.last_login_at ? new Date(row.last_login_at).toLocaleString() : 'Never recorded' },
    { header: 'Active sessions', value: row => String(row.active_sessions) },
  ], [])

  const exportWith = (format: 'csv' | 'xlsx' | 'pdf') => {
    const asAccounts = tab === 'accounts'
    const stamp = new Date().toISOString().slice(0, 10)
    if (asAccounts) {
      if (format === 'csv') exportCsv(`security-accounts-${stamp}.csv`, filteredAccounts, accountColumns)
      else if (format === 'xlsx') void exportXlsx(`security-accounts-${stamp}.xlsx`, filteredAccounts, accountColumns)
      else void exportPdf(`security-accounts-${stamp}.pdf`, 'Workspace account security', filteredAccounts, accountColumns)
    } else {
      if (format === 'csv') exportCsv(`password-reset-requests-${stamp}.csv`, filteredRequests, requestColumns)
      else if (format === 'xlsx') void exportXlsx(`password-reset-requests-${stamp}.xlsx`, filteredRequests, requestColumns)
      else void exportPdf(`password-reset-requests-${stamp}.pdf`, 'Password reset requests', filteredRequests, requestColumns)
    }
  }

  const canReset = can('security:password-reset')
  const canUnlock = can('security:unlock')
  const isOwner = !!user?.is_owner
  const selfSelected = selected.some(id => id === user?.id)
  const pendingCount = requests.filter(row => row.status === 'pending').length
  const pageRequests = filteredRequests.slice(requestPage * requestPageSize, requestPage * requestPageSize + requestPageSize)
  const pageAccounts = filteredAccounts.slice(accountPage * accountPageSize, accountPage * accountPageSize + accountPageSize)
  const allVisibleSelected = pageAccounts.length > 0 && pageAccounts.every(account => selected.includes(account.id))

  return <>
    <PageHeading
      eyebrow="USER MANAGEMENT / SECURITY CENTRE"
      title="Security centre"
      subtitle="Review password recovery, and control any account's password and sessions without waiting for a user request. Every decision is audited."
      action={<>
        <Button onClick={event => setExportAnchor(event.currentTarget)} disabled={loading}>Export</Button>
        <Menu anchorEl={exportAnchor} open={!!exportAnchor} onClose={() => setExportAnchor(null)}>
          <MenuItem onClick={() => { setExportAnchor(null); exportWith('csv') }}>CSV (.csv)</MenuItem>
          <MenuItem onClick={() => { setExportAnchor(null); exportWith('xlsx') }}>Excel (.xlsx)</MenuItem>
          <MenuItem onClick={() => { setExportAnchor(null); exportWith('pdf') }}>PDF (.pdf)</MenuItem>
        </Menu>
        <Button startIcon={<RefreshRounded/>} variant="contained" onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</Button>
      </>}
    />

    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>

    <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(5, minmax(0, 1fr))' }, mb: 2.5, mt: 1 }}>
      <StatCard label="Accounts" value={overview?.users} hint={`${overview?.active_users ?? 0} active in this workspace`} tone="info"/>
      <StatCard label="Locked" value={overview?.locked_users} hint="Blocked from signing in" tone={overview?.locked_users ? 'error' : 'neutral'}/>
      <StatCard label="Pending reviews" value={overview?.pending_requests} hint="Reset requests awaiting a decision" tone={overview?.pending_requests ? 'warning' : 'neutral'}/>
      <StatCard label="Codes awaiting use" value={overview?.awaiting_use} hint={`Single-use, ${overview?.reset_minutes ?? 30} minutes`} tone="info"/>
      <StatCard label="Forced changes" value={overview?.must_change_password} hint="Must set a new password first" tone={overview?.must_change_password ? 'error' : 'neutral'}/>
    </Box>

    <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
      <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ px: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Tab value="requests" label={`Reset requests${pendingCount ? ` (${pendingCount})` : ''}`} disabled={!canSeeQueue}/>
        <Tab value="accounts" label="Accounts" disabled={!canReadRegisters}/>
        <Tab value="policy" label="Password policy"/>
      </Tabs>

      {!canReadRegisters && <Alert severity="info" sx={{ borderRadius: 0 }}>
        Your role can act on password recovery but not read the full account register. The reset queue and the policy are shown;
        ask an administrator for <strong>security:read</strong> if you also need the account list.
      </Alert>}
      {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress/></Box> : <>
        {tab === 'requests' && <>
          <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Box display="flex" alignItems="center" gap={1} mb={1.4}><FilterListRounded sx={{ fontSize: 17, color: 'text.secondary' }}/><Typography fontWeight={800} fontSize={12} textTransform="uppercase" letterSpacing={0.8}>Filters</Typography></Box>
            <Box display="flex" gap={1.5} flexWrap="wrap" alignItems="center">
              <TextField size="small" label="Search request, user or reason" value={requestSearch} onChange={event => { setRequestSearch(event.target.value); setRequestPage(0) }} sx={{ minWidth: 250 }}/>
              <TextField select size="small" label="Status" value={requestStatus} onChange={event => { setRequestStatus(event.target.value); setRequestPage(0) }} sx={{ minWidth: 150 }}>
                <MenuItem value="">All statuses</MenuItem>
                {REQUEST_STATUSES.map(status => <MenuItem key={status} value={status}>{status}</MenuItem>)}
              </TextField>
              <Typography color="text.secondary" fontSize={12} fontWeight={700} textTransform="uppercase" letterSpacing={0.8} ml={1}>Date range</Typography>
              <TextField size="small" type="date" label="From" value={requestFrom} onChange={event => { setRequestFrom(event.target.value); setRequestPage(0) }} InputLabelProps={{ shrink: true }}/>
              <Typography color="text.secondary" fontSize={12}>to</Typography>
              <TextField size="small" type="date" label="To" value={requestTo} onChange={event => { setRequestTo(event.target.value); setRequestPage(0) }} InputLabelProps={{ shrink: true }}/>
              {(requestSearch || requestStatus !== 'pending' || requestFrom || requestTo) && <Button size="small" color="inherit" onClick={() => { setRequestSearch(''); setRequestStatus(''); setRequestFrom(''); setRequestTo(''); setRequestPage(0) }}>Clear</Button>}
            </Box>
          </Box>
          <TableContainer>
            <Table size="small">
              <TableHead><TableRow>
                <TableCell>Request</TableCell><TableCell>Account</TableCell><TableCell>Raised by</TableCell>
                <TableCell>Reason and review</TableCell><TableCell>Requested</TableCell><TableCell>Status</TableCell>
                <TableCell align="right">Decision</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {pageRequests.length === 0 ? <TableRow><TableCell colSpan={7} align="center" sx={{ py: 6, color: 'text.secondary' }}>
                  {requests.length === 0 ? 'No password reset has been requested or issued in this workspace yet.' : 'No request matches these filters.'}
                </TableCell></TableRow> : pageRequests.map(row => <TableRow key={row.id} hover>
                  <TableCell>
                    <Typography fontWeight={750} fontSize={12}>{row.request_number}</Typography>
                    <Typography color="text.secondary" fontSize={11}>{row.requested_by_ip || '—'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography fontWeight={700} fontSize={12.5}>{row.user_name}</Typography>
                    <Typography color="text.secondary" fontSize={11.5}>{row.user_email}</Typography>
                  </TableCell>
                  <TableCell><Tag tone={row.initiated_by === 'administrator' ? 'warning' : 'info'}>{row.initiated_by === 'administrator' ? 'Administrator' : 'User request'}</Tag></TableCell>
                  <TableCell sx={{ maxWidth: 330 }}>
                    <Typography fontSize={12}>{row.reason || 'No reason supplied'}</Typography>
                    {row.review_notes && <Typography color="text.secondary" fontSize={11.5} mt={.4}>Review: {row.review_notes}</Typography>}
                    {row.reviewed_at && <Typography color="text.secondary" fontSize={11} mt={.3}>Decided {new Date(row.reviewed_at).toLocaleString()}</Typography>}
                  </TableCell>
                  <TableCell>{new Date(row.requested_at).toLocaleString()}</TableCell>
                  <TableCell><Tag tone={STATUS_TONE[row.status] ?? 'neutral'}>{row.status}</Tag></TableCell>
                  <TableCell align="right">
                    {row.status === 'pending' && canReset ? <Box display="flex" justifyContent="flex-end" gap={.5}>
                      <Button size="small" color="error" onClick={() => { setDecision({ row, action: 'reject' }); setNotes(''); setDialogError('') }}>Reject</Button>
                      <Button size="small" variant="contained" onClick={() => { setDecision({ row, action: 'approve' }); setNotes(''); setDialogError('') }}>Approve</Button>
                    </Box> : <Typography color="text.secondary" fontSize={11.5}>{row.status === 'pending' ? 'Needs security:password-reset' : '—'}</Typography>}
                  </TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination component="div" count={filteredRequests.length} page={requestPage} rowsPerPage={requestPageSize}
            rowsPerPageOptions={PAGE_SIZES} onPageChange={(_, value) => setRequestPage(value)}
            onRowsPerPageChange={event => { setRequestPageSize(Number(event.target.value)); setRequestPage(0) }}/>
        </>}

        {tab === 'accounts' && <>
          <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Box display="flex" alignItems="center" gap={1} mb={1.4}><FilterListRounded sx={{ fontSize: 17, color: 'text.secondary' }}/><Typography fontWeight={800} fontSize={12} textTransform="uppercase" letterSpacing={0.8}>Filters</Typography></Box>
            <Box display="flex" gap={1.5} flexWrap="wrap" alignItems="center">
              <TextField size="small" label="Search name, e-mail or role" value={accountSearch} onChange={event => { setAccountSearch(event.target.value); setAccountPage(0) }} sx={{ minWidth: 250 }}/>
              <TextField select size="small" label="Account state" value={accountState} onChange={event => { setAccountState(event.target.value); setAccountPage(0) }} sx={{ minWidth: 180 }}>
                <MenuItem value="all">All accounts</MenuItem>
                <MenuItem value="active">Active and unlocked</MenuItem>
                <MenuItem value="locked">Locked</MenuItem>
                <MenuItem value="inactive">Deactivated</MenuItem>
                <MenuItem value="must-change">Must change password</MenuItem>
                <MenuItem value="expired">Password expired</MenuItem>
                <MenuItem value="expiring">Password expires in 14 days</MenuItem>
                <MenuItem value="signed-in">Has active sessions</MenuItem>
              </TextField>
              {(accountSearch || accountState !== 'all') && <Button size="small" color="inherit" onClick={() => { setAccountSearch(''); setAccountState('all'); setAccountPage(0) }}>Clear</Button>}
            </Box>
          </Box>

          {selected.length > 0 && <Box sx={{ px: 2, py: 1.4, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'action.hover' }} display="flex" alignItems="center" gap={1} flexWrap="wrap">
            <Typography fontSize={12.5} fontWeight={700}>{selected.length} selected</Typography>
            <Divider orientation="vertical" flexItem/>
            {canReset && <Button size="small" onClick={() => { setBulkAction('force-password-change'); setNotes(''); setDialogError('') }}>Force new password</Button>}
            {canReset && <Button size="small" onClick={() => { setBulkAction('revoke-sessions'); setNotes(''); setDialogError('') }}>Revoke sessions</Button>}
            {canUnlock && <Button size="small" color="error" onClick={() => { setBulkAction('lock'); setNotes(''); setDialogError('') }}>Lock</Button>}
            {canUnlock && <Button size="small" onClick={() => { setBulkAction('unlock'); setNotes(''); setDialogError('') }}>Unlock</Button>}
            <Button size="small" color="inherit" sx={{ ml: 'auto' }} onClick={() => setSelected([])}>Clear selection</Button>
          </Box>}
          {selected.length > 0 && selfSelected && <Typography fontSize={11.5} color="text.secondary" sx={{ px: 2, py: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
            Your own account is in the selection; it is skipped automatically because these actions cannot be applied to the administrator performing them.
          </Typography>}

          <TableContainer>
            <Table size="small">
              <TableHead><TableRow>
                <TableCell padding="checkbox">
                  <Checkbox size="small" checked={allVisibleSelected} indeterminate={!allVisibleSelected && pageAccounts.some(account => selected.includes(account.id))}
                    onChange={event => setSelected(event.target.checked ? Array.from(new Set([...selected, ...pageAccounts.map(account => account.id)])) : selected.filter(id => !pageAccounts.some(account => account.id === id)))}
                    inputProps={{ 'aria-label': 'Select every account on this page' }}/>
                </TableCell>
                <TableCell>Account</TableCell><TableCell>Roles</TableCell><TableCell>State</TableCell>
                <TableCell>Password</TableCell><TableCell>Last sign-in</TableCell><TableCell>Sessions</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {pageAccounts.length === 0 ? <TableRow><TableCell colSpan={8} align="center" sx={{ py: 6, color: 'text.secondary' }}>No account matches these filters.</TableCell></TableRow> : pageAccounts.map(account => {
                  const locked = !!account.locked_until && new Date(account.locked_until).getTime() > Date.now()
                  const self = account.id === user?.id
                  // The API refuses these on purpose (they answer 409), so the buttons say
                  // why up front instead of letting the user press a control that cannot work.
                  const selfHint = 'Your own password and sessions are managed from the account menu'
                  const ownerHint = 'Only an owner can lock another owner account'
                  const ownerTarget = account.is_owner && !isOwner
                  return <TableRow key={account.id} hover>
                    <TableCell padding="checkbox">
                      <Checkbox size="small" checked={selected.includes(account.id)}
                        onChange={event => setSelected(event.target.checked ? [...selected, account.id] : selected.filter(id => id !== account.id))}
                        inputProps={{ 'aria-label': `Select ${account.email}` }}/>
                    </TableCell>
                    <TableCell>
                      <Typography fontWeight={700} fontSize={12.5}>{account.full_name} {account.is_owner && <Tag>Owner</Tag>}</Typography>
                      <Typography color="text.secondary" fontSize={11.5}>{account.email}</Typography>
                    </TableCell>
                    <TableCell sx={{ maxWidth: 190 }}><Typography fontSize={11.5} color="text.secondary">{account.role_names.join(', ') || 'No role'}</Typography></TableCell>
                    <TableCell><Box display="flex" gap={.5} flexWrap="wrap">
                      <Tag tone={account.is_active ? 'success' : 'neutral'}>{account.is_active ? 'Active' : 'Deactivated'}</Tag>
                      {locked && <Tag tone="error">Locked</Tag>}
                      {account.must_change_password && <Tag tone="warning">Change password</Tag>}
                      {account.password_expired && <Tag tone="error">Password expired</Tag>}
                      {account.failed_logins > 0 && <Tag tone="warning">{account.failed_logins} failed</Tag>}
                    </Box></TableCell>
                    <TableCell>
                      <Typography fontSize={12}>{days(account.password_changed_at)}</Typography>
                      {account.password_changed_at && <Typography color="text.secondary" fontSize={11}>{new Date(account.password_changed_at).toLocaleDateString()}</Typography>}
                      {account.password_expires_at && <Typography color={account.password_expired ? 'error.main' : 'text.secondary'} fontSize={11}>
                        {account.password_expired ? 'Expired' : `Expires in ${account.password_days_remaining ?? 0}d`}
                      </Typography>}
                    </TableCell>
                    <TableCell>{account.last_login_at ? new Date(account.last_login_at).toLocaleString() : 'Never'}</TableCell>
                    <TableCell>{account.active_sessions}</TableCell>
                    <TableCell align="right">
                      <Box display="flex" justifyContent="flex-end" gap={.25} flexWrap="wrap">
                        {canReset && <Tooltip title={account.is_active ? 'Issue a one-time reset code — no request needed' : 'Reactivate this account in User Management before issuing a reset code'}>
                          <span><Button size="small" disabled={!account.is_active} startIcon={<KeyRounded sx={{ fontSize: 15 }}/>}
                            onClick={() => { setAccountAction({ account, action: 'reset-code' }); setNotes(''); setDialogError('') }}>Code</Button></span>
                        </Tooltip>}
                        {canReset && <Tooltip title={self ? selfHint : 'Require a new password at the next sign-in'}>
                          <span><Button size="small" disabled={self}
                            onClick={() => { setAccountAction({ account, action: 'force-password-change' }); setNotes(''); setDialogError('') }}>Force change</Button></span>
                        </Tooltip>}
                        {canReset && <Tooltip title={self ? selfHint : account.active_sessions === 0 ? 'This account has no active session to end' : 'Sign this account out everywhere'}>
                          <span><Button size="small" startIcon={<LogoutRounded sx={{ fontSize: 15 }}/>} disabled={self || account.active_sessions === 0}
                            onClick={() => { setAccountAction({ account, action: 'revoke-sessions' }); setNotes(''); setDialogError('') }}>Sign out</Button></span>
                        </Tooltip>}
                        {canUnlock && (locked
                          ? <Button size="small" startIcon={<LockOpenRounded sx={{ fontSize: 15 }}/>} onClick={() => { setAccountAction({ account, action: 'unlock' }); setNotes(''); setDialogError('') }}>Unlock</Button>
                          : <Tooltip title={self ? 'You cannot lock your own account' : ownerTarget ? ownerHint : 'Block this account from signing in'}>
                            <span><Button size="small" color="error" startIcon={<LockRounded sx={{ fontSize: 15 }}/>} disabled={self || ownerTarget}
                              onClick={() => { setAccountAction({ account, action: 'lock' }); setNotes(''); setDialogError('') }}>Lock</Button></span>
                          </Tooltip>)}
                      </Box>
                      {self && <Typography fontSize={11} color="text.secondary">Your account</Typography>}
                    </TableCell>
                  </TableRow>
                })}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination component="div" count={filteredAccounts.length} page={accountPage} rowsPerPage={accountPageSize}
            rowsPerPageOptions={PAGE_SIZES} onPageChange={(_, value) => setAccountPage(value)}
            onRowsPerPageChange={event => { setAccountPageSize(Number(event.target.value)); setAccountPage(0) }}/>
        </>}

        {tab === 'policy' && <Box sx={{ p: { xs: 2, sm: 3 }, display: 'grid', gap: 2.5, maxWidth: 900 }}>
          <Box>
            <Typography fontWeight={800} fontSize={15} mb={.5}>How the security centre controls passwords</Typography>
            <Typography color="text.secondary" fontSize={12.5} sx={{ lineHeight: 1.6 }}>
              Every action here is available without a request from the account holder, because compromise, departure or a
              suspected leak cannot wait for one. Each action records the administrator, the reason and the time in the audit
              trail, and the account holder is notified so the change is never silent.
            </Typography>
          </Box>
          <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' } }}>
            {[
              { icon: <KeyRounded sx={{ fontSize: 18 }}/>, title: 'One-time reset code', body: `Issued on demand or after a request. Single use, hashed at rest, expires after ${overview?.reset_minutes ?? 30} minutes, and revokes every session when redeemed.` },
              { icon: <LockRounded sx={{ fontSize: 18 }}/>, title: 'Forced password change', body: 'Flags the account so only the password screen is reachable, revokes all sessions, and clears the flag once a compliant password is set.' },
              { icon: <LogoutRounded sx={{ fontSize: 18 }}/>, title: 'Session revocation', body: 'Deletes every refresh session and invalidates existing access tokens, so a suspected device loses access immediately.' },
              { icon: <ManageAccountsRounded sx={{ fontSize: 18 }}/>, title: 'Account lock', body: 'Blocks sign-in until an administrator releases it. Locking also revokes sessions; repeated failed sign-ins lock automatically for 15 minutes.' },
            ].map(item => <Paper key={item.title} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
              <Box display="flex" alignItems="center" gap={1} mb={.6}>
                <Box className="stat-icon" sx={{ color: 'primary.main', bgcolor: 'primary.light', width: 30, height: 30 }}>{item.icon}</Box>
                <Typography fontWeight={750} fontSize={13}>{item.title}</Typography>
              </Box>
              <Typography color="text.secondary" fontSize={12} sx={{ lineHeight: 1.55 }}>{item.body}</Typography>
            </Paper>)}
          </Box>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, bgcolor: 'background.default' }}>
            <Box display="flex" alignItems="center" gap={1} mb={.8}><SecurityRounded sx={{ fontSize: 18, color: 'text.secondary' }}/><Typography fontWeight={800} fontSize={13}>Password standard</Typography></Box>
            <Typography color="text.secondary" fontSize={12.5} sx={{ lineHeight: 1.7 }}>
              12–128 characters · at least three of lowercase, uppercase, number and symbol · must not contain the account's
              e-mail address · the last five passwords cannot be reused · the workspace requires 6 or more failures before an
              automatic 15-minute lockout. Enforcement happens in the API, so these rules apply to sign-in recovery, the account
              menu and the security centre equally.
            </Typography>
          </Paper>
        </Box>}
      </>}
    </Paper>

    {/* Approve / reject a reset request */}
    <FormDialog open={!!decision} title={decision?.action === 'approve' ? 'Approve password reset' : 'Reject password reset'}
      subtitle={decision?.action === 'approve'
        ? 'A single-use code is generated now and shown once. Share it with the account holder through an approved secure channel.'
        : 'The account holder keeps their current password. They can request help again later.'}
      onClose={resetDialogs} onSubmit={() => void runDecision()} busy={busy}
      submitLabel={decision?.action === 'approve' ? 'Approve and issue code' : 'Reject request'}
      danger={decision?.action === 'reject'} maxWidth="sm">
      <Box display="grid" gap={2} pt={.5}>
        <Typography fontSize={12.5}>Request <strong>{decision?.row.request_number}</strong> for <strong>{decision?.row.user_email}</strong>.</Typography>
        <TextField label="Administrative notes" multiline minRows={3} value={notes} onChange={event => setNotes(event.target.value)}
          helperText="Record how identity was verified or why the request was refused. Kept in the audit trail."/>
        <ErrorMessage message={dialogError}/>
      </Box>
    </FormDialog>

    {/* Administrator-initiated account action */}
    <FormDialog open={!!accountAction} title={accountAction ? ACTION_COPY[accountAction.action].title : ''}
      subtitle={accountAction ? ACTION_COPY[accountAction.action].subtitle : ''}
      onClose={resetDialogs} onSubmit={() => void runAccountAction()} busy={busy}
      submitLabel={accountAction ? ACTION_COPY[accountAction.action].submit : 'Apply'} danger={accountAction?.action ? !!ACTION_COPY[accountAction.action].danger : false}
      maxWidth="sm">
      <Box display="grid" gap={2} pt={.5}>
        {accountAction && <Box>
          <Typography fontWeight={700} fontSize={13}>{accountAction.account.full_name}</Typography>
          <Typography color="text.secondary" fontSize={12}>{accountAction.account.email} · {accountAction.account.role_names.join(', ') || 'No role'}</Typography>
        </Box>}
        {accountAction?.action !== 'unlock' && <TextField label="Reason (recommended)" multiline minRows={2} value={notes} onChange={event => setNotes(event.target.value)}
          helperText="Shown to the account holder and stored in the audit trail."/>}
        <ErrorMessage message={dialogError}/>
      </Box>
    </FormDialog>

    {/* Bulk account action */}
    <FormDialog open={!!bulkAction} title={bulkAction ? BULK_COPY[bulkAction] : ''}
      subtitle={`This applies to ${selected.length} selected account(s) in one audited action.`}
      onClose={resetDialogs} onSubmit={() => void runBulk()} busy={busy}
      submitLabel={bulkAction ? BULK_COPY[bulkAction] : 'Apply'} danger={bulkAction === 'lock' || bulkAction === 'force-password-change'} maxWidth="sm">
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Reason (recommended)" multiline minRows={2} value={notes} onChange={event => setNotes(event.target.value)}
          helperText="Stored once for the whole batch in the audit trail."/>
        <ErrorMessage message={dialogError}/>
      </Box>
    </FormDialog>

    {/* One-time code display */}
    <PanelDialog open={!!issued} title="One-time reset code" maxWidth="sm"
      subtitle={`Only shown now. Share it with ${issued?.email ?? 'the account holder'} through an approved secure channel.`}
      onClose={() => setIssued(null)}
      footer={<>
        <Button startIcon={<ContentCopyRounded/>} onClick={() => issued && void navigator.clipboard.writeText(issued.code)}>Copy code</Button>
        <Button variant="contained" onClick={() => setIssued(null)}>Done</Button>
      </>}>
      <Box display="grid" gap={2}>
        <TextField fullWidth value={issued?.code ?? ''} label="Single-use reset code" InputProps={{ readOnly: true }}
          helperText={issued ? `${issued.request} · expires ${new Date(issued.expires).toLocaleString()}` : ''}/>
        <Alert severity="warning">The account holder signs in, chooses “Forgot password?”, then “I already have an approved reset code”. Redeeming it signs out every existing session.</Alert>
      </Box>
    </PanelDialog>
  </>
}

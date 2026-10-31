import { useEffect, useState, type FormEvent } from 'react'
import { Alert, Box, Button, CircularProgress, Paper, TextField, Typography } from '@mui/material'
import { LockResetRounded } from '@mui/icons-material'
import { api, body } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { APP_NAME, pageTitle } from '../lib/appInfo'
import { ErrorMessage } from './Common'

// An administrator can require a new password (Security centre → Force password
// change). The API then refuses every other endpoint, so the whole application is
// replaced by this screen until the account holder sets one. It has no dismiss
// control by design — the only way on is to complete the change or sign out.
export default function PasswordChangeGate() {
  const { user, logout, passwordExpired } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => { document.title = pageTitle('Set a new password') }, [])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    if (newPassword !== confirmPassword) { setError('The new password and its confirmation do not match.'); return }
    setBusy(true)
    try {
      await api('/auth/change-password', {
        method: 'POST',
        body: body({ current_password: currentPassword, new_password: newPassword }),
        action: 'Set a new password',
      })
      setDone(true)
      // Every session was revoked by the change, so the only correct next step is a fresh sign-in.
      window.setTimeout(() => { void logout() }, 1600)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', bgcolor: 'background.default', px: 2, py: 6 }}>
    <Paper component="main" variant="outlined" sx={{ width: 'min(520px, 100%)', p: { xs: 3, sm: 4 }, borderRadius: 2 }}>
      <Box display="flex" alignItems="center" gap={1.5} mb={2.5}>
        <Box className="stat-icon" sx={{ color: 'warning.main', bgcolor: 'var(--wcp-tone-warning-bg)' }}><LockResetRounded sx={{ fontSize: 21 }}/></Box>
        <Box>
          <Typography className="eyebrow">ACCOUNT SECURITY · {APP_NAME}</Typography>
          <Typography fontWeight={800} fontSize={20} letterSpacing="-0.4px">Set a new password</Typography>
        </Box>
      </Box>
      <Typography color="text.secondary" fontSize={13} sx={{ mb: 2.5, lineHeight: 1.55 }}>
        {passwordExpired
          ? <>Your password reached its maximum age, so it must be replaced before you continue as{' '}</>
          : <>Your workspace administrator requires a new password before you continue as{' '}</>}
        <Box component="strong" sx={{ color: 'text.primary' }}>{user?.email}</Box>. All previous sessions were signed out.
      </Typography>
      {done ? <Alert severity="success">
        Password updated. You are being signed out so you can sign in with the new password.
      </Alert> : <Box component="form" onSubmit={submit} display="grid" gap={2}>
        <TextField label="Current password" type="password" required autoFocus autoComplete="current-password"
          value={currentPassword} onChange={event => setCurrentPassword(event.target.value)}/>
        <TextField label="New password" type="password" required autoComplete="new-password"
          helperText="12–128 characters, at least three of lowercase, uppercase, number and symbol. The last five passwords cannot be reused."
          value={newPassword} onChange={event => setNewPassword(event.target.value)}/>
        <TextField label="Confirm new password" type="password" required autoComplete="new-password"
          value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)}/>
        <ErrorMessage message={error}/>
        <Box display="flex" justifyContent="space-between" alignItems="center" gap={1.5} flexWrap="wrap" mt={.5}>
          <Button color="inherit" onClick={() => void logout()} disabled={busy}>Sign out</Button>
          <Button type="submit" variant="contained" disabled={busy || !currentPassword || !newPassword || !confirmPassword}
            startIcon={busy ? <CircularProgress size={14} color="inherit"/> : undefined}>
            {busy ? 'Updating…' : 'Update password'}
          </Button>
        </Box>
      </Box>}
    </Paper>
  </Box>
}

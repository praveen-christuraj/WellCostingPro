import { useEffect, useId, useState, type FormEvent } from 'react'
import { Alert, Box, Button, CircularProgress, IconButton, InputAdornment, TextField, Typography } from '@mui/material'
import { ArrowForwardRounded, VisibilityOffOutlined, VisibilityOutlined, LockOutlined, HubOutlined } from '@mui/icons-material'
import { useAuth } from '../context/AuthContext'
import Brand from '../components/Brand'
import { APP_NAME, pageTitle } from '../lib/appInfo'
import { api, body } from '../lib/api'
import { FormDialog } from '../components/Common'

export default function Login() {
  const { login } = useAuth()
  const orgField = useId()
  const emailField = useId()
  const passwordField = useId()
  const [organization, setOrganization] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [recovery, setRecovery] = useState<'request' | 'reset' | null>(null)
  const [reason, setReason] = useState('')
  const [resetCode, setResetCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [recoveryError, setRecoveryError] = useState('')
  const [recoveryMessage, setRecoveryMessage] = useState('')
  const [recoveryBusy, setRecoveryBusy] = useState(false)
  // A brand-new deployment has no owner yet, so say what to run instead of showing a dead sign-in form.
  const [unseeded, setUnseeded] = useState(false)
  // The tab carries the product name and its subtitle, not whatever page was open before sign-out.
  useEffect(() => { document.title = pageTitle() }, [])
  useEffect(() => { fetch('/api/health').then(r => r.json()).then(d => setUnseeded(d.admin_seeded === false)).catch(() => undefined) }, [])
  const submit = async (e: FormEvent) => { e.preventDefault(); setBusy(true); setError(''); try { await login(organization.trim().toLowerCase(), email.trim(), password) } catch (err) { setError(err instanceof Error ? err.message : 'Unable to sign in') } finally { setBusy(false) } }
  const requestReset = async () => {
    setRecoveryBusy(true); setRecoveryError('')
    try {
      const result = await api<{ message: string }>('/auth/forgot-password', { method: 'POST', body: body({ organization, email, reason }) })
      setRecoveryMessage(result.message); setRecovery(null); setReason('')
    } catch (err) { setRecoveryError((err as Error).message) } finally { setRecoveryBusy(false) }
  }
  const completeReset = async () => {
    setRecoveryBusy(true); setRecoveryError('')
    try {
      await api('/auth/reset-password', { method: 'POST', body: body({ organization, email, reset_code: resetCode, new_password: newPassword, confirm_password: confirmPassword }) })
      setRecoveryMessage('Password updated. Sign in with your new password.'); setRecovery(null); setResetCode(''); setNewPassword(''); setConfirmPassword('')
    } catch (err) { setRecoveryError((err as Error).message) } finally { setRecoveryBusy(false) }
  }
  return <Box className="login-shell">
    <Box className="login-story">
      <Box className="story-top">
        <Brand light/>
        <Typography sx={{ color: '#A7B8CB', fontSize: 12 }}>The operating system for well economics</Typography>
      </Box>
      <Box className="story-bg">
        <img src="/login-bg.svg" alt="Rig and well path illustration" className="login-bg-image"/>
      </Box>
      <Box className="story-main">
        <Box className="story-eyebrow">BUILT FOR THE WAY YOU WORK</Box>
        <Typography variant="h2" className="story-headline">Clarity at<br/>every <em>depth.</em></Typography>
        <Typography className="story-copy">A more intelligent way to manage well costing</Typography>
      </Box>
      <Box className="story-bottom">
        <Typography fontSize={11} color="#A7B8CB">© {new Date().getFullYear()} {APP_NAME}</Typography>
        <Box display="flex" alignItems="center" gap={1}>
          <HubOutlined sx={{ fontSize: 16, color: '#A7B8CB' }}/>
          <Typography fontSize={11} color="#A7B8CB">Built for connected teams</Typography>
        </Box>
      </Box>
    </Box>
    <Box className="login-form-side">
      <Box className="login-mobile-brand"><Brand/></Box>
      <Box className="login-form-wrap">
        <Box className="login-icon"><LockOutlined sx={{ fontSize: 24 }}/></Box>
        <Typography variant="h4" sx={{ fontSize: { xs: 28, sm: 32 }, letterSpacing: '-1.4px', mt: 3, mb: 1 }}>Welcome back</Typography>
        <Typography color="text.secondary" fontSize={14}>Sign in to continue.</Typography>
        {unseeded && <Alert severity="warning" sx={{ mt: 3, fontSize: 13 }}><strong>This deployment has no administrator yet.</strong> On the API host run <Box component="code" sx={{ fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>python -m app.seed</Box> to create the first workspace owner, then reload this page.</Alert>}
        <Box component="form" onSubmit={submit} sx={{ mt: 4.5 }}>
          <Typography component="label" htmlFor={orgField} className="field-label">WORKSPACE ID</Typography>
          <TextField id={orgField} name="organization" fullWidth required placeholder="e.g. acme-energy" value={organization} onChange={e => setOrganization(e.target.value)} autoComplete="organization" sx={{ mb: 2.5 }}/>
          <Typography component="label" htmlFor={emailField} className="field-label">WORK EMAIL</Typography>
          <TextField id={emailField} name="email" fullWidth required type="email" placeholder="name@company.com" value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" sx={{ mb: 2.5 }}/>
          <Typography component="label" htmlFor={passwordField} className="field-label">PASSWORD</Typography>
          <TextField id={passwordField} name="password" fullWidth required type={show ? 'text' : 'password'} placeholder="Enter your password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" InputProps={{ endAdornment: <InputAdornment position="end"><IconButton onClick={() => setShow(!show)} size="small" aria-label={show ? 'Hide password' : 'Show password'}>{show ? <VisibilityOffOutlined fontSize="small"/> : <VisibilityOutlined fontSize="small"/>}</IconButton></InputAdornment> }}/>
          <Box display="flex" justifyContent="space-between" alignItems="center" sx={{ mt: 1, mb: 3 }}>
            <Typography fontSize={12} color="text.secondary">Secure workspace sign-in</Typography>
            <Button size="small" variant="text" onClick={() => { setRecovery('request'); setRecoveryError('') }} sx={{ minWidth: 0, p: 0, fontSize: 12 }}>Forgot password?</Button>
          </Box>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          {recoveryMessage && <Alert severity="success" onClose={() => setRecoveryMessage('')} sx={{ mb: 2 }}>{recoveryMessage}</Alert>}
          <Button type="submit" fullWidth variant="contained" disabled={busy} sx={{ py: 1.55, fontSize: 14 }}>{busy ? <CircularProgress size={22} color="inherit"/> : <>Sign In <ArrowForwardRounded sx={{ ml: 1, fontSize: 18 }}/></>}</Button>
        </Box>
        <Box className="login-trust">
          <LockOutlined sx={{ color: 'primary.main', fontSize: 18 }}/>
          <Typography fontSize={12} color="text.secondary">Your workspace is protected with secure access controls.</Typography>
        </Box>
      </Box>
      <Typography className="login-help">Need help? Reach out to your workspace administrator.</Typography>
    </Box>
    {/* Both recovery pop-ups use the shared FormDialog, so they close only via Cancel
        and never discard a typed reason or password by a stray backdrop click. */}
    <FormDialog open={recovery === 'request'} title="Request a password reset" maxWidth="sm"
      subtitle="Your workspace administrator reviews every request. For privacy, the answer is the same whether or not the account exists."
      onClose={() => setRecovery(null)} onSubmit={() => void requestReset()} busy={recoveryBusy} submitLabel="Send request"
      submitDisabled={!organization.trim() || !email.trim()}>
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Workspace ID" required value={organization} onChange={e => setOrganization(e.target.value)}/>
        <TextField label="Work email" required type="email" value={email} onChange={e => setEmail(e.target.value)}/>
        <TextField label="Reason (optional)" multiline minRows={2} value={reason} onChange={e => setReason(e.target.value)}
          helperText="Tell the administrator how you lost access. This is recorded with the request."/>
        {recoveryError && <Alert severity="error">{recoveryError}</Alert>}
        <Button variant="text" sx={{ justifySelf: 'start' }} onClick={() => { setRecovery('reset'); setRecoveryError('') }}>I already have an approved reset code</Button>
      </Box>
    </FormDialog>
    <FormDialog open={recovery === 'reset'} title="Use an approved reset code" maxWidth="sm"
      subtitle="Enter the single-use code supplied by your workspace administrator, then choose a new password."
      onClose={() => setRecovery(null)} onSubmit={() => void completeReset()} busy={recoveryBusy} submitLabel="Reset password"
      submitDisabled={!resetCode || !newPassword || !confirmPassword}>
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Workspace ID" required value={organization} onChange={e => setOrganization(e.target.value)}/>
        <TextField label="Work email" required type="email" value={email} onChange={e => setEmail(e.target.value)}/>
        <TextField label="Reset code" required value={resetCode} onChange={e => setResetCode(e.target.value)}/>
        <TextField label="New password" required type="password" autoComplete="new-password"
          helperText="12–128 characters; use at least three of uppercase, lowercase, number and symbol. The last five passwords cannot be reused."
          value={newPassword} onChange={e => setNewPassword(e.target.value)}/>
        <TextField label="Confirm new password" required type="password" autoComplete="new-password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)}/>
        {recoveryError && <Alert severity="error">{recoveryError}</Alert>}
      </Box>
    </FormDialog>
  </Box>
}

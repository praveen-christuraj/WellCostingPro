import { type ReactNode, useEffect, useId, useRef, useState } from 'react'
import { Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Typography } from '@mui/material'
import { useBlocker } from 'react-router-dom'
import { ErrorOutlineRounded } from '@mui/icons-material'

// Page header: eyebrow (where you are) → title (what this is) → subtitle (what to do).
export function PageHeading({ eyebrow, title, subtitle, action }: { eyebrow: string; title: string; subtitle: string; action?: ReactNode }) {
  return <Box component="header" display="flex" justifyContent="space-between" alignItems="flex-end" gap={2} rowGap={1.5} flexWrap="wrap" sx={{ mb: 3.5 }}>
    <Box minWidth={0}>
      <Typography className="eyebrow">{eyebrow}</Typography>
      <Typography variant="h4" sx={{ fontSize: { xs: 25, sm: 30 }, letterSpacing: '-1.1px', mt: .5 }}>{title}</Typography>
      <Typography color="text.secondary" fontSize={13} sx={{ mt: .8, maxWidth: 760, lineHeight: 1.5 }}>{subtitle}</Typography>
    </Box>
    {action ? <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" sx={{ pb: .5 }}>{action}</Box> : null}
  </Box>
}

/**
 * Status chip. Colours come from the `--wcp-tone-*` custom properties in
 * `styles.css`, which follow `data-theme`; they resolve without a React theme
 * context so chips keep their colours inside AG Grid cell renderers too.
 */
export type Tone = 'neutral' | 'success' | 'info' | 'warning' | 'error'
export function Tag({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return <Chip label={children} size="small" sx={{
    bgcolor: `var(--wcp-tone-${tone}-bg)`,
    color: `var(--wcp-tone-${tone}-fg)`,
    border: '1px solid',
    borderColor: `var(--wcp-tone-${tone}-border)`,
    height: 24,
    fontSize: 11,
    fontWeight: 700,
  }}/>
}

// ---------------------------------------------------------------------------
// Unsaved-changes protection (Standing product convention 15).
//
// A data-entry pop-up never silently throws away what the user typed. When a
// dialog that has received input is closed via Cancel, it first asks:
// "Save & close" (runs the normal save path), "Discard changes", or
// "Continue editing". The same protection applies to full-page editors, which
// use `useUnsavedChangesGuard` below to intercept in-app navigation, the back
// button, and the browser tab closing/reloading.
// ---------------------------------------------------------------------------

// Standard pop-up rule: a data-entry pop-up closes ONLY via its Cancel button (or after a successful save/import).
// Backdrop clicks and the Escape key are deliberately ignored, so no onClose is passed to the MUI Dialog.
// `danger` marks the irreversible actions (permanent delete, purge) in the primary button colour.
export function FormDialog({ open, title, subtitle, onClose, onSubmit, busy, busyLabel, children, submitLabel = 'Save changes', maxWidth = 'sm', submitDisabled = false, danger = false, dirty }: {
  open: boolean
  title: string
  subtitle?: string
  onClose: () => void
  onSubmit: () => void
  busy?: boolean
  busyLabel?: string
  children: ReactNode
  submitLabel?: string
  maxWidth?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  submitDisabled?: boolean
  danger?: boolean
  /** Precise unsaved-data flag from the page. When omitted, any user input inside the dialog marks it dirty. */
  dirty?: boolean
}) {
  const titleId = useId()
  const subtitleId = useId()
  const [typed, setTyped] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const confirmTitleId = useId()
  const confirmBodyId = useId()

  // Any interaction with the fields (typing, choosing an option, toggling a
  // button group) marks the dialog dirty, so nothing entered is ever lost to a
  // stray Cancel click. Pages can pass an exact `dirty` instead.
  useEffect(() => {
    if (open) return
    setTyped(false)
    setConfirmOpen(false)
  }, [open])

  const markDirty = () => setTyped(true)
  const isDirty = dirty ?? typed

  // Cancel keeps the data: with input present it first asks whether to save it.
  const requestClose = () => {
    if (isDirty && !busy) setConfirmOpen(true)
    else onClose()
  }

  return <Dialog open={open} disableEscapeKeyDown fullWidth maxWidth={maxWidth} aria-labelledby={titleId} aria-describedby={subtitle ? subtitleId : undefined}>
    {/* DialogTitle renders as an <h2> and takes the id from the Dialog's aria-labelledby, so the
        heading holds the title only; the subtitle is a paragraph the dialog points at with
        aria-describedby. That keeps one accessible name and no duplicated ids. */}
    <DialogTitle sx={{ px: 3, pt: 3, pb: subtitle ? 1 : 2 }}>
      <Box component="span" sx={{ display: 'block', fontSize: 19, fontWeight: 800, letterSpacing: '-.3px', lineHeight: 1.3 }}>{title}</Box>
    </DialogTitle>
    <DialogContent sx={{ px: 3, pt: subtitle ? 0 : '20px !important' }}>
      {subtitle && <Box component="p" id={subtitleId} sx={{ m: 0, mb: 2.5, fontSize: 12.5, color: 'text.secondary', lineHeight: 1.5 }}>{subtitle}</Box>}
      <Box onChangeCapture={markDirty} onInputCapture={markDirty}
        onClickCapture={event => {
          const target = event.target as HTMLElement | null
          // MUI Select / Autocomplete options and toggle buttons announce their
          // changes through clicks, not input events.
          if (target?.closest('[role="option"], [aria-pressed]')) markDirty()
        }}>
        {children}
      </Box>
    </DialogContent>
    <DialogActions sx={{ px: 3, py: 1.75, gap: 1, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.default' }}>
      <Button onClick={requestClose} color="inherit">Cancel</Button>
      <Button
        onClick={onSubmit}
        variant="contained"
        color={danger ? 'error' : 'primary'}
        disabled={busy || submitDisabled}
        startIcon={busy ? <CircularProgress size={14} color="inherit"/> : undefined}
      >{busy ? busyLabel ?? 'Saving...' : submitLabel}</Button>
    </DialogActions>

    {/* The unsaved-changes prompt. "Save & close" reuses the dialog's own save
        path — a successful save closes the form, a validation problem keeps it
        open with the messages next to the fields. */}
    <Dialog open={confirmOpen} disableEscapeKeyDown maxWidth="xs" fullWidth aria-labelledby={confirmTitleId} aria-describedby={confirmBodyId}>
      <DialogTitle sx={{ px: 3, pt: 3, pb: 1 }}>
        <Box component="span" sx={{ display: 'block', fontSize: 19, fontWeight: 800, letterSpacing: '-.3px', lineHeight: 1.3 }}>Save the data you entered?</Box>
      </DialogTitle>
      <DialogContent sx={{ px: 3, pt: 0 }}>
        <Box component="p" id={confirmBodyId} sx={{ m: 0, fontSize: 13, color: 'text.secondary', lineHeight: 1.55 }}>
          This pop-up has unsaved input. Closing it now loses everything you typed. Save it before closing, or discard it deliberately.
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 1.75, gap: 1, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.default', flexWrap: 'wrap' }}>
        <Button onClick={() => setConfirmOpen(false)} color="inherit" disabled={busy}>Continue editing</Button>
        <Button onClick={() => { setConfirmOpen(false); onClose() }} color="error" disabled={busy}>Discard changes</Button>
        <Button onClick={() => { setConfirmOpen(false); onSubmit() }} variant="contained" disabled={busy || submitDisabled}>{submitLabel}</Button>
      </DialogActions>
    </Dialog>
  </Dialog>
}

/**
 * Precise unsaved-data flag for dialogs whose form state lives in the parent
 * (or arrives as a prop): compares the live form against what it was when the
 * dialog opened. Pass the result as FormDialog's `dirty` prop.
 */
export function useFormDirty(form: unknown, open: boolean): boolean {
  const baseline = useRef<unknown>(form)
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    if (open) {
      baseline.current = form
      setDirty(false)
    }
    // The baseline is captured once per open; later form changes are edits, not baselines.
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (open) setDirty(JSON.stringify(form) !== JSON.stringify(baseline.current))
  }, [form, open])
  return dirty
}

/**
 * Page-level unsaved-changes guard for full-page editors (AFE estimate, daily
 * cost sheet, and future entry pages). While `when` is true it:
 *   - asks before any in-app navigation or the browser back button,
 *   - asks before the tab is closed or reloaded,
 * with "Save & continue" (the page's own save), "Discard changes" and
 * "Continue editing". Render the returned node anywhere in the page.
 */
export function useUnsavedChangesGuard({ when, onSave, title = 'Leave with unsaved changes?', message }: {
  when: boolean
  /** Try to save. Return true when saved (navigation continues), false to stay. */
  onSave?: () => Promise<boolean> | boolean
  title?: string
  message?: string
}): ReactNode {
  const titleId = useId()
  const [busy, setBusy] = useState(false)
  const blocker = useBlocker(when)

  useEffect(() => {
    if (!when) return
    const handler = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [when])

  // Drop the prompt if the guard deactivates while it is open (e.g. the page saved).
  useEffect(() => {
    if (!when && blocker.state === 'blocked') blocker.reset()
  }, [when, blocker])

  if (blocker.state !== 'blocked') return null

  const discard = () => blocker.proceed()
  const saveAndContinue = async () => {
    if (!onSave) { blocker.proceed(); return }
    setBusy(true)
    try {
      if (await onSave()) blocker.proceed()
      else blocker.reset()
    } catch {
      blocker.reset()
    } finally {
      setBusy(false)
    }
  }

  return <Dialog open disableEscapeKeyDown maxWidth="xs" fullWidth aria-labelledby={titleId}>
    <DialogTitle sx={{ px: 3, pt: 3, pb: 1 }}>
      <Box component="span" sx={{ display: 'block', fontSize: 19, fontWeight: 800, letterSpacing: '-.3px', lineHeight: 1.3 }}>{title}</Box>
    </DialogTitle>
    <DialogContent sx={{ px: 3, pt: 0 }}>
      <Box component="p" id={titleId} sx={{ m: 0, fontSize: 13, color: 'text.secondary', lineHeight: 1.55 }}>
        {message ?? 'This page has data that is not saved yet. Leaving now loses it. Save it before leaving, or discard it deliberately.'}
      </Box>
    </DialogContent>
    <DialogActions sx={{ px: 3, py: 1.75, gap: 1, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.default', flexWrap: 'wrap' }}>
      <Button onClick={() => blocker.reset()} color="inherit" disabled={busy}>Continue editing</Button>
      <Button onClick={discard} color="error" disabled={busy}>Discard changes</Button>
      {onSave && <Button onClick={() => void saveAndContinue()} variant="contained" disabled={busy}
        startIcon={busy ? <CircularProgress size={14} color="inherit"/> : undefined}>{busy ? 'Saving...' : 'Save & continue'}</Button>}
    </DialogActions>
  </Dialog>
}

// Error text stays next to the field or the action that caused it, never in a global banner.
export function ErrorMessage({ message }: { message: string }) {
  if (!message) return null
  return <Box role="alert" display="flex" alignItems="flex-start" gap={.8} sx={{ mt: 1.5 }}>
    <ErrorOutlineRounded sx={{ fontSize: 15, color: 'error.main', mt: '1px', flex: 'none' }}/>
    <Typography color="error" fontSize={12} sx={{ lineHeight: 1.45 }}>{message}</Typography>
  </Box>
}

// Same rule as FormDialog for panels that are not a single submit form (attachments,
// revision history): no backdrop or Escape close, no close icon, footer button only.
export function PanelDialog({ open, title, subtitle, onClose, footer, children, maxWidth = 'md' }: { open: boolean; title: string; subtitle?: string; onClose: () => void; footer?: ReactNode; children: ReactNode; maxWidth?: 'sm' | 'md' | 'lg' }) {
  const titleId = useId()
  const subtitleId = useId()
  return <Dialog open={open} disableEscapeKeyDown fullWidth maxWidth={maxWidth} aria-labelledby={titleId} aria-describedby={subtitle ? subtitleId : undefined}>
    {/* MUI renders DialogTitle as an <h2>; the title and subtitle are spans inside it so the
        heading is not nested inside another heading. */}
    <DialogTitle sx={{ px: 3, pt: 3, pb: subtitle ? 1 : 2 }}>
      <Box component="span" sx={{ display: 'block', fontSize: 19, fontWeight: 800, letterSpacing: '-.3px', lineHeight: 1.3 }}>{title}</Box>
    </DialogTitle>
    <DialogContent sx={{ px: 3, pt: subtitle ? 0 : '16px !important' }}>
      {subtitle && <Box component="p" id={subtitleId} sx={{ m: 0, mb: 2, fontSize: 12.5, color: 'text.secondary', lineHeight: 1.5 }}>{subtitle}</Box>}
      {children}
    </DialogContent>
    <DialogActions sx={{ px: 3, py: 1.75, gap: 1, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.default' }}>{footer ?? <Button onClick={onClose} color="inherit">Close</Button>}</DialogActions>
  </Dialog>
}

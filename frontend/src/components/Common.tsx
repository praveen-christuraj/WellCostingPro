import { type ReactNode, useId } from 'react'
import { Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Typography } from '@mui/material'
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

// Standard pop-up rule: a data-entry pop-up closes ONLY via its Cancel button (or after a successful save/import).
// Backdrop clicks and the Escape key are deliberately ignored, so no onClose is passed to the MUI Dialog.
// `danger` marks the irreversible actions (permanent delete, purge) in the primary button colour.
export function FormDialog({ open, title, subtitle, onClose, onSubmit, busy, busyLabel, children, submitLabel = 'Save changes', maxWidth = 'sm', submitDisabled = false, danger = false }: {
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
}) {
  const titleId = useId()
  const subtitleId = useId()
  return <Dialog open={open} disableEscapeKeyDown fullWidth maxWidth={maxWidth} aria-labelledby={titleId} aria-describedby={subtitle ? subtitleId : undefined}>
    {/* DialogTitle renders as an <h2> and takes the id from the Dialog's aria-labelledby, so the
        heading holds the title only; the subtitle is a paragraph the dialog points at with
        aria-describedby. That keeps one accessible name and no duplicated ids. */}
    <DialogTitle sx={{ px: 3, pt: 3, pb: subtitle ? 1 : 2 }}>
      <Box component="span" sx={{ display: 'block', fontSize: 19, fontWeight: 800, letterSpacing: '-.3px', lineHeight: 1.3 }}>{title}</Box>
    </DialogTitle>
    <DialogContent sx={{ px: 3, pt: subtitle ? 0 : '20px !important' }}>
      {subtitle && <Box component="p" id={subtitleId} sx={{ m: 0, mb: 2.5, fontSize: 12.5, color: 'text.secondary', lineHeight: 1.5 }}>{subtitle}</Box>}
      {children}
    </DialogContent>
    <DialogActions sx={{ px: 3, py: 1.75, gap: 1, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.default' }}>
      <Button onClick={onClose} color="inherit">Cancel</Button>
      <Button
        onClick={onSubmit}
        variant="contained"
        color={danger ? 'error' : 'primary'}
        disabled={busy || submitDisabled}
        startIcon={busy ? <CircularProgress size={14} color="inherit"/> : undefined}
      >{busy ? busyLabel ?? 'Saving...' : submitLabel}</Button>
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

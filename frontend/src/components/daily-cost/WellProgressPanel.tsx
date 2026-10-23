import { useEffect, useMemo, useState, type MutableRefObject } from 'react'
import { SaveOutlined } from '@mui/icons-material'
import { Alert, Box, Button, Paper, TextField, Typography } from '@mui/material'
import { Tag } from '../Common'
import { api, body } from '../../lib/api'
import type { WellProgressReport, WellProgressScope } from '../../lib/dailyCost'

/** datetime-local inputs work with `YYYY-MM-DDTHH:mm`; the API stores seconds. */
const toInput = (value: string | null) => (value ? value.slice(0, 16) : '')
const fromInput = (value: string) => (value ? `${value}:00` : null)

const formatDays = (value: string | null) =>
  value === null ? '—' : Number(value).toFixed(3)

type ScopeDraft = { spud: string; completed: string; label: string }

function draftFor(scope: WellProgressScope): ScopeDraft {
  return {
    spud: toInput(scope.spud_at),
    completed: toInput(scope.progress_completed_at),
    label: scope.milestone_label ?? '',
  }
}

function signature(scopes: WellProgressScope[]): string {
  return scopes.map(scope => {
    const draft = draftFor(scope)
    return `${scope.scope}:${draft.spud}:${draft.completed}:${draft.label}`
  }).join('|')
}

/**
 * The daily cost register's progress entry: Well Spud Date & Time and
 * Progress Completed Date & Time per configuration scope, with the actual
 * days they drive. The spud date can only be edited once entered, never
 * cleared, and entering the progress completion stops the day count.
 */
export function WellProgressPanel({ wellId, scopes, canEdit, onSaved, asOfLabel, asOfDate, onDirtyChange, saveRef }: {
  wellId: string
  scopes: WellProgressScope[]
  canEdit: boolean
  onSaved: (report: WellProgressReport) => void
  /** Where the actual-day count points, e.g. "the sheet date" or "the last cost sheet date". */
  asOfLabel?: string
  /** Explicit report endpoint used after saving from a dated sheet. */
  asOfDate?: string
  /** Lets the host page fold these edits into its unsaved-changes guard. */
  onDirtyChange?: (dirty: boolean) => void
  saveRef?: MutableRefObject<(() => Promise<boolean>) | null>
}) {
  const incoming = useMemo(() => signature(scopes), [scopes])
  const [drafts, setDrafts] = useState<Record<string, ScopeDraft>>(
    () => Object.fromEntries(scopes.map(scope => [scope.scope, draftFor(scope)])),
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Adopt server values only while the panel has no unsaved edits of its own.
  useEffect(() => {
    setDrafts(current => {
      const untouched = scopes.every(scope => {
        const draft = current[scope.scope]
        return !draft || (
          draft.spud === toInput(scope.spud_at) && draft.completed === toInput(scope.progress_completed_at)
          && draft.label === (scope.milestone_label ?? '')
        )
      })
      if (!untouched) return current
      return Object.fromEntries(scopes.map(scope => [scope.scope, draftFor(scope)]))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incoming])

  const dirtyScopes = scopes.filter(scope => {
    const draft = drafts[scope.scope]
    if (!draft) return false
    return draft.spud !== toInput(scope.spud_at)
      || draft.completed !== toInput(scope.progress_completed_at)
      || draft.label !== (scope.milestone_label ?? '')
  })
  const dirty = dirtyScopes.length > 0

  useEffect(() => { onDirtyChange?.(dirty) }, [dirty, onDirtyChange])

  const setDraft = (scope: string, patch: Partial<ScopeDraft>) => {
    setDrafts(current => ({ ...current, [scope]: { ...current[scope], ...patch } }))
    setError('')
  }

  const save = async (): Promise<boolean> => {
    if (!dirtyScopes.length) return true
    setBusy(true)
    setError('')
    let report: WellProgressReport | null = null
    try {
      for (const scope of dirtyScopes) {
        const draft = drafts[scope.scope]
        const payload: Record<string, unknown> = { scope: scope.scope }
        if (draft.spud !== toInput(scope.spud_at)) payload.spud_at = fromInput(draft.spud)
        if (draft.completed !== toInput(scope.progress_completed_at)) payload.progress_completed_at = fromInput(draft.completed)
        // The printed milestone wording is saved once here, not typed at print time.
        if (draft.label !== (scope.milestone_label ?? '')) payload.milestone_label = draft.label
        const query = asOfDate ? `?as_of=${encodeURIComponent(asOfDate)}` : ''
        report = await api<WellProgressReport>(`/daily-cost/wells/${wellId}/progress${query}`, {
          method: 'PUT', body: body(payload),
        })
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The well progress milestones could not be saved')
      return false
    } finally {
      setBusy(false)
    }
    if (report) onSaved(report)
    return true
  }
  useEffect(() => { if (saveRef) saveRef.current = save })

  return <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, mb: 1.6 }}>
    <Box display="flex" justifyContent="space-between" alignItems="center" gap={1.5} flexWrap="wrap">
      <Box>
        <Typography fontWeight={800} fontSize={14}>Well progress — spud to completion</Typography>
        <Typography color="text.secondary" fontSize={11.2} mt={.25}>
          Actual days count from the Well Spud Date &amp; Time — not from the first daily cost sheet —
          to the end of {asOfLabel ?? 'the last cost sheet date'}{asOfLabel ? '' : ' (0.583 days for a well spudded at 10:00 hrs on that date)'}.
          Entering the Progress Completed Date &amp; Time ends the whole progress and stops the count.
          The milestone label is the wording printed on every cost report for this well, so it is typed once here.
        </Typography>
      </Box>
      {canEdit && <Button
        size="small" variant="contained" startIcon={<SaveOutlined/>}
        onClick={() => void save()} disabled={!dirty || busy}
      >{busy ? 'Saving…' : 'Save progress & label'}</Button>}
    </Box>

    <Box display="grid" gap={1.4} mt={1.5}>
      {scopes.map(scope => {
        const draft = drafts[scope.scope] ?? draftFor(scope)
        const over = scope.days_variance !== null && Number(scope.days_variance) > 0
        const under = scope.days_variance !== null && Number(scope.days_variance) < 0
        return <Box key={scope.scope} sx={{ p: 1.3, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
          <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap">
            <Typography fontSize={12.5} fontWeight={800}>{scope.scope_label} progress</Typography>
            <Tag tone={scope.is_completed ? 'success' : scope.spud_at ? 'info' : 'neutral'}>
              {scope.is_completed ? 'Completed — count stopped' : scope.spud_at ? 'Counting days' : 'Not spudded yet'}
            </Tag>
          </Box>
          <TextField
            size="small" fullWidth label="Milestone label printed on the report"
            value={draft.label} disabled={!canEdit || busy}
            onChange={event => setDraft(scope.scope, { label: event.target.value })}
            placeholder="Spud date & time"
            inputProps={{ maxLength: 80 }}
            helperText="Saved once for this well and scope. Leave empty to print “Spud date & time”; edit it whenever the milestone wording changes."
            sx={{ mt: 1.1 }}
          />
          <Box display="grid" gap={1.2} mt={1.1} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(5, 1fr)' } }}>
            <TextField
              size="small" type="datetime-local" label="Well Spud Date & Time"
              value={draft.spud} disabled={!canEdit || busy}
              onChange={event => setDraft(scope.scope, { spud: event.target.value })}
              InputLabelProps={{ shrink: true }}
              helperText={scope.spud_at ? 'Entered — edit to recalculate the days; it cannot be cleared.' : 'The instant this progress started counting.'}
            />
            <TextField
              size="small" type="datetime-local" label="Progress Completed Date & Time"
              value={draft.completed} disabled={!canEdit || busy}
              onChange={event => setDraft(scope.scope, { completed: event.target.value })}
              InputLabelProps={{ shrink: true }}
              helperText={`${scope.progress_label} — leave empty while the progress runs.`}
            />
            <Paper variant="outlined" sx={{ p: 1.1, borderRadius: 1.5, display: 'grid', alignContent: 'center' }}>
              <Typography fontSize={10} fontWeight={800} letterSpacing={.6} color="text.secondary">ACTUAL DAYS</Typography>
              <Typography fontSize={17} fontWeight={800}>{formatDays(scope.actual_days)}</Typography>
              <Typography fontSize={10.2} color="text.secondary">
                {scope.spud_at
                  ? (scope.is_completed ? 'spud → completion' : scope.as_of_date ? `to end of ${scope.as_of_date}` : 'no cost sheet yet')
                  : 'enter the spud date & time'}
              </Typography>
            </Paper>
            <Paper variant="outlined" sx={{ p: 1.1, borderRadius: 1.5, display: 'grid', alignContent: 'center' }}>
              <Typography fontSize={10} fontWeight={800} letterSpacing={.6} color="text.secondary">PLANNED DAYS</Typography>
              <Typography fontSize={17} fontWeight={800}>{Number(scope.planned_days).toFixed(3)}</Typography>
              <Typography fontSize={10.2} color="text.secondary">{scope.scope_label.toLowerCase()} plan for this scope</Typography>
            </Paper>
            <Paper variant="outlined" sx={{ p: 1.1, borderRadius: 1.5, display: 'grid', alignContent: 'center' }}>
              <Typography fontSize={10} fontWeight={800} letterSpacing={.6} color="text.secondary">DIFFERENCE</Typography>
              <Typography fontSize={17} fontWeight={800} sx={{ color: scope.days_variance === null ? 'text.primary' : over ? 'error.main' : under ? 'success.main' : 'text.primary' }}>
                {scope.days_variance === null ? '—' : `${over ? '+' : ''}${Number(scope.days_variance).toFixed(3)}`}
              </Typography>
              <Typography fontSize={10.2} color="text.secondary">actual − planned days</Typography>
            </Paper>
          </Box>
        </Box>
      })}
    </Box>
    {error && <Alert severity="error" sx={{ mt: 1.3 }}>{error}</Alert>}
  </Paper>
}

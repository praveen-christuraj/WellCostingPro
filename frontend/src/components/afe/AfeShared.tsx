import { useEffect, useState } from 'react'
import { Alert, Box, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog, Tag } from '../Common'
import { ApiError, api, body } from '../../lib/api'
import { STATUS_ACTIONS, STATUS_LABEL, STATUS_TONE, remarksProblem, type Afe, type AfeStatus, type AfeStatusAction } from '../../lib/afe'

export function StatusTag({ status }: { status: AfeStatus }) {
  return <Tag tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Tag>
}

// Shows one message, or a bulleted list when the server returned several problems.
export function ErrorDetails({ error, title }: { error: unknown; title?: string }) {
  if (!error) return null
  const details = error instanceof ApiError ? error.details : []
  const message = error instanceof Error ? error.message : 'The request could not be completed.'
  if (details.length > 1) {
    return <Alert severity="error" sx={{ mb: 1.5 }}>
      <Typography fontWeight={700} fontSize={13}>{title ?? 'Fix these issues and try again:'}</Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.2, mt: .6 }}>
        {details.map((detail, index) => <li key={`${index}-${detail}`}><Typography fontSize={12.5}>{detail}</Typography></li>)}
      </Box>
    </Alert>
  }
  return <Alert severity="error" sx={{ mb: 1.5 }}>{message}</Alert>
}

export function StatusDialog({ afe, action, onClose, onDone }: {
  afe: Afe | null
  action: AfeStatusAction | null
  onClose: () => void
  onDone: (updated: Afe, action: AfeStatusAction) => void
}) {
  const [remarks, setRemarks] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setRemarks('')
    setError('')
  }, [afe?.id, action])

  if (!afe || !action) return null
  const copy = STATUS_ACTIONS[action]
  const problem = remarksProblem(action, remarks)

  const submit = async () => {
    setBusy(true)
    setError('')
    try {
      const updated = await api<Afe>(`/afe/afes/${afe.id}/status`, { method: 'POST', body: body({ action, remarks: remarks.trim() }) })
      onDone(updated, action)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The AFE status could not be changed')
    } finally {
      setBusy(false)
    }
  }

  return <FormDialog
    open
    title={copy.title}
    subtitle={`${afe.afe_code} · ${afe.afe_name}. ${copy.description}`}
    onClose={() => { if (!busy) onClose() }}
    onSubmit={() => void submit()}
    busy={busy}
    submitLabel={copy.label}
    submitDisabled={Boolean(problem)}
  >
    <Box display="flex" flexDirection="column" gap={1.6}>
      <Box display="flex" alignItems="center" gap={1}>
        <StatusTag status={afe.status}/>
        <Typography fontSize={12} color="text.secondary">→</Typography>
        <StatusTag status={copy.to}/>
      </Box>
      <TextField
        label={copy.remarksRequired ? 'Remarks (required)' : 'Remarks (optional)'}
        value={remarks}
        onChange={event => setRemarks(event.target.value)}
        multiline
        minRows={2}
        fullWidth
        inputProps={{ maxLength: 500 }}
        helperText={copy.remarksRequired ? (remarks.trim() ? problem || 'Recorded in the audit trail.' : 'At least 3 characters.') : 'Recorded in the audit trail.'}
        error={Boolean(remarks) && Boolean(problem)}
      />
      <ErrorMessage message={error}/>
    </Box>
  </FormDialog>
}

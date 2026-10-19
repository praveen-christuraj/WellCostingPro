import { useEffect, useState } from 'react'
import { Alert, Box, Button, CircularProgress, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog, PanelDialog, Tag } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { api } from '../../lib/api'
import { amountText, type Afe } from '../../lib/afe'
import {
  SOW_STATUS_LABEL, SOW_STATUS_TONE, adjustmentDeltaText, approveAfeAdjustment, createAfeAdjustment,
  listAfeAdjustments, updateAfeAdjustment, voidAfeAdjustment, type AfeSowAdjustment,
} from '../../lib/sowAdjustment'

type Decision = { adjustment: AfeSowAdjustment; action: 'approve' | 'void' } | null

function emptyForm(afe: Afe) {
  return {
    reason: '',
    sow_summary: '',
    adjusted_services_total: afe.services_total ?? '0',
    adjusted_consumables_total: afe.consumables_total ?? '0',
    adjusted_tangibles_total: afe.tangibles_total ?? '0',
  }
}

export function SowAdjustmentDialog({ open, afe, onClose, onChanged }: {
  open: boolean
  afe: Afe
  onClose: () => void
  onChanged: (updated: Afe) => void
}) {
  const { can } = useAuth()
  const canAdjust = can('afe:sow-adjust')
  const canDecide = can('afe:sow-approve')
  const [adjustments, setAdjustments] = useState<AfeSowAdjustment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [form, setForm] = useState(emptyForm(afe))
  const [editingId, setEditingId] = useState<string | null>(null)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [decision, setDecision] = useState<Decision>(null)
  const [remarks, setRemarks] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [deciding, setDeciding] = useState(false)

  const estimateReady = afe.estimate_saved_at != null && !afe.conversion_pending && afe.total_cost != null
  const openDraft = adjustments.find(item => item.status === 'draft' && item.id !== editingId) ?? null

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      setAdjustments(await listAfeAdjustments(afe.id))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'SOW adjustments could not be loaded')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    setForm(emptyForm(afe))
    setEditingId(null)
    setFormError('')
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, afe.id])

  const refreshAfe = async () => {
    try {
      onChanged(await api<Afe>(`/afe/afes/${afe.id}`))
    } catch {
      // The list already shows the new revision; the header refresh is best-effort.
    }
  }

  const startEdit = (adjustment: AfeSowAdjustment) => {
    setEditingId(adjustment.id)
    setForm({
      reason: adjustment.reason,
      sow_summary: adjustment.sow_summary,
      adjusted_services_total: adjustment.adjusted_services_total,
      adjusted_consumables_total: adjustment.adjusted_consumables_total,
      adjusted_tangibles_total: adjustment.adjusted_tangibles_total,
    })
    setFormError('')
  }

  const cancelEdit = () => {
    setEditingId(null)
    setForm(emptyForm(afe))
    setFormError('')
  }

  const submitForm = async () => {
    setSaving(true)
    setFormError('')
    try {
      if (editingId) await updateAfeAdjustment(editingId, form)
      else await createAfeAdjustment(afe.id, form)
      cancelEdit()
      await load()
      await refreshAfe()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'The adjustment could not be saved')
    } finally {
      setSaving(false)
    }
  }

  const submitDecision = async () => {
    if (!decision) return
    setDeciding(true)
    setDecisionError('')
    try {
      if (decision.action === 'approve') await approveAfeAdjustment(decision.adjustment.id, remarks.trim())
      else await voidAfeAdjustment(decision.adjustment.id, remarks.trim())
      setDecision(null)
      setRemarks('')
      await load()
      await refreshAfe()
    } catch (caught) {
      setDecisionError(caught instanceof Error ? caught.message : 'The decision could not be recorded')
    } finally {
      setDeciding(false)
    }
  }

  const adjustedSum = [form.adjusted_services_total, form.adjusted_consumables_total, form.adjusted_tangibles_total]
    .reduce((sum, value) => sum + (Number(value) || 0), 0)
  const formBlocked = !form.reason.trim() || openDraft != null && editingId == null
    ? 'Enter the reason first.'
    : ''

  return <>
    <PanelDialog
      open={open && decision == null}
      title={`SOW adjustments · ${afe.afe_code}`}
      subtitle={`Revisions to the approved estimate live here — the saved estimate itself never changes. Only the latest approved revision affects cost comparisons. Amounts in ${afe.standard_currency}.`}
      onClose={onClose}
      maxWidth="md"
      footer={<Button variant="outlined" onClick={onClose}>Close</Button>}
    >
      <Box display="grid" gap={2}>
        <Alert severity="info">
          Original approved total {amountText(afe.total_cost, afe.standard_currency)}
          {' '}· Services {amountText(afe.services_total)} · Consumables {amountText(afe.consumables_total)} · Tangibles {amountText(afe.tangibles_total)}
          {afe.has_sow_adjustment && afe.adjusted_total != null && <> · Effective (Rev {afe.sow_revision}) {amountText(afe.adjusted_total, afe.standard_currency)}</>}
        </Alert>
        <ErrorMessage message={error}/>
        {loading
          ? <Box py={4} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
          : <>
            {!estimateReady && <Alert severity="warning">Save the estimate with all conversion rates before recording an adjustment — the original totals must be convertible.</Alert>}
            {canAdjust && estimateReady && <Box sx={{ p: 1.8, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
              <Typography fontWeight={800} fontSize={14} mb={.3}>{editingId ? 'Edit draft revision' : 'New adjustment draft'}</Typography>
              <Typography color="text.secondary" fontSize={12} mb={1.5}>
                {editingId
                  ? 'Only draft revisions can be edited. Approving a revision locks it.'
                  : openDraft
                    ? `Revision ${openDraft.revision_number} is still a draft. Approve or void it before starting another.`
                    : 'Prefilled with the current totals — change only the groups the scope change affects.'}
              </Typography>
              <Box display="grid" gap={1.5}>
                <TextField label="Reason" required fullWidth value={form.reason} onChange={event => setForm({ ...form, reason: event.target.value })} inputProps={{ maxLength: 1000 }} helperText="Why the scope changed — recorded permanently with the revision."/>
                <TextField label="Scope summary" fullWidth multiline minRows={2} value={form.sow_summary} onChange={event => setForm({ ...form, sow_summary: event.target.value })} inputProps={{ maxLength: 4000 }} helperText="What was added or removed: services, consumables, tangibles, days."/>
                <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: 'repeat(3, 1fr)' }} gap={1.5}>
                  <TextField label={`Adjusted services (${afe.standard_currency})`} required fullWidth value={form.adjusted_services_total} onChange={event => setForm({ ...form, adjusted_services_total: event.target.value })} inputProps={{ inputMode: 'decimal' }}/>
                  <TextField label={`Adjusted consumables (${afe.standard_currency})`} required fullWidth value={form.adjusted_consumables_total} onChange={event => setForm({ ...form, adjusted_consumables_total: event.target.value })} inputProps={{ inputMode: 'decimal' }}/>
                  <TextField label={`Adjusted tangibles (${afe.standard_currency})`} required fullWidth value={form.adjusted_tangibles_total} onChange={event => setForm({ ...form, adjusted_tangibles_total: event.target.value })} inputProps={{ inputMode: 'decimal' }}/>
                </Box>
                <Typography fontSize={12.5}>Adjusted total {amountText(adjustedSum.toFixed(2), afe.standard_currency)}</Typography>
                <ErrorMessage message={formError}/>
                <Box display="flex" gap={1} flexWrap="wrap">
                  <Button variant="contained" disabled={saving || !form.reason.trim() || (openDraft != null && editingId == null)} title={formBlocked} onClick={() => void submitForm()}>
                    {saving ? 'Saving…' : editingId ? 'Save draft' : 'Save draft revision'}
                  </Button>
                  {editingId && <Button color="inherit" disabled={saving} onClick={cancelEdit}>Cancel edit</Button>}
                </Box>
              </Box>
            </Box>}
            {adjustments.length === 0
              ? <Typography color="text.secondary" fontSize={13}>No adjustments recorded yet.</Typography>
              : adjustments.map(adjustment => <Box key={adjustment.id} sx={{ p: 1.8, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
                <Box display="flex" justifyContent="space-between" alignItems="center" gap={1.5} flexWrap="wrap">
                  <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                    <Typography fontWeight={800} fontSize={14}>Revision {adjustment.revision_number}</Typography>
                    <Tag tone={SOW_STATUS_TONE[adjustment.status]}>{SOW_STATUS_LABEL[adjustment.status]}</Tag>
                    <Typography fontSize={12} color="text.secondary">
                      {new Date(adjustment.created_at).toLocaleString()} by {adjustment.created_by || 'workspace user'}
                    </Typography>
                  </Box>
                  <Typography fontWeight={800} fontSize={14}>
                    {amountText(adjustment.adjusted_total, adjustment.standard_currency)}{' '}
                    <Typography component="span" fontSize={12.5} color={Number(adjustment.delta_total) < 0 ? 'success.main' : 'text.secondary'}>
                      ({adjustmentDeltaText(adjustment.delta_total, adjustment.standard_currency)})
                    </Typography>
                  </Typography>
                </Box>
                <Typography fontSize={12.5} mt={1}><strong>Reason:</strong> {adjustment.reason}</Typography>
                {adjustment.sow_summary && <Typography fontSize={12.5} mt={.4} color="text.secondary">{adjustment.sow_summary}</Typography>}
                <Typography fontSize={12} color="text.secondary" mt={.8}>
                  Services {amountText(adjustment.adjusted_services_total)} · Consumables {amountText(adjustment.adjusted_consumables_total)} · Tangibles {amountText(adjustment.adjusted_tangibles_total)}
                  {adjustment.original_total != null && <> · Original {amountText(adjustment.original_total, adjustment.standard_currency)}</>}
                </Typography>
                {adjustment.status !== 'draft' && <Typography fontSize={12} color="text.secondary" mt={.4}>
                  {adjustment.status === 'approved' ? 'Approved' : 'Voided'} by {adjustment.approved_by || 'workspace user'}
                  {adjustment.approved_at ? ` on ${new Date(adjustment.approved_at).toLocaleString()}` : ''}
                </Typography>}
                <Box display="flex" gap={1} mt={1.2} flexWrap="wrap">
                  {canAdjust && adjustment.status === 'draft' && <Button size="small" variant="outlined" onClick={() => startEdit(adjustment)}>Edit draft</Button>}
                  {canDecide && adjustment.status === 'draft' && <Button size="small" variant="contained" onClick={() => { setDecision({ adjustment, action: 'approve' }); setRemarks(''); setDecisionError('') }}>Approve</Button>}
                  {canDecide && adjustment.status !== 'void' && <Button size="small" variant="outlined" color="error" onClick={() => { setDecision({ adjustment, action: 'void' }); setRemarks(''); setDecisionError('') }}>Void</Button>}
                </Box>
              </Box>)}
          </>}
      </Box>
    </PanelDialog>

    <FormDialog
      open={decision != null}
      title={decision?.action === 'approve' ? `Approve revision ${decision.adjustment.revision_number}?` : `Void revision ${decision?.adjustment.revision_number}?`}
      subtitle={decision?.action === 'approve'
        ? 'The revised totals become the effective AFE budget for cost comparisons. Earlier approved revisions are superseded.'
        : 'Voiding removes this revision from cost comparisons. The previously approved revision (if any) becomes effective again.'}
      onClose={() => { if (!deciding) setDecision(null) }}
      onSubmit={() => void submitDecision()}
      busy={deciding}
      submitDisabled={remarks.trim().length < 3}
      submitLabel={decision?.action === 'approve' ? 'Approve revision' : 'Void revision'}
      danger={decision?.action === 'void'}
    >
      <Box display="grid" gap={1.7} pt={.5}>
        <TextField label="Approval remarks" required fullWidth multiline minRows={3} value={remarks} onChange={event => setRemarks(event.target.value)} inputProps={{ maxLength: 1000 }} helperText="At least 3 characters. Recorded permanently with the revision."/>
        <ErrorMessage message={decisionError}/>
      </Box>
    </FormDialog>
  </>
}

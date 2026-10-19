import { useEffect, useState } from 'react'
import { Alert, Box, Button, CircularProgress, MenuItem, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog, PanelDialog, Tag } from './Common'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { formatDays, type Well, type WellConfiguration } from '../lib/rigWell'
import {
  SOW_STATUS_LABEL, SOW_STATUS_TONE, approveWellPlanAdjustment, createWellPlanAdjustment,
  listWellPlanAdjustments, updateWellPlanAdjustment, voidWellPlanAdjustment,
  type AdjustmentScope, type WellPlanAdjustment,
} from '../lib/sowAdjustment'

type Decision = { adjustment: WellPlanAdjustment; action: 'approve' | 'void' } | null

export function PlanAdjustmentDialog({ open, well, onClose, onChanged }: {
  open: boolean
  well: Well
  onClose: () => void
  onChanged: () => void
}) {
  const { can } = useAuth()
  const canAdjust = can('rig-well:plan-adjust')
  const [scope, setScope] = useState<AdjustmentScope>('drilling')
  const [configuration, setConfiguration] = useState<WellConfiguration | null>(null)
  const [adjustments, setAdjustments] = useState<WellPlanAdjustment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reason, setReason] = useState('')
  const [scopeSummary, setScopeSummary] = useState('')
  const [daysAfter, setDaysAfter] = useState('')
  const [sectionsAfter, setSectionsAfter] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [decision, setDecision] = useState<Decision>(null)
  const [remarks, setRemarks] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [deciding, setDeciding] = useState(false)

  const openDraft = adjustments.find(item => item.configuration_scope === scope && item.status === 'draft' && item.id !== editingId) ?? null
  const scoped = adjustments.filter(item => item.configuration_scope === scope)
  const configured = scope === 'drilling' ? well.config_status === 'configured' : well.completion_config_status === 'configured'

  const load = async (activeScope: AdjustmentScope) => {
    setLoading(true)
    setError('')
    try {
      const [config, rows] = await Promise.all([
        api<WellConfiguration>(`/rig-well/wells/${well.id}/configuration?scope=${activeScope}`),
        listWellPlanAdjustments(well.id),
      ])
      setConfiguration(config)
      setAdjustments(rows)
      if (!editingId) {
        setDaysAfter(String(config.total_days ?? '0'))
        setSectionsAfter(String(config.sections.length))
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Plan adjustments could not be loaded')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    setReason('')
    setScopeSummary('')
    setEditingId(null)
    setFormError('')
    void load(scope)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, well.id])

  const changeScope = (next: AdjustmentScope) => {
    setScope(next)
    setEditingId(null)
    setReason('')
    setScopeSummary('')
    setFormError('')
    void load(next)
  }

  const startEdit = (adjustment: WellPlanAdjustment) => {
    setEditingId(adjustment.id)
    setReason(adjustment.reason)
    setScopeSummary(adjustment.sow_summary)
    setDaysAfter(adjustment.planned_days_after)
    setSectionsAfter(String(adjustment.section_count_after))
    setFormError('')
  }

  const cancelEdit = () => {
    setEditingId(null)
    setReason('')
    setScopeSummary('')
    setFormError('')
    if (configuration) {
      setDaysAfter(String(configuration.total_days ?? '0'))
      setSectionsAfter(String(configuration.sections.length))
    }
  }

  const submitForm = async () => {
    setSaving(true)
    setFormError('')
    try {
      const sections = sectionsAfter.trim() === '' ? undefined : Number(sectionsAfter)
      if (editingId) {
        await updateWellPlanAdjustment(editingId, {
          reason: reason.trim(), sow_summary: scopeSummary.trim(), planned_days_after: daysAfter, section_count_after: sections,
        })
      } else {
        await createWellPlanAdjustment(well.id, {
          configuration_scope: scope, reason: reason.trim(), sow_summary: scopeSummary.trim(),
          planned_days_after: daysAfter, section_count_after: sections,
        })
      }
      cancelEdit()
      await load(scope)
      onChanged()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'The plan adjustment could not be saved')
    } finally {
      setSaving(false)
    }
  }

  const submitDecision = async () => {
    if (!decision) return
    setDeciding(true)
    setDecisionError('')
    try {
      if (decision.action === 'approve') await approveWellPlanAdjustment(decision.adjustment.id, remarks.trim())
      else await voidWellPlanAdjustment(decision.adjustment.id, remarks.trim())
      setDecision(null)
      setRemarks('')
      await load(scope)
      onChanged()
    } catch (caught) {
      setDecisionError(caught instanceof Error ? caught.message : 'The decision could not be recorded')
    } finally {
      setDeciding(false)
    }
  }

  return <>
    <PanelDialog
      open={open && decision == null}
      title={`Plan adjustments · ${well.well_code}`}
      subtitle="Revisions to the configured plan live here — the configured plan itself never changes. Only the latest approved revision per scope affects planned-days comparisons."
      onClose={onClose}
      maxWidth="md"
      footer={<Button variant="outlined" onClick={onClose}>Close</Button>}
    >
      <Box display="grid" gap={2}>
        <TextField select label="Configuration scope" fullWidth value={scope} onChange={event => changeScope(event.target.value as AdjustmentScope)}>
          <MenuItem value="drilling">Drilling</MenuItem>
          <MenuItem value="completion">Completion</MenuItem>
        </TextField>
        <ErrorMessage message={error}/>
        {loading
          ? <Box py={4} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
          : <>
            <Alert severity="info">
              Configured {scope} plan: {configuration ? formatDays(configuration.total_days) : '—'}
              {configuration ? ` across ${configuration.sections.length} section(s)` : ''} · Plan {configuration?.config_status}
              {scope === 'drilling' && well.has_plan_adjustment && well.adjusted_total_days != null && <> · Effective {formatDays(well.adjusted_total_days)} (Rev {well.plan_revision})</>}
            </Alert>
            {!configured && <Alert severity="warning">Mark the {scope} plan as Configured before recording an adjustment — only adjustments to a configured plan are allowed.</Alert>}
            {canAdjust && configured && <Box sx={{ p: 1.8, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
              <Typography fontWeight={800} fontSize={14} mb={.3}>{editingId ? 'Edit draft revision' : 'New adjustment draft'}</Typography>
              <Typography color="text.secondary" fontSize={12} mb={1.5}>
                {editingId
                  ? 'Only draft revisions can be edited. Approving a revision locks it.'
                  : openDraft
                    ? `Revision ${openDraft.revision_number} is still a draft. Approve or void it before starting another.`
                    : 'Prefilled with the configured plan — change the totals the scope change affects.'}
              </Typography>
              <Box display="grid" gap={1.5}>
                <TextField label="Reason" required fullWidth value={reason} onChange={event => setReason(event.target.value)} inputProps={{ maxLength: 1000 }} helperText="Why the plan changed — recorded permanently with the revision."/>
                <TextField label="Scope summary" fullWidth multiline minRows={2} value={scopeSummary} onChange={event => setScopeSummary(event.target.value)} inputProps={{ maxLength: 2000 }} helperText="Added or removed sections, phases and day changes."/>
                <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }} gap={1.5}>
                  <TextField label="Planned days after" required fullWidth value={daysAfter} onChange={event => setDaysAfter(event.target.value)} inputProps={{ inputMode: 'decimal' }}/>
                  <TextField label="Sections after" fullWidth value={sectionsAfter} onChange={event => setSectionsAfter(event.target.value)} inputProps={{ inputMode: 'numeric' }}/>
                </Box>
                <ErrorMessage message={formError}/>
                <Box display="flex" gap={1} flexWrap="wrap">
                  <Button variant="contained" disabled={saving || reason.trim().length < 3 || !daysAfter.trim() || (openDraft != null && editingId == null)} onClick={() => void submitForm()}>
                    {saving ? 'Saving…' : editingId ? 'Save draft' : 'Save draft revision'}
                  </Button>
                  {editingId && <Button color="inherit" disabled={saving} onClick={cancelEdit}>Cancel edit</Button>}
                </Box>
              </Box>
            </Box>}
            {scoped.length === 0
              ? <Typography color="text.secondary" fontSize={13}>No {scope} adjustments recorded yet.</Typography>
              : scoped.map(adjustment => <Box key={adjustment.id} sx={{ p: 1.8, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
                <Box display="flex" justifyContent="space-between" alignItems="center" gap={1.5} flexWrap="wrap">
                  <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                    <Typography fontWeight={800} fontSize={14}>Revision {adjustment.revision_number}</Typography>
                    <Tag tone={SOW_STATUS_TONE[adjustment.status]}>{SOW_STATUS_LABEL[adjustment.status]}</Tag>
                    <Typography fontSize={12} color="text.secondary">
                      {new Date(adjustment.created_at).toLocaleString()} by {adjustment.created_by || 'workspace user'}
                    </Typography>
                  </Box>
                  <Typography fontWeight={800} fontSize={14}>
                    {formatDays(adjustment.planned_days_after)}{' '}
                    <Typography component="span" fontSize={12.5} color="text.secondary">
                      ({Number(adjustment.delta_days) > 0 ? '+' : ''}{Number(adjustment.delta_days).toLocaleString(undefined, { maximumFractionDigits: 2 })} d)
                    </Typography>
                  </Typography>
                </Box>
                <Typography fontSize={12.5} mt={1}><strong>Reason:</strong> {adjustment.reason}</Typography>
                {adjustment.sow_summary && <Typography fontSize={12.5} mt={.4} color="text.secondary">{adjustment.sow_summary}</Typography>}
                <Typography fontSize={12} color="text.secondary" mt={.4}>
                  Was {formatDays(adjustment.planned_days_before)} across {adjustment.section_count_before} section(s) · Now {adjustment.section_count_after} section(s)
                </Typography>
                {adjustment.status !== 'draft' && <Typography fontSize={12} color="text.secondary" mt={.4}>
                  {adjustment.status === 'approved' ? 'Approved' : 'Voided'} by {adjustment.approved_by || 'workspace user'}
                  {adjustment.approved_at ? ` on ${new Date(adjustment.approved_at).toLocaleString()}` : ''}
                </Typography>}
                {canAdjust && <Box display="flex" gap={1} mt={1.2} flexWrap="wrap">
                  {adjustment.status === 'draft' && <Button size="small" variant="outlined" onClick={() => startEdit(adjustment)}>Edit draft</Button>}
                  {adjustment.status === 'draft' && <Button size="small" variant="contained" onClick={() => { setDecision({ adjustment, action: 'approve' }); setRemarks(''); setDecisionError('') }}>Approve</Button>}
                  {adjustment.status !== 'void' && <Button size="small" variant="outlined" color="error" onClick={() => { setDecision({ adjustment, action: 'void' }); setRemarks(''); setDecisionError('') }}>Void</Button>}
                </Box>}
              </Box>)}
          </>}
      </Box>
    </PanelDialog>

    <FormDialog
      open={decision != null}
      title={decision?.action === 'approve' ? `Approve revision ${decision.adjustment.revision_number}?` : `Void revision ${decision?.adjustment.revision_number}?`}
      subtitle={decision?.action === 'approve'
        ? 'The revised planned days become the effective plan for this scope. Earlier approved revisions are superseded.'
        : 'Voiding removes this revision from planned-days comparisons. The previously approved revision (if any) becomes effective again.'}
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

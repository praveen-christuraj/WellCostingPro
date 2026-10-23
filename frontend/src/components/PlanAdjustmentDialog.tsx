import { useEffect, useMemo, useRef, useState } from 'react'
import { AddRounded, ArrowDownwardRounded, ArrowUpwardRounded, DeleteOutlineRounded } from '@mui/icons-material'
import { Alert, Box, Button, Card, CardContent, CircularProgress, Divider, MenuItem, Paper, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog, PanelDialog, Tag } from './Common'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import {
  SOW_CHANGE_LABEL, SOW_CHANGE_TONE, SOW_STATUS_LABEL, SOW_STATUS_TONE,
  approveWellPlanAdjustment, createWellPlanAdjustment, listWellPlanAdjustments,
  updateWellPlanAdjustment, voidWellPlanAdjustment,
  type AdjustmentScope, type LineChange, type PlanSectionEntry, type PlanSectionRow,
  type WellPlanAdjustment,
} from '../lib/sowAdjustment'
import { formatDays, type MasterConfigurationOption, type RigWellConfigurationOptions, type Well, type WellConfiguration } from '../lib/rigWell'

type PhaseInput = {
  key: string
  pair_key: string | null
  phase_id: string
  days: string
  remarks: string
}
type SectionInput = {
  key: string
  pair_key: string | null
  hole_section_id: string
  from_depth: string
  to_depth: string
  remarks: string
  phases: PhaseInput[]
}

// One baseline snapshot per seeded row, so every edited value can read against
// the value it replaces ('new value against the entered value').
type PhaseBaseline = { phase_id: string; days: string; remarks: string }
type SectionBaseline = {
  hole_section_id: string
  from_depth: string
  to_depth: string
  remarks: string
  phases: Map<string, PhaseBaseline>
}
type BaselineMap = Map<string, SectionBaseline>

type Decision = { adjustment: WellPlanAdjustment; action: 'approve' | 'void' } | null

const numberValue = (value: string) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

const sameNumber = (left: string, right: string) => Number(left) === Number(right)

function phaseChange(phase: PhaseInput, baseline: SectionBaseline | undefined): LineChange {
  if (!baseline) return 'added'
  const before = baseline.phases.get(phase.pair_key ?? '')
  if (!before) return 'added'
  const movedParent = false
  const changed = before.phase_id !== phase.phase_id
    || !sameNumber(before.days, phase.days)
    || (before.remarks || '') !== (phase.remarks || '')
  return changed || movedParent ? 'modified' : 'kept'
}

function sectionChange(section: SectionInput, baseline: BaselineMap): LineChange {
  const before = baseline.get(section.pair_key ?? '')
  if (!before) return 'added'
  const ownChanged = before.hole_section_id !== section.hole_section_id
    || !sameNumber(before.from_depth, section.from_depth)
    || !sameNumber(before.to_depth, section.to_depth)
    || (before.remarks || '') !== (section.remarks || '')
  const phasesChanged = section.phases.some(phase => phaseChange(phase, before) !== 'kept')
    || [...before.phases.keys()].some(key => !section.phases.some(phase => (phase.pair_key ?? '') === key))
  return ownChanged || phasesChanged ? 'modified' : 'kept'
}

export function PlanAdjustmentDialog({ open, well, initialScope, onClose, onChanged }: {
  open: boolean
  well: Well
  initialScope?: AdjustmentScope
  onClose: () => void
  onChanged: () => void
}) {
  const { can } = useAuth()
  const canAdjust = can('rig-well:plan-adjust')
  const keyCounter = useRef(0)
  const nextRowKey = () => `row-${++keyCounter.current}`
  const [scope, setScope] = useState<AdjustmentScope>(initialScope ?? 'drilling')
  useEffect(() => {
    if (open) setScope(initialScope ?? (well.drilling_is_deleted && !well.completion_is_deleted ? 'completion' : 'drilling'))
  }, [open, well.id, initialScope])
  const [options, setOptions] = useState<RigWellConfigurationOptions>({ hole_sections: [], phases: [] })
  const [configuration, setConfiguration] = useState<WellConfiguration | null>(null)
  const [adjustments, setAdjustments] = useState<WellPlanAdjustment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reason, setReason] = useState('')
  const [scopeSummary, setScopeSummary] = useState('')
  const [sections, setSections] = useState<SectionInput[]>([])
  const [baseline, setBaseline] = useState<BaselineMap>(new Map())
  const [configuredTotalDays, setConfiguredTotalDays] = useState(0)
  const [configuredSections, setConfiguredSections] = useState(0)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [decision, setDecision] = useState<Decision>(null)
  const [remarks, setRemarks] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [deciding, setDeciding] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const openDraft = adjustments.find(item => item.configuration_scope === scope && item.status === 'draft' && item.id !== editingId) ?? null
  const scoped = adjustments.filter(item => item.configuration_scope === scope)
  const configured = scope === 'drilling' ? well.config_status === 'configured' : well.completion_config_status === 'configured'
  const depthUnit: 'm' | 'ft' = (configuration?.depth_unit as 'm' | 'ft') ?? well.depth_unit ?? 'm'

  const totalDays = useMemo(
    () => sections.reduce((total, section) => total + section.phases.reduce((sum, phase) => sum + numberValue(phase.days), 0), 0),
    [sections],
  )

  const seedFromConfiguration = (config: WellConfiguration) => {
    const seededBaseline: BaselineMap = new Map()
    const seeded: SectionInput[] = config.sections.map((section, sectionIndex) => {
      const sectionPair = `s${sectionIndex}`
      const phases = new Map<string, PhaseBaseline>()
      const phaseRows: PhaseInput[] = section.phases.map((phase, phaseIndex) => {
        const phasePair = `p${sectionIndex}-${phaseIndex}`
        phases.set(phasePair, { phase_id: phase.phase_id, days: String(phase.days), remarks: phase.remarks ?? '' })
        return {
          key: nextRowKey(), pair_key: phasePair, phase_id: phase.phase_id,
          days: String(phase.days), remarks: phase.remarks ?? '',
        }
      })
      seededBaseline.set(sectionPair, {
        hole_section_id: section.hole_section_id,
        from_depth: String(section.from_depth),
        to_depth: String(section.to_depth),
        remarks: section.remarks ?? '',
        phases,
      })
      return {
        key: nextRowKey(), pair_key: sectionPair, hole_section_id: section.hole_section_id,
        from_depth: String(section.from_depth), to_depth: String(section.to_depth),
        remarks: section.remarks ?? '', phases: phaseRows,
      }
    })
    setSections(seeded)
    setBaseline(seededBaseline)
    setConfiguredTotalDays(config.sections.reduce((total, section) => total + section.phases.reduce((sum, phase) => sum + numberValue(String(phase.days)), 0), 0))
    setConfiguredSections(config.sections.length)
  }

  const seedFromDraft = (adjustment: WellPlanAdjustment) => {
    // Edit a draft against the snapshot it was recorded with: the before rows
    // are the entered values, the after rows seed the editable grid.
    const seededBaseline: BaselineMap = new Map()
    for (const row of adjustment.sections_before) {
      const phases = new Map<string, PhaseBaseline>()
      for (const phase of row.phases) {
        phases.set(phase.pair_key, { phase_id: phase.phase_id, days: String(phase.days), remarks: phase.remarks })
      }
      seededBaseline.set(row.pair_key, {
        hole_section_id: row.hole_section_id,
        from_depth: String(row.from_depth),
        to_depth: String(row.to_depth),
        remarks: row.remarks,
        phases,
      })
    }
    const seeded: SectionInput[] = adjustment.sections_after.map(row => ({
      key: nextRowKey(),
      pair_key: row.pair_key,
      hole_section_id: row.hole_section_id,
      from_depth: String(row.from_depth),
      to_depth: String(row.to_depth),
      remarks: row.remarks,
      phases: row.phases.map(phase => ({
        key: nextRowKey(), pair_key: phase.pair_key, phase_id: phase.phase_id,
        days: String(phase.days), remarks: phase.remarks,
      })),
    }))
    setSections(seeded)
    setBaseline(seededBaseline)
    setConfiguredTotalDays(Number(adjustment.planned_days_before))
    setConfiguredSections(adjustment.section_count_before)
  }

  const load = async (activeScope: AdjustmentScope) => {
    setLoading(true)
    setError('')
    try {
      const [referenceOptions, config, rows] = await Promise.all([
        api<RigWellConfigurationOptions>('/rig-well/configuration-options'),
        api<WellConfiguration>(`/rig-well/wells/${well.id}/configuration?scope=${activeScope}`),
        listWellPlanAdjustments(well.id),
      ])
      setOptions(referenceOptions)
      setConfiguration(config)
      setAdjustments(rows)
      if (!editingId) seedFromConfiguration(config)
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
    setExpanded(null)
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

  const updateSection = (key: string, patch: Partial<SectionInput>) =>
    setSections(rows => rows.map(row => row.key === key ? { ...row, ...patch } : row))
  const updatePhase = (sectionKey: string, phaseKey: string, patch: Partial<PhaseInput>) =>
    setSections(rows => rows.map(section => section.key === sectionKey
      ? { ...section, phases: section.phases.map(phase => phase.key === phaseKey ? { ...phase, ...patch } : phase) }
      : section))
  const addSection = () => setSections(rows => [...rows, {
    key: nextRowKey(), pair_key: null, hole_section_id: '', from_depth: '', to_depth: '', remarks: '', phases: [],
  }])
  const removeSection = (key: string) => setSections(rows => rows.filter(row => row.key !== key))
  const moveSection = (index: number, direction: -1 | 1) => setSections(rows => {
    const target = index + direction
    if (target < 0 || target >= rows.length) return rows
    const reordered = [...rows]
    ;[reordered[index], reordered[target]] = [reordered[target], reordered[index]]
    return reordered
  })
  const addPhase = (sectionKey: string) => setSections(rows => rows.map(section => section.key === sectionKey
    ? { ...section, phases: [...section.phases, { key: nextRowKey(), pair_key: null, phase_id: '', days: '', remarks: '' }] }
    : section))
  const removePhase = (sectionKey: string, phaseKey: string) => setSections(rows => rows.map(section => section.key === sectionKey
    ? { ...section, phases: section.phases.filter(phase => phase.key !== phaseKey) }
    : section))

  const startEdit = (adjustment: WellPlanAdjustment) => {
    setEditingId(adjustment.id)
    setReason(adjustment.reason)
    setScopeSummary(adjustment.sow_summary)
    seedFromDraft(adjustment)
    setFormError('')
  }

  const cancelEdit = () => {
    setEditingId(null)
    setReason('')
    setScopeSummary('')
    setFormError('')
    if (configuration) seedFromConfiguration(configuration)
  }

  const toPayload = (): PlanSectionEntry[] => sections.map(section => ({
    pair_key: section.pair_key,
    hole_section_id: section.hole_section_id,
    from_depth: section.from_depth,
    to_depth: section.to_depth,
    remarks: section.remarks.trim(),
    phases: section.phases.map(phase => ({
      pair_key: phase.pair_key,
      phase_id: phase.phase_id,
      days: phase.days,
      remarks: phase.remarks.trim(),
    })),
  }))

  const submitForm = async () => {
    setSaving(true)
    setFormError('')
    try {
      if (editingId) {
        await updateWellPlanAdjustment(editingId, {
          reason: reason.trim(), sow_summary: scopeSummary.trim(), sections: toPayload(),
        })
      } else {
        await createWellPlanAdjustment(well.id, {
          configuration_scope: scope, reason: reason.trim(), sow_summary: scopeSummary.trim(), sections: toPayload(),
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

  const optionById = (items: MasterConfigurationOption[], id: string) => items.find(item => item.id === id)

  const changeLabel = (change: LineChange) =>
    <Tag tone={SOW_CHANGE_TONE[change]}>{SOW_CHANGE_LABEL[change]}</Tag>

  const wasChip = (before: string | undefined, unit = '') =>
    before === undefined ? null : (
      <Typography component="span" fontSize={11} color="warning.main" fontWeight={700}>
        was {before}{unit}
      </Typography>
    )

  const revisionSummary = (adjustment: WellPlanAdjustment) => {
    const afterRows = adjustment.sections_after
    const beforeRows = adjustment.sections_before
    const added = afterRows.filter(row => row.change === 'added').length
    const removed = beforeRows.filter(row => row.change === 'removed').length
    const modified = afterRows.filter(row => row.change === 'modified').length
    return [added ? `${added} new section(s)` : '', removed ? `${removed} removed section(s)` : '', modified ? `${modified} modified section(s)` : '']
      .filter(Boolean).join(' · ') || 'No line changes'
  }

  return <>
    <PanelDialog
      open={open && decision == null}
      title={`Plan adjustments · ${well.well_code}`}
      subtitle="Revisions are entered through the same well configuration grid — change the entered values, add or remove sections and phases. Planned days and section counts derive from the grid. The configured plan itself never changes."
      onClose={onClose}
      maxWidth="lg"
      footer={<Button variant="outlined" onClick={onClose}>Close</Button>}
    >
      <Box display="grid" gap={2}>
        <TextField select label="Configuration scope" fullWidth value={scope} onChange={event => changeScope(event.target.value as AdjustmentScope)}>
          <MenuItem value="drilling" disabled={Boolean(well.drilling_is_deleted)}>Drilling{well.drilling_is_deleted ? ' (deleted)' : ''}</MenuItem>
          <MenuItem value="completion" disabled={Boolean(well.completion_is_deleted)}>Completion{well.completion_is_deleted ? ' (deleted)' : ''}</MenuItem>
        </TextField>
        <ErrorMessage message={error}/>
        {loading
          ? <Box py={4} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
          : <>
            <Alert severity="info">
              Configured {scope} plan: {formatDays(configuredTotalDays)} across {configuredSections} section(s)
              {configuration ? ` · Plan ${configuration.config_status}` : ''}
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
                    : 'Prefilled with the configured plan — change the entered values the scope change affects and add or remove sections and phases.'}
              </Typography>
              <Box display="grid" gap={1.5}>
                <TextField label="Reason" required fullWidth value={reason} onChange={event => setReason(event.target.value)} inputProps={{ maxLength: 500 }} helperText="Why the plan changed — recorded permanently with the revision."/>
                <TextField label="Scope summary" fullWidth multiline minRows={2} value={scopeSummary} onChange={event => setScopeSummary(event.target.value)} inputProps={{ maxLength: 2000 }} helperText="Narrative of what the scope change adds or removes."/>
                <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap">
                  <Box><Typography fontWeight={800} fontSize={13}>Revised sections and phases</Typography>
                    <Typography color="text.secondary" fontSize={11.5} mt={.25}>Each row starts from the entered value — changed values are marked, new rows are tagged New.</Typography></Box>
                  <Button size="small" variant="outlined" startIcon={<AddRounded/>} onClick={addSection} disabled={!options.hole_sections.length}>Add section</Button>
                </Box>
                <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr 1fr' }} gap={1.2}>
                  <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, px: 1.5, py: 1 }}>
                    <Typography fontSize={10} fontWeight={800} color="text.secondary" textTransform="uppercase">Revised planned days</Typography>
                    <Typography fontSize={15} fontWeight={800} mt={.3}>
                      {totalDays.toFixed(2)} d
                      <Typography component="span" fontSize={11.5} color="text.secondary" ml={1}>
                        against {configuredTotalDays.toFixed(2)} d entered ({(totalDays - configuredTotalDays) >= 0 ? '+' : ''}{(totalDays - configuredTotalDays).toFixed(2)} d)
                      </Typography>
                    </Typography>
                  </Box>
                  <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, px: 1.5, py: 1 }}>
                    <Typography fontSize={10} fontWeight={800} color="text.secondary" textTransform="uppercase">Revised section count</Typography>
                    <Typography fontSize={15} fontWeight={800} mt={.3}>
                      {sections.length}
                      <Typography component="span" fontSize={11.5} color="text.secondary" ml={1}>
                        against {configuredSections} entered ({sections.length - configuredSections >= 0 ? '+' : ''}{sections.length - configuredSections})
                      </Typography>
                    </Typography>
                  </Box>
                  <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, px: 1.5, py: 1 }}>
                    <Typography fontSize={10} fontWeight={800} color="text.secondary" textTransform="uppercase">Depth unit (from plan)</Typography>
                    <Typography fontSize={15} fontWeight={800} mt={.3}>{depthUnit === 'ft' ? 'Feet (ft)' : 'Metres (m)'}</Typography>
                  </Box>
                </Box>
                {!sections.length && <Paper variant="outlined" sx={{ p: 2.5, textAlign: 'center', borderStyle: 'dashed' }}>
                  <Typography fontWeight={700} fontSize={13}>No revised sections</Typography>
                  <Typography color="text.secondary" fontSize={12} mt={.5}>Add at least one Hole Section with its phases — the same way the well configuration is entered.</Typography>
                </Paper>}
                {sections.map((section, sectionIndex) => {
                  const before = baseline.get(section.pair_key ?? '')
                  const change = sectionChange(section, baseline)
                  const selectedSection = optionById(options.hole_sections, section.hole_section_id)
                  const phaseDays = section.phases.reduce((sum, phase) => sum + numberValue(phase.days), 0)
                  return <Card key={section.key} variant="outlined" sx={{ borderRadius: 2, borderColor: change === 'added' ? 'success.main' : change === 'modified' ? 'info.main' : 'divider' }}>
                    <CardContent sx={{ p: '14px !important' }}>
                      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} mb={1.2}>
                        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                          <Box className="table-icon" sx={{ width: 26, height: 26, fontSize: 10.5, fontWeight: 800 }}>{String(sectionIndex + 1).padStart(2, '0')}</Box>
                          <Typography fontWeight={800} fontSize={12.5}>Hole Section {sectionIndex + 1}{selectedSection ? ` · ${selectedSection.code}` : ''}</Typography>
                          <Tag>{phaseDays.toFixed(2)} days</Tag>
                          {change !== 'kept' && changeLabel(change)}
                        </Box>
                        <Box display="flex" gap={.2}>
                          <Button size="small" aria-label="Move section up" disabled={sectionIndex === 0} onClick={() => moveSection(sectionIndex, -1)}><ArrowUpwardRounded fontSize="small"/></Button>
                          <Button size="small" aria-label="Move section down" disabled={sectionIndex === sections.length - 1} onClick={() => moveSection(sectionIndex, 1)}><ArrowDownwardRounded fontSize="small"/></Button>
                          <Button size="small" color="error" aria-label="Remove section" onClick={() => removeSection(section.key)}><DeleteOutlineRounded fontSize="small"/></Button>
                        </Box>
                      </Box>
                      <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1.5fr 1fr 1fr 1fr' }} gap={1.2}>
                        <TextField select label="Hole Section" required value={section.hole_section_id} onChange={event => updateSection(section.key, { hole_section_id: event.target.value })}
                          helperText={before && before.hole_section_id !== section.hole_section_id ? wasChip(options.hole_sections.find(option => option.id === before.hole_section_id)?.code ?? 'previous selection') : undefined}>
                          {section.hole_section_id && !selectedSection && <MenuItem value={section.hole_section_id} disabled>Deleted or unavailable section · choose another</MenuItem>}
                          {options.hole_sections.map(option => <MenuItem key={option.id} value={option.id}>{option.code} — {option.name}</MenuItem>)}
                        </TextField>
                        <TextField type="number" label={`From (${depthUnit})`} required value={section.from_depth} inputProps={{ min: 0, step: .0000000001 }}
                          helperText={before && !sameNumber(before.from_depth, section.from_depth) ? wasChip(before.from_depth) : undefined}
                          onChange={event => updateSection(section.key, { from_depth: event.target.value })}/>
                        <TextField type="number" label={`To (${depthUnit})`} required value={section.to_depth} inputProps={{ min: 0, step: .0000000001 }}
                          helperText={before && !sameNumber(before.to_depth, section.to_depth) ? wasChip(before.to_depth) : undefined}
                          onChange={event => updateSection(section.key, { to_depth: event.target.value })}/>
                        <TextField label="Section remarks" value={section.remarks} inputProps={{ maxLength: 1000 }}
                          helperText={before && (before.remarks || '') !== (section.remarks || '') ? wasChip(before.remarks || 'empty') : undefined}
                          onChange={event => updateSection(section.key, { remarks: event.target.value })}/>
                      </Box>
                      <Divider sx={{ my: 1.4 }}/>
                      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} mb={1}>
                        <Typography fontWeight={800} fontSize={12}>Phases</Typography>
                        <Button size="small" startIcon={<AddRounded/>} onClick={() => addPhase(section.key)} disabled={!options.phases.length}>Add phase</Button>
                      </Box>
                      {!section.phases.length && <Typography color="text.secondary" fontSize={12} sx={{ py: .8 }}>At least one Phase is needed for each section.</Typography>}
                      <Box display="grid" gap={1}>
                        {section.phases.map((phase, phaseIndex) => {
                          const phaseBefore = before?.phases.get(phase.pair_key ?? '')
                          const changePhase = phaseChange(phase, before)
                          const selectedPhase = optionById(options.phases, phase.phase_id)
                          return <Box key={phase.key} display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1.6fr .6fr 1.4fr auto' }} gap={1} alignItems="center">
                            <TextField select label={`Phase ${phaseIndex + 1}`} required value={phase.phase_id} onChange={event => updatePhase(section.key, phase.key, { phase_id: event.target.value })}
                              helperText={phaseBefore && phaseBefore.phase_id !== phase.phase_id
                                ? wasChip(options.phases.find(option => option.id === phaseBefore.phase_id)?.code ?? 'previous phase')
                                : changePhase === 'added' ? <Typography component="span" fontSize={11} color="success.main" fontWeight={700}>New phase</Typography> : undefined}>
                              {phase.phase_id && !selectedPhase && <MenuItem value={phase.phase_id} disabled>Deleted or unavailable phase · choose another</MenuItem>}
                              {options.phases.map(option => <MenuItem key={option.id} value={option.id}>{option.code} — {option.name}</MenuItem>)}
                            </TextField>
                            <TextField type="number" label="Days" required value={phase.days} inputProps={{ min: 0, step: .0000000001 }}
                              helperText={phaseBefore && !sameNumber(phaseBefore.days, phase.days) ? wasChip(`${phaseBefore.days} d`) : undefined}
                              onChange={event => updatePhase(section.key, phase.key, { days: event.target.value })}/>
                            <TextField label="Phase remarks" value={phase.remarks} inputProps={{ maxLength: 1000 }}
                              helperText={phaseBefore && (phaseBefore.remarks || '') !== (phase.remarks || '') ? wasChip(phaseBefore.remarks || 'empty') : undefined}
                              onChange={event => updatePhase(section.key, phase.key, { remarks: event.target.value })}/>
                            <Button color="error" size="small" aria-label="Remove phase" onClick={() => removePhase(section.key, phase.key)}><DeleteOutlineRounded fontSize="small"/></Button>
                          </Box>
                        })}
                      </Box>
                    </CardContent>
                  </Card>
                })}
                <ErrorMessage message={formError}/>
                <Box display="flex" gap={1} flexWrap="wrap">
                  <Button variant="contained" disabled={saving || reason.trim().length < 3 || !sections.length || (openDraft != null && editingId == null)} onClick={() => void submitForm()}>
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
                  Was {formatDays(adjustment.planned_days_before)} across {adjustment.section_count_before} section(s) · Now {adjustment.section_count_after} section(s) · {revisionSummary(adjustment)}
                </Typography>
                <Button size="small" sx={{ mt: .8 }} onClick={() => setExpanded(expanded === adjustment.id ? null : adjustment.id)}>
                  {expanded === adjustment.id ? 'Hide revision grid' : 'Show revision grid'}
                </Button>
                {expanded === adjustment.id && <Box mt={1.2} display="grid" gap={1}>
                  {['before' as const, 'after' as const].map(side => {
                    const rows: PlanSectionRow[] = side === 'before' ? adjustment.sections_before : adjustment.sections_after
                    return <Box key={side} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.5, p: 1.2 }}>
                      <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" mb={.8}>
                        {side === 'before' ? 'Entered plan (before)' : 'Revised plan (after)'}
                      </Typography>
                      {rows.length === 0
                        ? <Typography fontSize={12} color="text.secondary">—</Typography>
                        : rows.map(row => <Box key={`${side}-${row.pair_key}`} mb={1}>
                          <Box display="flex" gap={.8} alignItems="center" flexWrap="wrap">
                            <Typography fontSize={12} fontWeight={700}>
                              {row.section_code || row.section_name} · {Number(row.from_depth).toLocaleString()}–{Number(row.to_depth).toLocaleString()} {adjustment.depth_unit}
                            </Typography>
                            <Tag>{Number(row.total_days).toLocaleString()} d</Tag>
                            {row.change !== 'kept' && changeLabel(row.change)}
                          </Box>
                          {row.phases.map(phase => <Box key={`${side}-${row.pair_key}-${phase.pair_key}`} display="flex" gap={.8} alignItems="center" flexWrap="wrap" ml={2}>
                            <Typography fontSize={11.5} color="text.secondary">
                              {phase.phase_code || phase.phase_name} · {Number(phase.days).toLocaleString()} d
                            </Typography>
                            {phase.change !== 'kept' && changeLabel(phase.change)}
                          </Box>)}
                        </Box>)}
                    </Box>
                  })}
                </Box>}
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

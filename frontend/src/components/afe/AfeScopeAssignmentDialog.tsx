import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, MenuItem, TextField, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import { phaseOptions, sectionOptions, type WellScope } from '../../lib/afe'

export type AfeScopeTarget = 'service' | 'consumable'
const ALL_SECTIONS = '__all_sections__'

type Props = {
  open: boolean
  target: AfeScopeTarget
  selectedCount: number
  unsupportedCount: number
  requireSection: boolean
  scope: WellScope
  onClose: () => void
  onApply: (sectionId: string | null, phaseId: string | null) => void
}

export function AfeScopeAssignmentDialog({
  open, target, selectedCount, unsupportedCount, requireSection, scope, onClose, onApply,
}: Props) {
  const sections = useMemo(() => sectionOptions(scope), [scope])
  const [sectionId, setSectionId] = useState('')
  const [phaseId, setPhaseId] = useState('')
  const effectiveSection = sectionId === ALL_SECTIONS ? null : sectionId || null
  const phases = useMemo(() => phaseOptions(scope, effectiveSection), [scope, effectiveSection])
  const invalidSection = requireSection && !effectiveSection

  useEffect(() => {
    if (!open) return
    setSectionId(requireSection ? (sections[0]?.id ?? '') : ALL_SECTIONS)
    setPhaseId('')
  }, [open, requireSection, sections])

  const apply = () => {
    if (invalidSection) return
    onApply(effectiveSection, effectiveSection ? phaseId || null : null)
  }

  const groupName = target === 'service' ? 'service' : 'consumable'

  return <FormDialog
    open={open}
    title={`Assign section and phase to selected ${groupName} lines`}
    subtitle={`The same well-plan scope will be applied to ${selectedCount} selected line(s). Rates, quantities and amounts are not changed.`}
    onClose={onClose}
    onSubmit={apply}
    submitLabel="Apply scope"
    submitDisabled={invalidSection || sections.length === 0}
    maxWidth="sm"
  >
    <Box display="grid" gap={1.6}>
      {unsupportedCount > 0 && <Alert severity="warning">
        {unsupportedCount} selected per-section-rate service line(s) are not changed by this action because their rates are stored separately for each section/phase.
      </Alert>}
      {target === 'service' && !requireSection && <Alert severity="info">
        For day-rate services, “All sections” keeps the well-wide planned-days split. A per-service charge requires one specific section.
      </Alert>}
      {sections.length === 0 && <Alert severity="warning">This well has no configured hole sections to assign.</Alert>}
      <TextField
        select
        label={target === 'consumable' || requireSection ? 'Hole section (required)' : 'Hole section'}
        value={sectionId}
        onChange={event => { setSectionId(event.target.value); setPhaseId('') }}
        error={invalidSection}
        helperText={target === 'consumable' ? 'Consumable estimates are tied to one section.' : 'Choose the section or keep the day-rate service well-wide.'}
      >
        {target === 'service' && !requireSection && <MenuItem value={ALL_SECTIONS}>All sections</MenuItem>}
        {sections.map(section => <MenuItem key={section.id} value={section.id}>{section.label}</MenuItem>)}
      </TextField>
      <TextField
        select
        label="Phase"
        value={phaseId}
        onChange={event => setPhaseId(event.target.value)}
        disabled={!effectiveSection || phases.length === 0}
        helperText={!effectiveSection ? 'Choose a section first.' : phases.length ? 'Optional; leave All phases to cover the full section.' : 'The chosen section has no phase split.'}
      >
        <MenuItem value="">All phases</MenuItem>
        {phases.map(phase => <MenuItem key={phase.id} value={phase.id}>{phase.label}</MenuItem>)}
      </TextField>
      <Typography fontSize={12} color="text.secondary">
        These are unsaved estimate edits. The normal estimate preview and validation will run; save the AFE to keep them.
      </Typography>
    </Box>
  </FormDialog>
}

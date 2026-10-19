import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  FormControl,
  FormControlLabel,
  FormLabel,
  MenuItem,
  Radio,
  RadioGroup,
  TextField,
  Typography,
} from '@mui/material'
import { FormDialog } from '../Common'
import {
  DAILY_ONE_TIME_CATEGORIES,
  deriveClassification,
  type DailyCostBaseline,
  type DailyCostReference,
  type DailyCostServiceInput,
  type DailyQuantityUnit,
} from '../../lib/dailyCost'

type Selection = { index: number; line: DailyCostServiceInput }
type ScopeMode = 'keep' | 'assign'

type Props = {
  open: boolean
  selections: Selection[]
  allLines: DailyCostServiceInput[]
  baseline: DailyCostBaseline
  reference: DailyCostReference
  wellId: string
  onClose: () => void
  onApply: (updates: Selection[]) => void
}

function commonValue<T>(items: T[]): T | null {
  if (!items.length || items.some(item => item !== items[0])) return null
  return items[0]
}

function rateQuantityUnit(basis: string, category: string): DailyQuantityUnit {
  if (basis === 'Per Service Rate') return 'service'
  if (basis === 'Per Section Rate') return 'section'
  return DAILY_ONE_TIME_CATEGORIES.includes(category as typeof DAILY_ONE_TIME_CATEGORIES[number]) ? 'unit' : 'days'
}

export function DailyCostBulkScopeDialog({
  open, selections, allLines, baseline, reference, wellId, onClose, onApply,
}: Props) {
  const [activityId, setActivityId] = useState('')
  const [subActivityId, setSubActivityId] = useState('')
  const [scopeMode, setScopeMode] = useState<ScopeMode>('keep')
  const [sectionId, setSectionId] = useState('')
  const [phaseId, setPhaseId] = useState('')
  const [error, setError] = useState('')

  const subActivities = useMemo(
    () => reference.sub_activities.filter(item => item.well_id === wellId && item.activity_id === activityId),
    [reference.sub_activities, activityId, wellId],
  )
  const sections = baseline.sections
  const selectedSection = sections.find(section => section.hole_section_id === sectionId)
  const requireSection = selections.some(({ line }) => line.charging_basis !== 'Day Rate')
  const activity = reference.activities.find(item => item.id === activityId)
  const classification = deriveClassification(activity)

  useEffect(() => {
    if (!open) return
    const selectedActivities = selections.map(item => item.line.activity_id)
    const selectedSubs = selections.map(item => item.line.sub_activity_id ?? '')
    const selectedSections = selections.map(item => item.line.hole_section_id ?? '')
    const selectedPhases = selections.map(item => item.line.phase_id ?? '')
    const commonActivity = commonValue(selectedActivities)
    const commonSub = commonValue(selectedSubs)
    const commonSection = commonValue(selectedSections)
    const commonPhase = commonValue(selectedPhases)
    setActivityId(commonActivity ?? '')
    setSubActivityId(commonSub ?? '')
    setScopeMode('keep')
    setSectionId(commonSection ?? '')
    setPhaseId(commonPhase ?? '')
    setError('')
  }, [open, selections])

  const setActivity = (nextActivityId: string) => {
    setActivityId(nextActivityId)
    if (!reference.sub_activities.some(item =>
      item.id === subActivityId && item.well_id === wellId && item.activity_id === nextActivityId,
    )) setSubActivityId('')
    setError('')
  }

  const apply = () => {
    setError('')
    if (!activityId) { setError('Select one Activity for the selected service lines.'); return }
    const selectedSub = reference.sub_activities.find(item =>
      item.id === subActivityId && item.well_id === wellId && item.activity_id === activityId,
    )
    if (!selectedSub) { setError('Select a well sub activity that belongs to this well and Activity.'); return }

    const targetSection = scopeMode === 'assign' ? sectionId || null : null
    const targetPhase = scopeMode === 'assign' && targetSection ? phaseId || null : null
    if (scopeMode === 'assign' && requireSection && !targetSection) {
      setError('The selected service charging basis requires a hole section.'); return
    }
    if (targetSection && !sections.some(section => section.hole_section_id === targetSection)) {
      setError('Choose a section from this daily sheet’s locked AFE baseline.'); return
    }
    if (targetPhase && !sections.find(section => section.hole_section_id === targetSection)?.phases.some(phase => phase.phase_id === targetPhase)) {
      setError('Choose a phase that belongs to the selected section.'); return
    }

    const selectedIndexes = new Set(selections.map(item => item.index))
    const existingPairs = new Set<string>()
    allLines.forEach((line, index) => {
      if (!selectedIndexes.has(index)) existingPairs.add(`${line.service_id}:${line.sub_activity_id ?? ''}`)
    })
    const updates: Selection[] = []
    for (const selection of selections) {
      const { index, line } = selection
      const nextSection = scopeMode === 'assign' ? targetSection : line.hole_section_id
      const nextPhase = scopeMode === 'assign' ? targetPhase : line.phase_id
      const targetLine = {
        ...line,
        activity_id: activityId,
        sub_activity_id: selectedSub.id,
        hole_section_id: nextSection,
        phase_id: nextSection ? nextPhase : null,
        vendor_id: classification === 'Planned' ? null : line.vendor_id,
        party_name: classification === 'Planned'
          ? 'Not Applicable'
          : (selectedSub.responsible_party || line.party_name),
      }
      let selectedRate = baseline.service_rates.find(rate => rate.id === targetLine.baseline_service_rate_id)

      if (classification === 'Planned' && !selectedRate) {
        const rates = baseline.service_rates
          .filter(rate => rate.service_id === targetLine.service_id)
          .filter(rate => !rate.hole_section_id || rate.hole_section_id === targetLine.hole_section_id)
          .filter(rate => !rate.phase_id || rate.phase_id === targetLine.phase_id)
        selectedRate = rates[0]
        if (!selectedRate) {
          setError(`A planned Activity needs a locked AFE rate for every selected service. No compatible rate was found for ${reference.services.find(item => item.id === line.service_id)?.service_code ?? line.service_id}.`)
          return
        }
        targetLine.baseline_service_rate_id = selectedRate.id
        targetLine.charging_basis = selectedRate.charging_basis
        targetLine.charge_category = (selectedRate.charge_category || 'Operation') as DailyCostServiceInput['charge_category']
        targetLine.quantity_unit = rateQuantityUnit(selectedRate.charging_basis, targetLine.charge_category)
        targetLine.currency = selectedRate.currency
      }

      if (selectedRate && selectedRate.service_id !== line.service_id) {
        setError('A selected AFE rate does not match its service. Reopen the affected line and choose its locked rate.'); return
      }
      if (selectedRate?.hole_section_id && selectedRate.hole_section_id !== targetLine.hole_section_id) {
        setError(`The locked AFE rate for ${selectedRate.service_code} is restricted to ${selectedRate.section_label}. Keep the current scope or select the matching section.`)
        return
      }
      if (selectedRate?.phase_id && selectedRate.phase_id !== targetLine.phase_id) {
        setError(`The locked AFE rate for ${selectedRate.service_code} is restricted to ${selectedRate.phase_label}. Keep the current scope or select the matching phase.`)
        return
      }
      if (selectedRate && targetLine.charging_basis !== selectedRate.charging_basis) {
        setError(`The charging basis for ${selectedRate.service_code} must match its saved AFE rate.`)
        return
      }
      if (selectedRate && selectedRate.rate_kind === 'day_rate' && targetLine.charge_category !== selectedRate.charge_category) {
        setError(`The charge category for ${selectedRate.service_code} must match its saved AFE Day Rate.`)
        return
      }
      if (selectedRate && targetLine.currency.toUpperCase() !== selectedRate.currency.toUpperCase()) {
        setError(`The currency for ${selectedRate.service_code} must remain ${selectedRate.currency}, as saved in the AFE.`)
        return
      }
      if (classification === 'Planned' && !selectedRate) {
        setError('A planned service must keep a rate from this AFE’s locked estimate.'); return
      }
      if (classification !== 'Planned' && !selectedRate && targetLine.override_rate === null) {
        setError(`The selected ${classification} Activity needs a justified manual rate for every service without a locked AFE rate.`)
        return
      }
      if (classification !== 'Planned' && !targetLine.vendor_id && !targetLine.party_name.trim()) {
        setError(`The selected ${classification} Activity needs a responsible vendor or party. Choose a sub activity with a responsible party or edit the lines individually.`)
        return
      }
      if (!targetLine.charging_basis) {
        setError('A service charging basis is missing. Edit that line before applying a bulk scope.'); return
      }
      if (targetLine.charging_basis !== 'Day Rate' && !targetLine.hole_section_id) {
        setError('Per-service and per-section rates require a hole section.'); return
      }
      if (!baseline.exchange_rates[targetLine.currency]) {
        setError(`${targetLine.currency || 'The service'} has no conversion factor in the locked AFE currency setup.`)
        return
      }

      const duplicateKey = `${targetLine.service_id}:${targetLine.sub_activity_id ?? ''}`
      if (existingPairs.has(duplicateKey)) {
        const serviceCode = reference.services.find(item => item.id === targetLine.service_id)?.service_code ?? targetLine.service_id
        setError(`Service ${serviceCode} is already selected for this sub activity on this sheet. Choose a different sub activity or deselect one of the duplicate lines.`)
        return
      }
      existingPairs.add(duplicateKey)
      updates.push({ index, line: targetLine })
    }
    onApply(updates)
  }

  const selectedSubIsValid = subActivities.some(item => item.id === subActivityId)
  const invalidScope = scopeMode === 'assign' && (requireSection && !sectionId || Boolean(phaseId && !sectionId))
  const submitDisabled = !selections.length || !activityId || !selectedSubIsValid || invalidScope

  return <FormDialog
    open={open}
    title={`Bulk edit ${selections.length} selected service line(s)`}
    subtitle="Apply one Activity and well sub activity to the selected lines. Optionally assign the same section and phase; each line keeps its locked AFE rate and quantity."
    onClose={onClose}
    onSubmit={apply}
    submitLabel="Apply to selected lines"
    submitDisabled={submitDisabled}
    maxWidth="md"
  >
    <Box display="grid" gap={1.7}>
      <Alert severity="info">
        Planned is derived from the chosen Activity. Planned services require a saved rate from this AFE; UPA/NPT lines without a locked rate need an existing manual override and a responsible party. Conflicting locked section/phase rates are blocked.
      </Alert>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField select required label="Activity" value={activityId} onChange={event => setActivity(event.target.value)}>
          <MenuItem value="">Select an Activity</MenuItem>
          {reference.activities.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}</MenuItem>)}
        </TextField>
        <TextField select required label="Well sub activity" value={subActivityId} disabled={!activityId} onChange={event => setSubActivityId(event.target.value)} helperText="The sub activity must belong to this well and selected Activity.">
          <MenuItem value="">Select a sub activity</MenuItem>
          {subActivities.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}{item.responsible_party ? ` · ${item.responsible_party}` : ''}</MenuItem>)}
        </TextField>
      </Box>
      {activityId && <Typography fontSize={12} color="text.secondary">Classification from this Activity: <strong>{classification}</strong></Typography>}
      <FormControl>
        <FormLabel>Hole section and phase</FormLabel>
        <RadioGroup row value={scopeMode} onChange={event => setScopeMode(event.target.value as ScopeMode)}>
          <FormControlLabel value="keep" control={<Radio size="small"/>} label="Keep each line’s current scope"/>
          <FormControlLabel value="assign" control={<Radio size="small"/>} label="Set one section and phase for all"/>
        </RadioGroup>
      </FormControl>
      {scopeMode === 'assign' && <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField select required={requireSection} label={requireSection ? 'Hole section (required)' : 'Hole section'} value={sectionId} onChange={event => { setSectionId(event.target.value); setPhaseId('') }}>
          {!requireSection && <MenuItem value="">No hole section</MenuItem>}
          {sections.map(section => <MenuItem key={section.hole_section_id} value={section.hole_section_id}>{section.section_code} · {section.section_name}</MenuItem>)}
        </TextField>
        <TextField select label="Phase" value={phaseId} disabled={!sectionId} onChange={event => setPhaseId(event.target.value)} helperText={!sectionId ? 'Choose a section first.' : 'Optional; leave No phase to apply the whole section.'}>
          <MenuItem value="">No phase</MenuItem>
          {selectedSection?.phases.map(phase => <MenuItem key={phase.phase_id} value={phase.phase_id}>{phase.phase_code} · {phase.phase_name}</MenuItem>)}
        </TextField>
      </Box>}
      {error && <Alert severity="error">{error}</Alert>}
      <Typography fontSize={11.5} color="text.secondary">Bulk edits remain a draft until this daily sheet is saved. Preview validates the selection before any changes reach the server.</Typography>
    </Box>
  </FormDialog>
}

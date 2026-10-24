import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Checkbox,
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
import { ActivityAllocationEditor } from './ActivityAllocationEditor'
import { allocateService, allocationErrors, type ActivityAllocation } from '../../lib/dailyAllocations'
import { FormDialog } from '../Common'
import {
  DAILY_ONE_TIME_CATEGORIES,
  deriveClassification,
  type DailyCostBaseline,
  type DailyCostReference,
  type DailyCostServiceInput,
  type DailyQuantityUnit,
} from '../../lib/dailyCost'
import type { DepthUnit } from '../../lib/units'

type Selection = { index: number; line: DailyCostServiceInput; lines?: DailyCostServiceInput[] }
type ScopeMode = 'keep' | 'assign'
type BulkFieldMode = 'keep' | 'assign'

type Props = {
  open: boolean
  selections: Selection[]
  allLines: DailyCostServiceInput[]
  baseline: DailyCostBaseline
  reference: DailyCostReference
  wellId: string
  scope?: 'drilling' | 'completion'
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
  open, selections, allLines, baseline, reference, wellId, scope = 'drilling', onClose, onApply,
}: Props) {
  const [useCurrentRates, setUseCurrentRates] = useState(false)
  const [allocations, setAllocations] = useState<ActivityAllocation[]>([])
  const [activityId, setActivityId] = useState('')
  const [subActivityId, setSubActivityId] = useState('')
  const [scopeMode, setScopeMode] = useState<ScopeMode>('keep')
  const [sectionId, setSectionId] = useState('')
  const [phaseId, setPhaseId] = useState('')
  const [depthMode, setDepthMode] = useState<BulkFieldMode>('keep')
  const [actualDepth, setActualDepth] = useState('')
  const [actualDepthUnit, setActualDepthUnit] = useState<DepthUnit>('m')
  const [quantityMode, setQuantityMode] = useState<BulkFieldMode>('keep')
  const [quantity, setQuantity] = useState('')
  const [quantityUnit, setQuantityUnit] = useState<DailyQuantityUnit>('days')
  const [error, setError] = useState('')

  const subActivities = useMemo(
    () => reference.sub_activities.filter(
      item => item.well_id === wellId && (item.scope ?? 'drilling') === scope && item.activity_id === activityId,
    ),
    [reference.sub_activities, activityId, wellId, scope],
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
    const commonDepth = commonValue(selections.map(item => item.line.actual_depth ?? ''))
    const commonDepthUnit = commonValue(selections.map(item => item.line.actual_depth_unit ?? 'm'))
    const commonQuantity = commonValue(selections.map(item => item.line.quantity))
    const commonQuantityUnit = commonValue(selections.map(item => item.line.quantity_unit))
    setUseCurrentRates(false)
    setAllocations([])
    setActivityId(commonActivity ?? '')
    setSubActivityId(commonSub ?? '')
    setScopeMode('keep')
    setSectionId(commonSection ?? '')
    setPhaseId(commonPhase ?? '')
    setDepthMode('keep')
    setActualDepth(commonDepth ?? '')
    setActualDepthUnit(commonDepthUnit ?? 'm')
    setQuantityMode('keep')
    setQuantity(commonQuantity ?? '')
    setQuantityUnit(commonQuantityUnit ?? 'days')
    setError('')
  }, [open, selections])

  const setActivity = (nextActivityId: string) => {
    setActivityId(nextActivityId)
    if (!reference.sub_activities.some(item =>
      item.id === subActivityId && item.well_id === wellId && (item.scope ?? 'drilling') === scope && item.activity_id === nextActivityId,
    )) setSubActivityId('')
    setError('')
  }

  const currentRateLine = (line: DailyCostServiceInput): DailyCostServiceInput => {
    if (!useCurrentRates) return line
    const section = allocations[0]?.hole_section_id || (scopeMode === 'assign' ? sectionId : line.hole_section_id)
    const phase = allocations[0]?.phase_id || (scopeMode === 'assign' ? phaseId : line.phase_id)
    const rates = baseline.service_rates.filter(rate => rate.is_current !== false && rate.service_id === line.service_id)
      .filter(rate => !rate.hole_section_id || rate.hole_section_id === section)
      .filter(rate => !rate.phase_id || rate.phase_id === phase)
    const rate = rates.find(rate => rate.charge_category === line.charge_category)
    if (!rate) throw new Error('No compatible current AFE rate exists for a selected service. Edit that service individually.')
    return { ...line, baseline_service_rate_id: rate.id, charging_basis: rate.charging_basis,
      charge_category: rate.charge_category as DailyCostServiceInput['charge_category'], currency: rate.currency,
      exchange_rate: rate.currency === line.currency ? line.exchange_rate : null,
      override_rate: null, override_reason: '', quantity_unit: rateQuantityUnit(rate.charging_basis, rate.charge_category) }
  }
  const timeBased = selections.some(({ line }) => useCurrentRates ? baseline.service_rates.some(rate => rate.is_current !== false && rate.service_id === line.service_id && rate.charging_basis === 'Day Rate' && !DAILY_ONE_TIME_CATEGORIES.includes(rate.charge_category as DailyCostServiceInput['charge_category'])) : line.charging_basis === 'Day Rate' && !DAILY_ONE_TIME_CATEGORIES.includes(line.charge_category))

  const apply = () => {
    setError('')
    if (allocations.length) {
      const errors = allocationErrors(allocations, reference, wellId, scope, timeBased)
      if (errors.length) { setError(errors[0]); return }
      try {
        onApply(selections.map(selection => ({ ...selection, lines: allocateService(currentRateLine(selection.line), allocations, baseline, reference) })))
      } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not allocate services.') }
      return
    }
    if (!activityId) { setError('Select one Activity for the selected service lines.'); return }
    const selectedSub = reference.sub_activities.find(item =>
      item.id === subActivityId && item.well_id === wellId && (item.scope ?? 'drilling') === scope && item.activity_id === activityId,
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
    if (depthMode === 'assign') {
      const depth = Number(actualDepth)
      if (actualDepth.trim() === '' || !Number.isFinite(depth) || depth < 0) {
        setError('Enter a valid non-negative actual depth for the selected service lines.'); return
      }
    }
    if (quantityMode === 'assign') {
      const chargedQuantity = Number(quantity)
      if (quantity.trim() === '' || !Number.isFinite(chargedQuantity) || chargedQuantity <= 0 || chargedQuantity > 1_000_000) {
        setError('Enter a charged quantity greater than zero and no more than 1,000,000.'); return
      }
      if (quantityUnit === 'hours' && chargedQuantity > 24) {
        setError('Charged hours cannot exceed 24; enter the equivalent quantity in days instead.'); return
      }
    }

    const selectedIndexes = new Set(selections.map(item => item.index))
    const existingPairs = new Set<string>()
    allLines.forEach((line, index) => {
      if (!selectedIndexes.has(index)) existingPairs.add(`${line.service_id}:${line.sub_activity_id ?? ''}:${line.charge_category}:${line.hole_section_id}:${line.phase_id}`)
    })
    const updates: Selection[] = []
    for (const selection of selections) {
      const index = selection.index
      let line: DailyCostServiceInput
      try { line = currentRateLine(selection.line) }
      catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not select current rates.'); return }
      const nextSection = scopeMode === 'assign' ? targetSection : line.hole_section_id
      const nextPhase = scopeMode === 'assign' ? targetPhase : line.phase_id
      const targetLine = {
        ...line,
        activity_id: activityId,
        sub_activity_id: selectedSub.id,
        hole_section_id: nextSection,
        phase_id: nextSection ? nextPhase : null,
        actual_depth: depthMode === 'assign' ? actualDepth : line.actual_depth,
        actual_depth_unit: depthMode === 'assign' ? actualDepthUnit : line.actual_depth_unit,
        quantity: quantityMode === 'assign' ? quantity : line.quantity,
        quantity_unit: quantityMode === 'assign' ? quantityUnit : line.quantity_unit,
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
      // An explicit bulk quantity choice wins over the basis-derived default.
      if (quantityMode === 'assign') {
        targetLine.quantity = quantity
        targetLine.quantity_unit = quantityUnit
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

      const duplicateKey = `${targetLine.service_id}:${targetLine.sub_activity_id ?? ''}:${targetLine.charge_category}:${targetLine.hole_section_id}:${targetLine.phase_id}`
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
  const invalidDepth = depthMode === 'assign' && (actualDepth.trim() === '' || !Number.isFinite(Number(actualDepth)) || Number(actualDepth) < 0)
  const invalidQuantity = quantityMode === 'assign' && (quantity.trim() === '' || !Number.isFinite(Number(quantity)) || Number(quantity) <= 0 || Number(quantity) > 1_000_000 || quantityUnit === 'hours' && Number(quantity) > 24)
  const submitDisabled = !allocations.length && (!selections.length || !activityId || !selectedSubIsValid || invalidScope || invalidDepth || invalidQuantity)

  return <FormDialog
    open={open}
    title={`Bulk edit ${selections.length} selected service line(s)`}
    subtitle="Allocate multiple Activities and sub activities to selected services, or apply common criteria. Optionally assign one scope, actual depth, charged quantity and unit; each line keeps its locked AFE rate."
    onClose={onClose}
    onSubmit={apply}
    submitLabel="Apply to selected lines"
    submitDisabled={submitDisabled}
    maxWidth="md"
  >
    <Box display="grid" gap={1.7}>
      <FormControlLabel control={<Checkbox checked={useCurrentRates} onChange={event => setUseCurrentRates(event.target.checked)}/>} label="Use current AFE service rates and charging basis (replaces manual rate overrides)"/>
      <ActivityAllocationEditor value={allocations} onChange={setAllocations} baseline={baseline} reference={reference} wellId={wellId} scope={scope} timeBased={timeBased}/>
      {!!allocations.length && <Alert severity="info">The allocation rows replace the common scope and quantity controls below.</Alert>}
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
      <FormControl>
        <FormLabel>Actual depth</FormLabel>
        <RadioGroup row value={depthMode} onChange={event => setDepthMode(event.target.value as BulkFieldMode)}>
          <FormControlLabel value="keep" control={<Radio size="small"/>} label="Keep each line’s current depth"/>
          <FormControlLabel value="assign" control={<Radio size="small"/>} label="Set one depth for all"/>
        </RadioGroup>
      </FormControl>
      {depthMode === 'assign' && <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField required type="number" label="Actual depth" value={actualDepth} onChange={event => setActualDepth(event.target.value)} inputProps={{ min: 0, step: 'any' }} helperText="The last entered depth for the date and section governs the register."/>
        <TextField select label="Depth unit" value={actualDepthUnit} onChange={event => setActualDepthUnit(event.target.value as DepthUnit)} helperText="Feet are standardized to metres using ft ÷ 3.281.">
          <MenuItem value="m">Metres (m)</MenuItem>
          <MenuItem value="ft">Feet (ft)</MenuItem>
        </TextField>
      </Box>}
      <FormControl>
        <FormLabel>Charged quantity and unit</FormLabel>
        <RadioGroup row value={quantityMode} onChange={event => setQuantityMode(event.target.value as BulkFieldMode)}>
          <FormControlLabel value="keep" control={<Radio size="small"/>} label="Keep each line’s current quantity"/>
          <FormControlLabel value="assign" control={<Radio size="small"/>} label="Set one quantity and unit for all"/>
        </RadioGroup>
      </FormControl>
      {quantityMode === 'assign' && <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField required type="number" label="Charged quantity" value={quantity} onChange={event => setQuantity(event.target.value)} inputProps={{ min: 0.0000000001, max: 1_000_000, step: 'any' }} helperText={quantityUnit === 'hours' ? 'Maximum 24 hours per daily sheet.' : 'Applied to every selected service line.'}/>
        <TextField select label="Quantity unit" value={quantityUnit} onChange={event => setQuantityUnit(event.target.value as DailyQuantityUnit)}>
          {reference.quantity_units.map(unit => <MenuItem key={unit} value={unit}>{unit}</MenuItem>)}
        </TextField>
      </Box>}
      {error && <Alert severity="error">{error}</Alert>}
      <Typography fontSize={11.5} color="text.secondary">Bulk edits remain a draft until this daily sheet is saved. Preview validates the selection before any changes reach the server.</Typography>
    </Box>
  </FormDialog>
}

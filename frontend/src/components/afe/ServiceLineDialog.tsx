import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, MenuItem, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import {
  CHARGE_CATEGORIES, CHARGING_BASES, ONE_TIME_CATEGORIES, daysText, emptyServiceLine, phaseOptions, scopeRows, sectionOptions, serviceProblems,
  toDays, type AfeReference, type ChargeCategory, type ChargingBasis, type QuantityUnit, type ServiceLineInput, type WellScope,
} from '../../lib/afe'
import { defaultCurrencyCode } from '../../lib/masterData'
import { ServicePicker } from './LinePickers'

const BASIS_HINT: Record<ChargingBasis, string> = {
  'Day Rate': 'Planned days × unit rate for each day-based category. One-time charges (mobilization, demobilization, fixed) are added once.',
  'Per Service Rate': 'One lump sum for this service in the chosen section and phase.',
  'Per Section Rate': 'A separate amount for each section (and phase) of the well plan.',
}

const DAY_CATEGORIES = CHARGE_CATEGORIES.filter(category => !ONE_TIME_CATEGORIES.includes(category))

type Props = {
  open: boolean
  initial: ServiceLineInput | null
  scope: WellScope
  reference: AfeReference
  onClose: () => void
  onSave: (line: ServiceLineInput) => void
}

// Adds or edits one service line. A line is priced from the well plan it is scoped to.
export function ServiceLineDialog({ open, initial, scope, reference, onClose, onSave }: Props) {
  const [line, setLine] = useState<ServiceLineInput>(() => emptyServiceLine())
  const [baseline, setBaseline] = useState<ServiceLineInput | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [chargeCategory, setChargeCategory] = useState<ChargeCategory>('Standby')
  const [chargeQuantity, setChargeQuantity] = useState('')
  const [chargeUnit, setChargeUnit] = useState<QuantityUnit>('days')

  useEffect(() => {
    if (!open) return
    const next = initial ? structuredClone(initial) : emptyServiceLine()
    // New lines start in the workspace default currency, so it rarely has to be picked.
    if (!next.currency) next.currency = defaultCurrencyCode(reference.currencies)
    setLine(next)
    setBaseline(next)
    setSubmitted(false)
    setChargeQuantity('')
    setChargeCategory('Standby')
    setChargeUnit('days')
  }, [open, initial, reference.currencies])
  // Unsaved-changes guard: everything typed or picked in this dialog is protected.
  const dirty = baseline !== null && JSON.stringify(line) !== JSON.stringify(baseline)

  const sections = useMemo(() => sectionOptions(scope), [scope])
  const phases = useMemo(() => phaseOptions(scope, line.hole_section_id), [scope, line.hole_section_id])
  const problems = serviceProblems(line)
  const currencies = reference.currencies

  const update = (patch: Partial<ServiceLineInput>) => setLine(current => ({ ...current, ...patch }))

  const setBasis = (basis: ChargingBasis | null) => {
    if (!basis) return
    setLine(current => ({
      ...current,
      charging_basis: basis,
      // Per-section lines carry their scope in each section row, so they have no single section.
      hole_section_id: basis === 'Per Section Rate' ? null : current.hole_section_id,
      phase_id: basis === 'Per Section Rate' ? null : current.phase_id,
    }))
  }

  const setRate = (category: ChargeCategory, value: string) => {
    setLine(current => {
      const others = current.rates.filter(rate => rate.category !== category)
      return { ...current, rates: value === '' ? others : [...others, { category, unit_rate: value }] }
    })
  }
  const rateFor = (category: ChargeCategory) => line.rates.find(rate => rate.category === category)?.unit_rate ?? ''

  const addCharge = () => {
    if (!chargeQuantity.trim() || Number(chargeQuantity) <= 0) return
    setLine(current => ({
      ...current,
      charges: [...current.charges.filter(charge => charge.category !== chargeCategory), { category: chargeCategory, quantity: chargeQuantity.trim(), quantity_unit: chargeUnit }],
    }))
    setChargeQuantity('')
  }
  const removeCharge = (category: ChargeCategory) => setLine(current => ({ ...current, charges: current.charges.filter(charge => charge.category !== category) }))

  const sectionRows = useMemo(() => scopeRows(scope), [scope])
  const sectionAmount = (sectionId: string, phaseId: string | null) => line.section_rates.find(rate => rate.hole_section_id === sectionId && rate.phase_id === phaseId)?.amount ?? ''
  const setSectionAmount = (sectionId: string, phaseId: string | null, value: string) => {
    setLine(current => {
      const others = current.section_rates.filter(rate => !(rate.hole_section_id === sectionId && rate.phase_id === phaseId))
      return { ...current, section_rates: value === '' ? others : [...others, { hole_section_id: sectionId, phase_id: phaseId, amount: value }] }
    })
  }

  const save = () => {
    setSubmitted(true)
    if (problems.length) return
    // Keep only meaningful entries so the saved line stays tidy.
    onSave({
      ...line,
      remarks: line.remarks.trim(),
      rates: line.rates.filter(rate => rate.unit_rate !== ''),
      charges: line.charges.filter(charge => Number(charge.quantity) > 0),
      section_rates: line.section_rates.filter(rate => Number(rate.amount) > 0),
      service_amount: line.charging_basis === 'Per Service Rate' ? line.service_amount || '0' : '0',
      hole_section_id: line.charging_basis === 'Per Section Rate' ? null : line.hole_section_id || null,
      phase_id: line.charging_basis === 'Per Section Rate' ? null : line.phase_id || null,
    })
  }

  const showProblems = submitted && problems.length > 0

  return <FormDialog
    open={open}
    title={initial ? 'Edit service line' : 'Add service'}
    subtitle="Choose a service from Master Data, how it is charged, and the rates. Sections and phases come from the well plan."
    onClose={onClose}
    onSubmit={save}
    dirty={dirty}
    submitLabel={initial ? 'Save line' : 'Add service'}
    maxWidth="md"
  >
    <Box display="grid" gap={2}>
      <ServicePicker value={line.service_id} options={reference.services} onChange={id => update({ service_id: id })} error={submitted && !line.service_id}/>

      <Box>
        <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Charging basis</Typography>
        <ToggleButtonGroup exclusive size="small" value={line.charging_basis} onChange={(_event, basis: ChargingBasis | null) => setBasis(basis)} fullWidth>
          {CHARGING_BASES.map(basis => <ToggleButton key={basis} value={basis} sx={{ textTransform: 'none', fontWeight: 700 }}>{basis}</ToggleButton>)}
        </ToggleButtonGroup>
        <Typography fontSize={12} color="text.secondary" mt={.8}>{BASIS_HINT[line.charging_basis]}</Typography>
      </Box>

      <Box display="grid" gap={1.6} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        {line.charging_basis !== 'Per Section Rate' && <TextField
          select label={line.charging_basis === 'Per Service Rate' ? 'Section (required)' : 'Section'} value={line.hole_section_id ?? ''}
          onChange={event => update({ hole_section_id: event.target.value || null, phase_id: null })}
          helperText={line.charging_basis === 'Day Rate' ? 'All sections splits the amount by each section’s planned days.' : 'Section from the well plan.'}
          error={submitted && line.charging_basis === 'Per Service Rate' && !line.hole_section_id}
        >
          {line.charging_basis === 'Day Rate' && <MenuItem value="">All sections (split by planned days)</MenuItem>}
          {sections.map(section => <MenuItem key={section.id} value={section.id}>{section.label}</MenuItem>)}
        </TextField>}
        {line.charging_basis !== 'Per Section Rate' && <TextField
          select label="Phase" value={line.phase_id ?? ''} onChange={event => update({ phase_id: event.target.value || null })}
          disabled={!line.hole_section_id}
          helperText={!line.hole_section_id ? 'Choose a section first.' : 'Optional. Limits the charge to one phase of the section.'}
        >
          <MenuItem value="">All phases</MenuItem>
          {phases.map(phase => <MenuItem key={phase.id} value={phase.id}>{phase.label} · {daysText(phase.days)}</MenuItem>)}
        </TextField>}
        <TextField
          select label="Currency" required value={line.currency} onChange={event => update({ currency: event.target.value })}
          error={submitted && !line.currency}
          helperText="From Master Data → Currency. Lines in different currencies are totalled separately."
        >
          {currencies.map(currency => <MenuItem key={currency.code} value={currency.code}>{currency.code} · {currency.name}</MenuItem>)}
        </TextField>
        <TextField label="Remarks" value={line.remarks} onChange={event => update({ remarks: event.target.value })} inputProps={{ maxLength: 500 }}/>
      </Box>

      {line.charging_basis === 'Day Rate' && <Box display="grid" gap={1.6}>
        <Box>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Unit rates</Typography>
          <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
            {CHARGE_CATEGORIES.map(category => <TextField
              key={category}
              size="small"
              label={category}
              value={rateFor(category)}
              onChange={event => setRate(category, event.target.value.replace(/[^0-9.]/g, ''))}
              helperText={ONE_TIME_CATEGORIES.includes(category) ? 'Charged once per line' : 'Per day'}
              inputProps={{ inputMode: 'decimal' }}
            />)}
          </Box>
        </Box>
        <Box>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Days for day-based charges (optional)</Typography>
          <Typography fontSize={12} color="text.secondary" mb={1}>
            Operation uses the planned days of the chosen scope unless you enter Operation days here. Enter days (for example 0.73) or hours (converted at 24 hours per day).
          </Typography>
          <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.4fr 1fr 1fr auto' }, alignItems: 'start' }}>
            <TextField select size="small" label="Category" value={chargeCategory} onChange={event => setChargeCategory(event.target.value as ChargeCategory)}>
              {DAY_CATEGORIES.map(category => <MenuItem key={category} value={category}>{category}</MenuItem>)}
            </TextField>
            <TextField size="small" label="Quantity" value={chargeQuantity} onChange={event => setChargeQuantity(event.target.value.replace(/[^0-9.]/g, ''))} inputProps={{ inputMode: 'decimal' }}
              helperText={chargeQuantity ? `= ${daysText(toDays(chargeQuantity, chargeUnit))}` : ' '}/>
            <TextField select size="small" label="Unit" value={chargeUnit} onChange={event => setChargeUnit(event.target.value as QuantityUnit)}>
              <MenuItem value="days">Days</MenuItem>
              <MenuItem value="hours">Hours</MenuItem>
            </TextField>
            <Button variant="outlined" onClick={addCharge} disabled={!chargeQuantity || Number(chargeQuantity) <= 0} sx={{ height: 40 }}>Add</Button>
          </Box>
          {line.charges.length > 0 && <Box mt={1} display="grid" gap={.6}>
            {line.charges.map(charge => <Box key={charge.category} display="flex" justifyContent="space-between" alignItems="center" sx={{ border: 1, borderColor: 'divider', borderRadius: 1, px: 1.2, py: .6 }}>
              <Typography fontSize={12.5}>{charge.category} · {charge.quantity} {charge.quantity_unit} = {daysText(toDays(charge.quantity, charge.quantity_unit))}</Typography>
              <Button size="small" color="error" onClick={() => removeCharge(charge.category)}>Remove</Button>
            </Box>)}
          </Box>}
        </Box>
      </Box>}

      {line.charging_basis === 'Per Service Rate' && <TextField
        label="Amount for this service" required value={line.service_amount}
        onChange={event => update({ service_amount: event.target.value.replace(/[^0-9.]/g, '') })}
        inputProps={{ inputMode: 'decimal' }} error={submitted && toNumberSafe(line.service_amount) <= 0}
        helperText="Lump sum applied once for the chosen section and phase."
      />}

      {line.charging_basis === 'Per Section Rate' && <Box>
        <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Rate for each section and phase</Typography>
        <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1.5, overflow: 'hidden' }}>
          {sectionRows.map(row => <Box key={row.key} display="grid" alignItems="center" gap={1} px={1.4} py={.9} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.3fr 1fr 0.8fr 1fr' }, borderBottom: 1, borderColor: 'divider', '&:last-child': { borderBottom: 0 } }}>
            <Typography fontSize={13} fontWeight={700}>{row.section}</Typography>
            <Typography fontSize={12.5} color="text.secondary">{row.phase}</Typography>
            <Typography fontSize={12} color="text.secondary">{daysText(row.days)}</Typography>
            <TextField size="small" label="Amount" value={sectionAmount(row.sectionId, row.phaseId)} onChange={event => setSectionAmount(row.sectionId, row.phaseId, event.target.value.replace(/[^0-9.]/g, ''))} inputProps={{ inputMode: 'decimal' }}/>
          </Box>)}
        </Box>
        <Typography fontSize={12} color="text.secondary" mt={.8}>Leave a row empty to skip that section.</Typography>
      </Box>}

      {showProblems && <Alert severity="error">
        {problems.map(problem => <Typography key={problem} fontSize={12.5}>{problem}</Typography>)}
      </Alert>}
    </Box>
  </FormDialog>
}

function toNumberSafe(value: string): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

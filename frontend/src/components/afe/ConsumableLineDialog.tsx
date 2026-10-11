import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, MenuItem, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import {
  CONSUMABLE_CATEGORIES, LUMP_SUM_CATEGORIES, amountText, consumableProblems, emptyConsumableLine, phaseOptions, sectionOptions,
  type AfeReference, type ConsumableCategory, type ConsumableLineInput, type WellScope,
} from '../../lib/afe'
import { DrillBitPicker, FactPanel } from './LinePickers'

const CATEGORY_HINT: Record<ConsumableCategory, string> = {
  'Mud Chemicals': 'Enter the estimated lump sum for the section. Daily consumption is not deducted automatically.',
  'Cement Additives': 'Enter the estimated lump sum for the section.',
  Fuel: 'Enter the estimated lump sum for the section.',
  'Drill Bits': 'Price per bit from Master Data. The currency follows the drill bit’s master record.',
}

type Props = {
  open: boolean
  initial: ConsumableLineInput | null
  scope: WellScope
  reference: AfeReference
  onClose: () => void
  onSave: (line: ConsumableLineInput) => void
}

export function ConsumableLineDialog({ open, initial, scope, reference, onClose, onSave }: Props) {
  const [line, setLine] = useState<ConsumableLineInput>(() => emptyConsumableLine())
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    if (!open) return
    setLine(initial ? structuredClone(initial) : emptyConsumableLine())
    setSubmitted(false)
  }, [open, initial])

  const sections = useMemo(() => sectionOptions(scope), [scope])
  const phases = useMemo(() => phaseOptions(scope, line.hole_section_id), [scope, line.hole_section_id])
  const bit = reference.drill_bits.find(item => item.id === line.drill_bit_id) ?? null
  const isBit = line.category === 'Drill Bits'
  const problems = consumableProblems(line)

  const update = (patch: Partial<ConsumableLineInput>) => setLine(current => ({ ...current, ...patch }))

  const setCategory = (category: ConsumableCategory | null) => {
    if (!category) return
    setLine(current => ({
      ...current,
      category,
      // Switching kind clears the fields that belong to the other kind.
      drill_bit_id: category === 'Drill Bits' ? current.drill_bit_id : null,
      quantity: category === 'Drill Bits' ? (current.quantity && current.quantity !== '1' ? current.quantity : '1') : '1',
      override_rate: category === 'Drill Bits' ? current.override_rate : null,
      estimated_amount: category === 'Drill Bits' ? null : current.estimated_amount ?? '',
      currency: category === 'Drill Bits' ? (reference.drill_bits.find(item => item.id === current.drill_bit_id)?.currency ?? '') : current.currency,
    }))
  }

  const pickBit = (id: string) => {
    const picked = reference.drill_bits.find(item => item.id === id)
    update({ drill_bit_id: id || null, currency: picked?.currency ?? '' })
  }

  const save = () => {
    setSubmitted(true)
    if (problems.length) return
    onSave({
      ...line,
      remarks: line.remarks.trim(),
      quantity: isBit ? line.quantity : '1',
      override_rate: isBit ? (line.override_rate || null) : null,
      estimated_amount: isBit ? null : (line.estimated_amount ?? '0'),
      // Drill bits take the currency of their master record; lump sums use the chosen currency.
      currency: isBit ? (bit?.currency ?? line.currency) : line.currency,
      drill_bit_id: isBit ? line.drill_bit_id : null,
      phase_id: line.phase_id || null,
    })
  }

  return <FormDialog
    open={open}
    title={initial ? 'Edit consumable line' : 'Add consumable'}
    subtitle="Mud chemicals, cement additives and fuel are estimated per section. Drill bits are priced per bit."
    onClose={onClose}
    onSubmit={save}
    submitLabel={initial ? 'Save line' : 'Add consumable'}
    maxWidth="md"
  >
    <Box display="grid" gap={2}>
      <Box>
        <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Category</Typography>
        <ToggleButtonGroup exclusive size="small" value={line.category} onChange={(_event, category: ConsumableCategory | null) => setCategory(category)} fullWidth>
          {CONSUMABLE_CATEGORIES.map(category => <ToggleButton key={category} value={category} sx={{ textTransform: 'none', fontWeight: 700 }}>{category}</ToggleButton>)}
        </ToggleButtonGroup>
        <Typography fontSize={12} color="text.secondary" mt={.8}>{CATEGORY_HINT[line.category]}</Typography>
      </Box>

      <Box display="grid" gap={1.6} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField
          select label="Hole section" required value={line.hole_section_id}
          onChange={event => update({ hole_section_id: event.target.value, phase_id: null })}
          error={submitted && !line.hole_section_id}
          helperText="From the well plan."
        >
          {sections.map(section => <MenuItem key={section.id} value={section.id}>{section.label}</MenuItem>)}
        </TextField>
        <TextField
          select label="Phase" value={line.phase_id ?? ''} onChange={event => update({ phase_id: event.target.value || null })}
          disabled={!line.hole_section_id}
          helperText={!line.hole_section_id ? 'Choose a section first.' : 'Optional.'}
        >
          <MenuItem value="">All phases</MenuItem>
          {phases.map(phase => <MenuItem key={phase.id} value={phase.id}>{phase.label}</MenuItem>)}
        </TextField>

        {isBit ? <Box sx={{ gridColumn: '1 / -1' }}>
          <DrillBitPicker value={line.drill_bit_id ?? ''} options={reference.drill_bits} onChange={pickBit} error={submitted && !line.drill_bit_id}/>
        </Box> : null}

        {isBit && bit && <Box sx={{ gridColumn: '1 / -1' }}>
          <FactPanel rows={[
            { label: 'Make', value: bit.manufacturer_name },
            { label: 'Bit type', value: bit.bit_type },
            { label: 'Size', value: bit.size },
            { label: 'IADC code', value: bit.iadc_code },
            { label: 'Model no.', value: bit.model_no },
            { label: 'Serial no.', value: bit.serial_number },
            { label: 'Description', value: bit.description },
            { label: 'Master rate', value: amountText(bit.captured_rate, bit.currency) },
          ]}/>
        </Box>}

        {isBit && <>
          <TextField
            label="Number of bits" required value={line.quantity}
            onChange={event => update({ quantity: event.target.value.replace(/[^0-9.]/g, '') })}
            inputProps={{ inputMode: 'decimal' }}
            error={submitted && Number(line.quantity) <= 0}
            helperText="Bits planned for this section."
          />
          <TextField
            label="Override unit rate (optional)"
            value={line.override_rate ?? ''}
            onChange={event => update({ override_rate: event.target.value.replace(/[^0-9.]/g, '') || null })}
            inputProps={{ inputMode: 'decimal' }}
            helperText={bit ? `Leave empty to use the master rate. Override is in ${bit.currency || 'the master currency'}.` : 'Leave empty to use the master rate.'}
          />
          <TextField label="Currency" value={bit?.currency ?? ''} disabled helperText="Follows the drill bit’s master record."/>
        </>}

        {!isBit && <>
          <TextField
            label="Estimated amount" required value={line.estimated_amount ?? ''}
            onChange={event => update({ estimated_amount: event.target.value.replace(/[^0-9.]/g, '') })}
            inputProps={{ inputMode: 'decimal' }}
            error={submitted && (line.estimated_amount === null || line.estimated_amount === '')}
            helperText="Lump sum for this section and phase."
          />
          <TextField
            select label="Currency" required value={line.currency} onChange={event => update({ currency: event.target.value })}
            error={submitted && !line.currency}
            helperText="From Master Data → Currency."
          >
            {reference.currencies.map(currency => <MenuItem key={currency.code} value={currency.code}>{currency.code} · {currency.name}</MenuItem>)}
          </TextField>
        </>}

        <TextField label="Remarks" value={line.remarks} onChange={event => update({ remarks: event.target.value })} inputProps={{ maxLength: 500 }} sx={{ gridColumn: '1 / -1' }}/>
      </Box>

      {submitted && problems.length > 0 && <Alert severity="error">
        {problems.map(problem => <Typography key={problem} fontSize={12.5}>{problem}</Typography>)}
      </Alert>}
      {!isBit && <Typography fontSize={11.5} color="text.secondary">Lump-sum categories: {LUMP_SUM_CATEGORIES.join(', ')}.</Typography>}
    </Box>
  </FormDialog>
}

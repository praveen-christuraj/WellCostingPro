import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, MenuItem, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import {
  LUMP_SUM_CATEGORIES, amountText, daysText, emptyConsumableLine, emptyServiceLine, newKey, scopeRows, toNumber,
  type AfeReference, type ConsumableCategory, type ConsumableLineInput, type ServiceLineInput, type WellScope,
} from '../../lib/afe'
import { defaultCurrencyCode } from '../../lib/masterData'
import { ServicePicker } from './LinePickers'

type Mode = 'consumable' | 'service'

export type BulkResult = { services: ServiceLineInput[]; consumables: ConsumableLineInput[] }

type Props = {
  open: boolean
  initialMode?: Mode
  scope: WellScope
  reference: AfeReference
  onClose: () => void
  onApply: (result: BulkResult) => void
}

// Method 2: enter one amount per hole section (and phase) of the well plan, in one pass.
// Each filled row becomes one line, so the result stays editable line by line afterwards.
export function BulkEstimateDialog({ open, initialMode = 'consumable', scope, reference, onClose, onApply }: Props) {
  const [mode, setMode] = useState<Mode>(initialMode)
  const [category, setCategory] = useState<ConsumableCategory>('Mud Chemicals')
  const [serviceId, setServiceId] = useState('')
  const [currency, setCurrency] = useState('')
  const [amounts, setAmounts] = useState<Record<string, string>>({})
  const [baseline, setBaseline] = useState('')
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    if (!open) return
    setMode(initialMode)
    setCategory('Mud Chemicals')
    setServiceId('')
    // Start in the workspace default currency so it rarely has to be picked.
    const initialCurrency = defaultCurrencyCode(reference.currencies)
    setCurrency(initialCurrency)
    setBaseline(initialCurrency)
    setAmounts({})
    setSubmitted(false)
  }, [open, reference.currencies])
  // Unsaved-changes guard: amounts typed or the currency changed are protected.
  const dirty = currency !== baseline || Boolean(serviceId) || Object.values(amounts).some(value => toNumber(value) > 0)

  const rows = useMemo(() => scopeRows(scope), [scope])
  const filled = rows.filter(row => toNumber(amounts[row.key]) > 0)
  const total = filled.reduce((sum, row) => sum + toNumber(amounts[row.key]), 0)
  const problems: string[] = []
  if (!filled.length) problems.push('Enter an amount for at least one section.')
  if (!currency) problems.push('Select the currency.')
  if (mode === 'service' && !serviceId) problems.push('Select the service to rate per section.')

  const setAmount = (key: string, value: string) => setAmounts(current => ({ ...current, [key]: value.replace(/[^0-9.]/g, '') }))

  const apply = () => {
    setSubmitted(true)
    if (problems.length) return
    if (mode === 'consumable') {
      const consumables = filled.map(row => ({
        ...emptyConsumableLine(category),
        client_key: newKey(),
        hole_section_id: row.sectionId,
        phase_id: row.phaseId,
        estimated_amount: amounts[row.key],
        currency,
        remarks: 'Bulk estimate',
      }))
      onApply({ services: [], consumables })
      return
    }
    const service = {
      ...emptyServiceLine('Per Section Rate'),
      service_id: serviceId,
      currency,
      remarks: 'Bulk estimate per section',
      section_rates: filled.map(row => ({ hole_section_id: row.sectionId, phase_id: row.phaseId, amount: amounts[row.key] })),
    }
    onApply({ services: [service], consumables: [] })
  }

  return <FormDialog
    open={open}
    title="Bulk estimate by section"
    subtitle="Enter amounts for each hole section and phase from the well plan. Empty rows are skipped."
    onClose={onClose}
    onSubmit={apply}
    dirty={dirty}
    submitLabel={mode === 'consumable' ? 'Add lines' : 'Add service line'}
    maxWidth="md"
  >
    <Box display="grid" gap={2}>
      <Box display="grid" gap={1.6} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <Box>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7} mb={.8}>Estimate type</Typography>
          <ToggleButtonGroup exclusive size="small" value={mode} onChange={(_event, next: Mode | null) => next && setMode(next)} fullWidth>
            <ToggleButton value="consumable" sx={{ textTransform: 'none', fontWeight: 700 }}>Consumable lump sums</ToggleButton>
            <ToggleButton value="service" sx={{ textTransform: 'none', fontWeight: 700 }}>Service per section</ToggleButton>
          </ToggleButtonGroup>
        </Box>
        {mode === 'consumable'
          ? <TextField select label="Consumable category" value={category} onChange={event => setCategory(event.target.value as ConsumableCategory)} helperText="One line is created per filled row.">
            {LUMP_SUM_CATEGORIES.map(item => <MenuItem key={item} value={item}>{item}</MenuItem>)}
          </TextField>
          : <Box sx={{ minWidth: 0 }}><ServicePicker value={serviceId} options={reference.services} onChange={setServiceId} error={submitted && !serviceId}/></Box>}
        <TextField select label="Currency" required value={currency} onChange={event => setCurrency(event.target.value)} error={submitted && !currency} helperText="Applied to every filled row.">
          {reference.currencies.map(item => <MenuItem key={item.code} value={item.code}>{item.code} · {item.name}</MenuItem>)}
        </TextField>
      </Box>

      <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1.5, overflow: 'hidden' }}>
        <Box display="grid" gap={1} px={1.4} py={.8} sx={{ gridTemplateColumns: '1.3fr 1fr .8fr 1fr', bgcolor: 'action.hover' }}>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase">Section</Typography>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase">Phase</Typography>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase">Planned</Typography>
          <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase">Amount</Typography>
        </Box>
        {rows.length === 0 && <Typography p={2} fontSize={13} color="text.secondary">This well has no sections yet. Save its plan in Rig & Well Management first.</Typography>}
        {rows.map(row => <Box key={row.key} display="grid" alignItems="center" gap={1} px={1.4} py={.8} sx={{ gridTemplateColumns: '1.3fr 1fr .8fr 1fr', borderTop: 1, borderColor: 'divider' }}>
          <Typography fontSize={13} fontWeight={700}>{row.section}</Typography>
          <Typography fontSize={12.5} color="text.secondary">{row.phase}</Typography>
          <Typography fontSize={12} color="text.secondary">{daysText(row.days)}</Typography>
          <TextField size="small" value={amounts[row.key] ?? ''} onChange={event => setAmount(row.key, event.target.value)} inputProps={{ inputMode: 'decimal', 'aria-label': `Amount for ${row.section} ${row.phase}` }}/>
        </Box>)}
      </Box>

      <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
        <Typography fontSize={13} color="text.secondary">{filled.length} row{filled.length === 1 ? '' : 's'} filled</Typography>
        <Typography fontSize={14} fontWeight={800}>Total {amountText(total, currency)}</Typography>
      </Box>
      {submitted && problems.length > 0 && <Alert severity="error">{problems.map(problem => <Typography key={problem} fontSize={12.5}>{problem}</Typography>)}</Alert>}
    </Box>
  </FormDialog>
}

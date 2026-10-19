import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Divider,
  IconButton,
  MenuItem,
  Paper,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { AddRounded, DeleteOutlineRounded } from '@mui/icons-material'
import { FormDialog } from '../Common'
import {
  CONSUMABLE_CATEGORIES,
  LUMP_SUM_CATEGORIES,
  amountText,
  newKey,
  phaseOptions,
  sectionOptions,
  toNumber,
  type AfeReference,
  type ConsumableCategory,
  type ConsumableLineInput,
  type WellScope,
} from '../../lib/afe'
import { defaultCurrencyCode } from '../../lib/masterData'
import { DrillBitPicker, FactPanel } from './LinePickers'

const CATEGORY_HINT: Record<ConsumableCategory, string> = {
  'Mud Chemicals': 'Enter estimated lump sums per section. Multiple sections can be added at once and will save as separate line items.',
  'Cement Additives': 'Enter estimated lump sums per section. Multiple sections can be added at once and will save as separate line items.',
  Fuel: 'Enter estimated lump sums per section. Multiple sections can be added at once and will save as separate line items.',
  'Drill Bits': 'Price per bit from Master Data. Multiple drill bits can be added and will save as separate line items.',
}

type SectionEntry = {
  id: string
  hole_section_id: string
  phase_id: string | null
  estimated_amount: string
  remarks: string
}

type DrillBitEntry = {
  id: string
  hole_section_id: string
  phase_id: string | null
  drill_bit_id: string | null
  quantity: string
  override_rate: string | null
  remarks: string
}

type Props = {
  open: boolean
  initial: ConsumableLineInput | null
  scope: WellScope
  reference: AfeReference
  onClose: () => void
  onSave: (lines: ConsumableLineInput[]) => void
}

export function ConsumableLineDialog({ open, initial, scope, reference, onClose, onSave }: Props) {
  const [category, setCategory] = useState<ConsumableCategory>('Mud Chemicals')
  const [currency, setCurrency] = useState('')
  const [commonRemarks, setCommonRemarks] = useState('')
  const [sectionEntries, setSectionEntries] = useState<SectionEntry[]>([])
  const [bitEntries, setBitEntries] = useState<DrillBitEntry[]>([])
  const [baselineState, setBaselineState] = useState<string>('')
  const [submitted, setSubmitted] = useState(false)

  const sections = useMemo(() => sectionOptions(scope), [scope])

  useEffect(() => {
    if (!open) return
    const defaultCurr = defaultCurrencyCode(reference.currencies)

    if (initial) {
      setCategory(initial.category)
      setCurrency(initial.currency || defaultCurr)
      setCommonRemarks(initial.remarks || '')

      if (initial.category === 'Drill Bits') {
        setBitEntries([{
          id: initial.client_key || newKey(),
          hole_section_id: initial.hole_section_id,
          phase_id: initial.phase_id,
          drill_bit_id: initial.drill_bit_id,
          quantity: initial.quantity || '1',
          override_rate: initial.override_rate,
          remarks: initial.remarks || '',
        }])
        setSectionEntries([])
      } else {
        setSectionEntries([{
          id: initial.client_key || newKey(),
          hole_section_id: initial.hole_section_id,
          phase_id: initial.phase_id,
          estimated_amount: initial.estimated_amount || '',
          remarks: initial.remarks || '',
        }])
        setBitEntries([])
      }
    } else {
      setCategory('Mud Chemicals')
      setCurrency(defaultCurr)
      setCommonRemarks('')
      const firstSection = sections[0]?.id ?? ''
      setSectionEntries([{
        id: newKey(),
        hole_section_id: firstSection,
        phase_id: null,
        estimated_amount: '',
        remarks: '',
      }])
      setBitEntries([{
        id: newKey(),
        hole_section_id: firstSection,
        phase_id: null,
        drill_bit_id: null,
        quantity: '1',
        override_rate: null,
        remarks: '',
      }])
    }

    setSubmitted(false)
  }, [open, initial, reference.currencies, sections])

  useEffect(() => {
    if (open && baselineState === '') {
      setBaselineState(JSON.stringify({ category, currency, commonRemarks, sectionEntries, bitEntries }))
    }
  }, [open, baselineState, category, currency, commonRemarks, sectionEntries, bitEntries])

  const currentState = JSON.stringify({ category, currency, commonRemarks, sectionEntries, bitEntries })
  const dirty = baselineState !== '' && currentState !== baselineState

  const isBit = category === 'Drill Bits'

  // Handling section entries for lump sums
  const addSectionEntry = () => {
    const usedSections = new Set(sectionEntries.map(e => e.hole_section_id).filter(Boolean))
    const nextAvailable = sections.find(s => !usedSections.has(s.id))?.id ?? ''
    setSectionEntries(prev => [
      ...prev,
      {
        id: newKey(),
        hole_section_id: nextAvailable,
        phase_id: null,
        estimated_amount: '',
        remarks: '',
      },
    ])
  }

  const updateSectionEntry = (id: string, patch: Partial<SectionEntry>) => {
    setSectionEntries(prev => prev.map(entry => {
      if (entry.id !== id) return entry
      const next = { ...entry, ...patch }
      if (patch.hole_section_id !== undefined && patch.hole_section_id !== entry.hole_section_id) {
        next.phase_id = null
      }
      return next
    }))
  }

  const removeSectionEntry = (id: string) => {
    if (sectionEntries.length <= 1) return
    setSectionEntries(prev => prev.filter(entry => entry.id !== id))
  }

  // Duplicate section validation
  const duplicateSections = useMemo(() => {
    const counts = new Map<string, number>()
    sectionEntries.forEach(e => {
      if (e.hole_section_id) {
        counts.set(e.hole_section_id, (counts.get(e.hole_section_id) || 0) + 1)
      }
    })
    return new Set([...counts.entries()].filter(([, c]) => c > 1).map(([s]) => s))
  }, [sectionEntries])

  // Handling drill bit entries
  const addBitEntry = () => {
    const firstSection = sections[0]?.id ?? ''
    setBitEntries(prev => [
      ...prev,
      {
        id: newKey(),
        hole_section_id: firstSection,
        phase_id: null,
        drill_bit_id: null,
        quantity: '1',
        override_rate: null,
        remarks: '',
      },
    ])
  }

  const updateBitEntry = (id: string, patch: Partial<DrillBitEntry>) => {
    setBitEntries(prev => prev.map(entry => {
      if (entry.id !== id) return entry
      const next = { ...entry, ...patch }
      if (patch.hole_section_id !== undefined && patch.hole_section_id !== entry.hole_section_id) {
        next.phase_id = null
      }
      return next
    }))
  }

  const removeBitEntry = (id: string) => {
    if (bitEntries.length <= 1) return
    setBitEntries(prev => prev.filter(entry => entry.id !== id))
  }

  // Total summary calculation
  const totalLumpSum = useMemo(() => {
    return sectionEntries.reduce((sum, entry) => sum + toNumber(entry.estimated_amount), 0)
  }, [sectionEntries])

  const totalBits = useMemo(() => {
    return bitEntries.reduce((sum, entry) => sum + toNumber(entry.quantity), 0)
  }, [bitEntries])

  // Validation
  const errors: string[] = []
  if (isBit) {
    if (!bitEntries.length) errors.push('Add at least one drill bit.')
    bitEntries.forEach((entry, idx) => {
      if (!entry.hole_section_id) errors.push(`Drill bit #${idx + 1}: Select a hole section.`)
      if (!entry.drill_bit_id) errors.push(`Drill bit #${idx + 1}: Select a drill bit from Master Data.`)
      if (toNumber(entry.quantity) <= 0) errors.push(`Drill bit #${idx + 1}: Quantity must be greater than zero.`)
    })
  } else {
    if (!currency) errors.push('Select a currency.')
    if (!sectionEntries.length) errors.push('Add at least one section.')
    if (duplicateSections.size > 0) {
      errors.push('Same section cannot be added twice. Each hole section must be unique in this list.')
    }
    sectionEntries.forEach((entry, idx) => {
      if (!entry.hole_section_id) errors.push(`Section row #${idx + 1}: Select a hole section.`)
      if (entry.estimated_amount === '' || entry.estimated_amount === null || isNaN(Number(entry.estimated_amount)) || Number(entry.estimated_amount) < 0) {
        errors.push(`Section row #${idx + 1}: Enter a valid estimated lump sum amount.`)
      }
    })
  }

  const handleSave = () => {
    setSubmitted(true)
    if (errors.length > 0) return

    if (isBit) {
      const lines: ConsumableLineInput[] = bitEntries.map(entry => {
        const bit = reference.drill_bits.find(item => item.id === entry.drill_bit_id)
        return {
          client_key: initial?.client_key && bitEntries.length === 1 ? initial.client_key : entry.id || newKey(),
          category: 'Drill Bits',
          hole_section_id: entry.hole_section_id,
          phase_id: entry.phase_id || null,
          drill_bit_id: entry.drill_bit_id,
          quantity: entry.quantity || '1',
          override_rate: entry.override_rate || null,
          estimated_amount: null,
          currency: bit?.currency || '',
          remarks: (entry.remarks || commonRemarks).trim(),
        }
      })
      onSave(lines)
    } else {
      const lines: ConsumableLineInput[] = sectionEntries.map(entry => ({
        client_key: initial?.client_key && sectionEntries.length === 1 ? initial.client_key : entry.id || newKey(),
        category,
        hole_section_id: entry.hole_section_id,
        phase_id: entry.phase_id || null,
        drill_bit_id: null,
        quantity: '1',
        override_rate: null,
        estimated_amount: entry.estimated_amount,
        currency,
        remarks: (entry.remarks || commonRemarks).trim(),
      }))
      onSave(lines)
    }
  }

  const dialogTitle = initial
    ? `Edit ${initial.category} line`
    : `Add ${category}`
  const submitText = initial
    ? 'Save line'
    : isBit
      ? bitEntries.length > 1 ? `Add ${bitEntries.length} drill bits` : 'Add drill bit'
      : sectionEntries.length > 1 ? `Add ${sectionEntries.length} section lines` : 'Add consumable'

  return (
    <FormDialog
      open={open}
      title={dialogTitle}
      subtitle="Mud chemicals, cement additives and fuel are estimated per section as lump sums. Drill bits are priced per bit."
      onClose={onClose}
      onSubmit={handleSave}
      dirty={dirty}
      submitLabel={submitText}
      maxWidth="md"
    >
      <Box display="grid" gap={2}>
        {/* Category Tabs */}
        {!initial && (
          <Box>
            <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={0.7} mb={0.8}>
              Consumable category
            </Typography>
            <Tabs
              value={category}
              onChange={(_event, val) => {
                if (val) {
                  setCategory(val)
                  setSubmitted(false)
                }
              }}
              variant="fullWidth"
              sx={{
                bgcolor: 'action.hover',
                borderRadius: 1.5,
                p: 0.5,
                '& .MuiTab-root': {
                  minHeight: 38,
                  fontWeight: 700,
                  fontSize: 13,
                  textTransform: 'none',
                  borderRadius: 1,
                  '&.Mui-selected': {
                    bgcolor: 'background.paper',
                    boxShadow: 1,
                  },
                },
              }}
            >
              {CONSUMABLE_CATEGORIES.map(cat => (
                <Tab key={cat} value={cat} label={cat} />
              ))}
            </Tabs>
            <Typography fontSize={12} color="text.secondary" mt={0.8}>
              {CATEGORY_HINT[category]}
            </Typography>
          </Box>
        )}

        {/* Currency & Common Remarks for Lump Sum categories */}
        {!isBit && (
          <Box display="grid" gap={1.6} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.2fr 2fr' } }}>
            <TextField
              select
              label="Currency"
              required
              value={currency}
              onChange={event => setCurrency(event.target.value)}
              error={submitted && !currency}
              helperText="Applied to all sections."
            >
              {reference.currencies.map(curr => (
                <MenuItem key={curr.code} value={curr.code}>
                  {curr.code} · {curr.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="General remarks (optional)"
              value={commonRemarks}
              onChange={event => setCommonRemarks(event.target.value)}
              inputProps={{ maxLength: 500 }}
              helperText="Applies as default remarks for these lines."
            />
          </Box>
        )}

        {/* Lump Sum Categories: Multi-section Entry List */}
        {!isBit && (
          <Box>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography fontSize={12} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={0.5}>
                Hole sections &amp; lump sum amounts ({sectionEntries.length})
              </Typography>
              {!initial && (
                <Button
                  size="small"
                  startIcon={<AddRounded sx={{ fontSize: 16 }} />}
                  onClick={addSectionEntry}
                  variant="outlined"
                  disabled={sectionEntries.length >= sections.length && sections.length > 0}
                >
                  Add section
                </Button>
              )}
            </Box>

            <Box display="grid" gap={1.2}>
              {sectionEntries.map((entry, index) => {
                const phases = phaseOptions(scope, entry.hole_section_id)
                const isDuplicate = duplicateSections.has(entry.hole_section_id)
                return (
                  <Paper
                    key={entry.id}
                    variant="outlined"
                    sx={{
                      p: 1.5,
                      borderRadius: 1.5,
                      borderColor: isDuplicate ? 'error.main' : 'divider',
                      bgcolor: isDuplicate ? 'error.lighter' : 'background.paper',
                    }}
                  >
                    <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.2fr 1fr 1.2fr auto' }, alignItems: 'center' }}>
                      <TextField
                        select
                        size="small"
                        label={`Section ${index + 1}`}
                        required
                        value={entry.hole_section_id}
                        onChange={e => updateSectionEntry(entry.id, { hole_section_id: e.target.value })}
                        error={(submitted && !entry.hole_section_id) || isDuplicate}
                        helperText={isDuplicate ? 'Duplicate section! Must be unique.' : undefined}
                      >
                        {sections.map(sec => (
                          <MenuItem key={sec.id} value={sec.id}>
                            {sec.label}
                          </MenuItem>
                        ))}
                      </TextField>

                      <TextField
                        select
                        size="small"
                        label="Phase (optional)"
                        value={entry.phase_id ?? ''}
                        disabled={!entry.hole_section_id}
                        onChange={e => updateSectionEntry(entry.id, { phase_id: e.target.value || null })}
                      >
                        <MenuItem value="">All phases</MenuItem>
                        {phases.map(p => (
                          <MenuItem key={p.id} value={p.id}>
                            {p.label}
                          </MenuItem>
                        ))}
                      </TextField>

                      <TextField
                        size="small"
                        label="Lump sum amount"
                        required
                        value={entry.estimated_amount}
                        onChange={e => updateSectionEntry(entry.id, { estimated_amount: e.target.value.replace(/[^0-9.]/g, '') })}
                        inputProps={{ inputMode: 'decimal' }}
                        error={submitted && (entry.estimated_amount === '' || isNaN(Number(entry.estimated_amount)))}
                        helperText={currency && entry.estimated_amount ? amountText(entry.estimated_amount, currency) : undefined}
                      />

                      {!initial && sectionEntries.length > 1 && (
                        <Tooltip title="Remove this section">
                          <IconButton size="small" color="error" onClick={() => removeSectionEntry(entry.id)}>
                            <DeleteOutlineRounded sx={{ fontSize: 20 }} />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Box>
                  </Paper>
                )
              })}
            </Box>

            {/* Total Lump Sum Card */}
            <Box mt={1.5} p={1.2} display="flex" justifyContent="space-between" alignItems="center" bgcolor="action.hover" borderRadius={1}>
              <Typography fontSize={12} color="text.secondary">
                {sectionEntries.length} section{sectionEntries.length === 1 ? '' : 's'} entered
              </Typography>
              <Typography fontSize={14} fontWeight={800}>
                Total {amountText(totalLumpSum, currency)}
              </Typography>
            </Box>
          </Box>
        )}

        {/* Drill Bits: Multi-bit Entry List */}
        {isBit && (
          <Box>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography fontSize={12} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={0.5}>
                Drill bits list ({bitEntries.length})
              </Typography>
              {!initial && (
                <Button size="small" startIcon={<AddRounded sx={{ fontSize: 16 }} />} onClick={addBitEntry} variant="outlined">
                  Add drill bit
                </Button>
              )}
            </Box>

            <Box display="grid" gap={1.8}>
              {bitEntries.map((entry, index) => {
                const phases = phaseOptions(scope, entry.hole_section_id)
                const bit = reference.drill_bits.find(item => item.id === entry.drill_bit_id) ?? null
                return (
                  <Paper key={entry.id} variant="outlined" sx={{ p: 1.8, borderRadius: 1.5 }}>
                    <Box display="flex" justifyContent="space-between" alignItems="center" mb={1.2}>
                      <Typography fontSize={12} fontWeight={800} color="primary">
                        Drill bit #{index + 1}
                      </Typography>
                      {!initial && bitEntries.length > 1 && (
                        <Button size="small" color="error" startIcon={<DeleteOutlineRounded sx={{ fontSize: 16 }} />} onClick={() => removeBitEntry(entry.id)}>
                          Remove
                        </Button>
                      )}
                    </Box>

                    <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                      <TextField
                        select
                        size="small"
                        label="Hole section"
                        required
                        value={entry.hole_section_id}
                        onChange={e => updateBitEntry(entry.id, { hole_section_id: e.target.value })}
                        error={submitted && !entry.hole_section_id}
                      >
                        {sections.map(sec => (
                          <MenuItem key={sec.id} value={sec.id}>
                            {sec.label}
                          </MenuItem>
                        ))}
                      </TextField>

                      <TextField
                        select
                        size="small"
                        label="Phase (optional)"
                        value={entry.phase_id ?? ''}
                        disabled={!entry.hole_section_id}
                        onChange={e => updateBitEntry(entry.id, { phase_id: e.target.value || null })}
                      >
                        <MenuItem value="">All phases</MenuItem>
                        {phases.map(p => (
                          <MenuItem key={p.id} value={p.id}>
                            {p.label}
                          </MenuItem>
                        ))}
                      </TextField>

                      <Box sx={{ gridColumn: '1 / -1' }}>
                        <DrillBitPicker
                          value={entry.drill_bit_id ?? ''}
                          options={reference.drill_bits}
                          onChange={id => updateBitEntry(entry.id, { drill_bit_id: id || null })}
                          error={submitted && !entry.drill_bit_id}
                        />
                      </Box>

                      {bit && (
                        <Box sx={{ gridColumn: '1 / -1' }}>
                          <FactPanel
                            rows={[
                              { label: 'Make', value: bit.manufacturer_name },
                              { label: 'Bit type', value: bit.bit_type },
                              { label: 'Size', value: bit.size },
                              { label: 'IADC code', value: bit.iadc_code },
                              { label: 'Model no.', value: bit.model_no },
                              { label: 'Final cost', value: amountText(bit.captured_rate, bit.currency) },
                            ]}
                          />
                        </Box>
                      )}

                      <TextField
                        size="small"
                        label="Number of bits"
                        required
                        value={entry.quantity}
                        onChange={e => updateBitEntry(entry.id, { quantity: e.target.value.replace(/[^0-9.]/g, '') })}
                        inputProps={{ inputMode: 'decimal' }}
                        error={submitted && toNumber(entry.quantity) <= 0}
                      />

                      <TextField
                        size="small"
                        label="Override unit rate (optional)"
                        value={entry.override_rate ?? ''}
                        onChange={e => updateBitEntry(entry.id, { override_rate: e.target.value.replace(/[^0-9.]/g, '') || null })}
                        inputProps={{ inputMode: 'decimal' }}
                        helperText={bit ? `Master cost: ${amountText(bit.captured_rate, bit.currency)}` : undefined}
                      />

                      <TextField
                        size="small"
                        label="Remarks (optional)"
                        value={entry.remarks}
                        onChange={e => updateBitEntry(entry.id, { remarks: e.target.value })}
                        inputProps={{ maxLength: 500 }}
                        sx={{ gridColumn: '1 / -1' }}
                      />
                    </Box>
                  </Paper>
                )
              })}
            </Box>

            <Box mt={1.5} p={1.2} display="flex" justifyContent="space-between" alignItems="center" bgcolor="action.hover" borderRadius={1}>
              <Typography fontSize={12} color="text.secondary">
                {bitEntries.length} drill bit line{bitEntries.length === 1 ? '' : 's'}
              </Typography>
              <Typography fontSize={13} fontWeight={700}>
                Total bits: {totalBits}
              </Typography>
            </Box>
          </Box>
        )}

        {submitted && errors.length > 0 && (
          <Alert severity="error">
            {errors.map(err => (
              <Typography key={err} fontSize={12.5}>
                {err}
              </Typography>
            ))}
          </Alert>
        )}

        <Divider />
        <Typography fontSize={11.5} color="text.secondary">
          {isBit
            ? 'Each drill bit line will be saved as an individual consumable item under this AFE estimate.'
            : `Lump sums: ${LUMP_SUM_CATEGORIES.join(', ')}. Each section is saved as an individual line item.`}
        </Typography>
      </Box>
    </FormDialog>
  )
}

import { useEffect, useMemo, useState } from 'react'
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Divider, Paper, Table, TableBody,
  TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { ExpandMoreRounded } from '@mui/icons-material'
import { ErrorMessage, FormDialog } from '../Common'
import { radius } from '../../designSystem'
import {
  MUD_COST_ENTRY_LINES, MUD_COST_LINE_GROUPS, MUD_COST_STOCK_LINES,
  localMudToday, validMudDate, type MudCostEntry, type MudCostEntryUpdatePayload,
  type MudCostLineInput, type MudCostLineSpec, type MudCostSectionOption,
} from '../../lib/mudCost'
import type { MudCostRigOption, MudCostWellOption } from '../../lib/mudCost'

export type MudCostEditorPayload = MudCostEntryUpdatePayload

type LineState = Record<string, { amount: string; remarks: string }>
type FormState = { entry_date: string; lines: LineState }

const MAX_QUANTITY_MILLI = 999999999999999999n
const QUANTITY_PATTERN = /^(?:\d+|\d*\.\d{1,3})$/

function quantityMilli(value: string | null | undefined): bigint {
  const text = (value ?? '').trim()
  if (!text || !QUANTITY_PATTERN.test(text)) return 0n
  const [whole = '0', fraction = ''] = text.split('.')
  return BigInt(whole || '0') * 1000n + BigInt((fraction + '000').slice(0, 3) || '0')
}

function displayMilli(value: bigint): string {
  const negative = value < 0n
  const absolute = negative ? -value : value
  const whole = (absolute / 1000n).toLocaleString()
  const fraction = String(absolute % 1000n).padStart(3, '0').replace(/0+$/, '')
  return `${negative ? '−' : ''}${whole}${fraction ? `.${fraction}` : ''}`
}

type Props = {
  open: boolean
  onClose: () => void
  onSave: (payload: MudCostEditorPayload) => Promise<void>
  entry: MudCostEntry | null
  rig: MudCostRigOption | null
  section: MudCostSectionOption | null
  well: MudCostWellOption | null
  entries: MudCostEntry[]
  existingRows: MudCostEntry[]
  saving: boolean
  error: string
}

function blankLines(): LineState {
  return Object.fromEntries(MUD_COST_LINE_SPECS.map(line => [line.code, { amount: '', remarks: '' }]))
}

const MUD_COST_LINE_SPECS = [...MUD_COST_STOCK_LINES.slice(0, 1), ...MUD_COST_ENTRY_LINES, ...MUD_COST_STOCK_LINES.slice(1)]

function initialForm(entry: MudCostEntry | null): FormState {
  const lines = blankLines()
  if (entry) {
    for (const line of entry.lines) {
      lines[line.line_code] = {
        amount: Number(line.amount) === 0 ? '' : String(line.amount),
        remarks: line.remarks ?? '',
      }
    }
  }
  return { entry_date: entry?.entry_date ?? localMudToday(), lines }
}

function minRemarkError(amount: string, remarks: string, label: string): string {
  if (Number(amount || 0) > 0 && remarks.trim().length < 3) return `${label}: add a remark of at least 3 characters.`
  return ''
}

function NumberCell({ line, value, onChange, error, disabled = false }: {
  line: MudCostLineSpec
  value: string
  onChange: (value: string) => void
  error?: string
  disabled?: boolean
}) {
  return <TextField
    size="small"
    label={`${line.label} quantity`}
    type="number"
    value={value}
    disabled={disabled}
    onChange={event => onChange(event.target.value)}
    inputProps={{ min: 0, step: 0.001, inputMode: 'decimal', 'aria-label': `${line.label} quantity` }}
    error={Boolean(error)}
    helperText={error || ' '}
    sx={{ minWidth: 130, '& .MuiFormHelperText-root': { minHeight: 16, mt: 0 } }}
  />
}

function RemarksCell({ line, value, onChange, error, disabled = false }: {
  line: MudCostLineSpec
  value: string
  onChange: (value: string) => void
  error?: string
  disabled?: boolean
}) {
  return <TextField
    size="small"
    label={`${line.label} remarks`}
    value={value}
    disabled={disabled}
    onChange={event => onChange(event.target.value)}
    inputProps={{ maxLength: 500, 'aria-label': `${line.label} remarks` }}
    error={Boolean(error)}
    helperText={error || ' '}
    sx={{ minWidth: 240, width: '100%', '& .MuiFormHelperText-root': { minHeight: 16, mt: 0 } }}
  />
}

export function MudCostEntryDialog({ open, onClose, onSave, entry, rig, section, well, entries, existingRows, saving, error }: Props) {
  const [form, setForm] = useState<FormState>(() => initialForm(entry))
  const [formError, setFormError] = useState('')

  useEffect(() => {
    if (open) {
      setForm(initialForm(entry))
      setFormError('')
    }
  }, [open, entry])

  const priorRows = useMemo(() => entries
    .filter(row => row.section_id === (entry?.section_id ?? section?.id) && row.id !== entry?.id && !row.is_deleted && row.entry_date < form.entry_date)
    .sort((a, b) => b.entry_date.localeCompare(a.entry_date)), [entries, entry?.id, entry?.section_id, section?.id, form.entry_date])
  const isFirstSectionEntry = priorRows.length === 0
  const previousActual = priorRows[0]
  const openingLine = form.lines.opening_stock ?? { amount: '', remarks: '' }
  const actualLine = form.lines.actual_closing_stock ?? { amount: '', remarks: '' }
  const openingAmount = isFirstSectionEntry ? openingLine.amount : previousActual?.actual_closing_stock ?? entry?.opening_stock ?? '0'
  const openingRemarks = isFirstSectionEntry ? openingLine.remarks : previousActual?.actual_closing_stock_remarks ?? entry?.opening_stock_remarks ?? ''
  const categoryTotal = (category: string) => MUD_COST_ENTRY_LINES
    .filter(line => line.category === category)
    .reduce((total, line) => total + quantityMilli(form.lines[line.code]?.amount), 0n)
  const openingTotal = quantityMilli(openingAmount)
  const receiptTotal = categoryTotal('receipt')
  const additionsTotal = categoryTotal('additions')
  const consumptionTotal = categoryTotal('consumption_losses')
  const otherTotal = categoryTotal('others')
  const actualTotal = quantityMilli(actualLine.amount)
  const bookTotal = openingTotal + receiptTotal + additionsTotal - consumptionTotal - otherTotal
  const varianceTotal = actualTotal - bookTotal

  const duplicateDate = existingRows.find(row => row.id !== entry?.id && row.entry_date === form.entry_date)
  const dateError = !validMudDate(form.entry_date)
    ? 'Enter a valid calendar date.'
    : duplicateDate
      ? duplicateDate.is_deleted
        ? `A deleted Mud Cost entry already uses ${form.entry_date}. Restore or permanently delete that record before reusing the date.`
        : `A Mud Cost entry already exists for ${form.entry_date} (${duplicateDate.section_label}). One entry per well/date is allowed.`
      : ''

  const lineErrors = useMemo(() => {
    const errors: Record<string, string> = {}
    for (const spec of MUD_COST_LINE_SPECS) {
      if (spec.code === 'opening_stock' && !isFirstSectionEntry) continue
      const value = form.lines[spec.code] ?? { amount: '', remarks: '' }
      const text = value.amount.trim()
      if (text) {
        if (!QUANTITY_PATTERN.test(text)) {
          errors[spec.code] = `${spec.label}: enter a non-negative quantity with up to 3 decimal places.`
          continue
        }
        if (quantityMilli(text) > MAX_QUANTITY_MILLI) {
          errors[spec.code] = `${spec.label}: quantity is larger than the supported maximum.`
          continue
        }
      }
      const problem = minRemarkError(value.amount, value.remarks, spec.label)
      if (problem) errors[spec.code] = problem
    }
    return errors
  }, [form.lines, isFirstSectionEntry])

  const updateDate = (entry_date: string) => setForm(current => ({ ...current, entry_date }))
  const updateLine = (code: string, field: 'amount' | 'remarks', value: string) => {
    setForm(current => ({
      ...current,
      lines: { ...current.lines, [code]: { ...(current.lines[code] ?? { amount: '', remarks: '' }), [field]: value } },
    }))
  }

  const validate = async () => {
    if (dateError) { setFormError(dateError); return }
    if (Object.keys(lineErrors).length) {
      setFormError('Correct quantity values and add a remark for each non-zero quantity before saving.')
      return
    }
    setFormError('')
    const lines: MudCostLineInput[] = MUD_COST_LINE_SPECS.map(spec => {
      const row = form.lines[spec.code] ?? { amount: '', remarks: '' }
      const amount = spec.code === 'opening_stock' && !isFirstSectionEntry ? null : (row.amount.trim() || null)
      const remarks = spec.code === 'opening_stock' && !isFirstSectionEntry ? '' : row.remarks.trim()
      return { line_code: spec.code, amount, remarks }
    })
    await onSave({ entry_date: form.entry_date, lines })
  }

  const stockSection = (spec: MudCostLineSpec, derived: boolean) => {
    const value = spec.code === 'opening_stock' ? openingAmount : actualLine.amount
    const remarks = spec.code === 'opening_stock' ? openingRemarks : actualLine.remarks
    const errorText = spec.code === 'opening_stock' && !isFirstSectionEntry ? '' : lineErrors[spec.code]
    return <Paper key={spec.code} variant="outlined" sx={{ p: 1.5, borderRadius: `${radius.md}px`, minWidth: 0 }}>
      <Typography fontWeight={800} fontSize={13} mb={1}>{spec.label}</Typography>
      {derived && <Typography color="text.secondary" fontSize={11.5} mb={1}>
        Carried forward from {previousActual?.entry_date ?? 'the preceding actual closing'}; this section uses its initial value only on the first recorded date.
      </Typography>}
      <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', md: 'minmax(140px, .55fr) minmax(220px, 1fr)' } }}>
        <NumberCell
          line={spec}
          value={value}
          disabled={derived}
          onChange={next => updateLine(spec.code, 'amount', next)}
          error={errorText}
        />
        <RemarksCell
          line={spec}
          value={remarks}
          disabled={derived}
          onChange={next => updateLine(spec.code, 'remarks', next)}
          error={errorText}
        />
      </Box>
    </Paper>
  }

  return <FormDialog
    open={open}
    onClose={onClose}
    onSubmit={validate}
    busy={saving}
    busyLabel="Saving Mud Cost entry…"
    title={entry ? 'Edit Mud Cost entry' : 'New Mud Cost entry'}
    subtitle="Record one date for this well. Blank rows are saved as zero; every non-zero quantity needs a remark."
    maxWidth="xl"
    submitLabel={entry ? 'Save entry' : 'Create entry'}
    submitDisabled={!section || !well || Boolean(dateError) || Object.keys(lineErrors).length > 0}
  >
    <Box display="grid" gap={2}>
      <ErrorMessage message={formError || error}/>
      <Paper variant="outlined" sx={{ p: 1.5, borderRadius: `${radius.md}px` }}>
        <Box display="grid" gap={1.4} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr 1fr' } }}>
          <TextField
            type="date"
            label="Entry date"
            value={form.entry_date}
            onChange={event => updateDate(event.target.value)}
            InputLabelProps={{ shrink: true }}
            error={Boolean(dateError)}
            helperText={dateError || 'One entry is allowed per well/date.'}
          />
          <TextField label="Rig" value={rig?.display_name ?? ''} disabled helperText="Selected rig scope"/>
          <TextField label="Well section" value={section?.display_name ?? ''} disabled helperText={section?.is_current ? 'Section from Rig & Well configuration' : 'Historical section snapshot'}/>
        </Box>
      </Paper>

      <Alert severity="info">
        Keep quantities in one consistent volume unit for this well section. Opening stock after the first entry is calculated from the previous recorded actual closing stock.
      </Alert>

      <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' } }}>
        {stockSection(MUD_COST_STOCK_LINES[0], !isFirstSectionEntry)}
        {stockSection(MUD_COST_STOCK_LINES[1], false)}
      </Box>

      <Paper variant="outlined" sx={{ p: 1.5, borderRadius: `${radius.md}px` }}>
        <Box display="flex" alignItems="baseline" justifyContent="space-between" gap={1} flexWrap="wrap" mb={1.2}>
          <Typography fontWeight={800} fontSize={13}>Live material-balance preview</Typography>
          <Typography color="text.secondary" fontSize={11.5}>Blank quantities count as zero</Typography>
        </Box>
        <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(4, minmax(0, 1fr))' } }}>
          {[
            { label: 'Opening stock', value: displayMilli(openingTotal) },
            { label: 'Receipt', value: displayMilli(receiptTotal) },
            { label: 'Additions', value: displayMilli(additionsTotal) },
            { label: 'Consumption / losses', value: displayMilli(consumptionTotal) },
            { label: 'Others', value: displayMilli(otherTotal) },
            { label: 'Book closing stock', value: displayMilli(bookTotal) },
            { label: 'Actual closing stock', value: displayMilli(actualTotal) },
            { label: 'Variance', value: displayMilli(varianceTotal) },
          ].map(item => <Box key={item.label} sx={{ minWidth: 0, borderLeft: '2px solid', borderColor: 'divider', pl: 1 }}>
            <Typography color="text.secondary" fontSize={10.5} fontWeight={700} textTransform="uppercase">{item.label}</Typography>
            <Typography className="tnum" fontSize={15} fontWeight={800}>{item.value}</Typography>
          </Box>)}
        </Box>
        <Typography color="text.secondary" fontSize={11} mt={1.2}>
          Book closing = opening + receipt + additions − consumption/losses − others · Variance = actual closing − book closing.
        </Typography>
      </Paper>

      {MUD_COST_LINE_GROUPS.map((group, index) => <Accordion
        key={group.key}
        defaultExpanded={index === 0}
        disableGutters
        variant="outlined"
        sx={{ borderRadius: `${radius.md}px`, '&::before': { display: 'none' }, overflow: 'hidden' }}
      >
        <AccordionSummary expandIcon={<ExpandMoreRounded/>} aria-controls={`mud-cost-${group.key}-content`} id={`mud-cost-${group.key}-header`}>
          <Box display="flex" alignItems="center" gap={1.2} flexWrap="wrap">
            <Typography fontWeight={800} fontSize={13}>{group.label}</Typography>
            <Typography color="text.secondary" fontSize={11.5}>{group.lines.length} rows</Typography>
          </Box>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0 }}>
          <Divider sx={{ mb: 1.2 }}/>
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small" aria-label={`${group.label} entry rows`} sx={{ minWidth: 760 }}>
              <TableHead><TableRow>
                <TableCell sx={{ width: 210 }}>Entry row</TableCell>
                <TableCell sx={{ minWidth: 170 }}>Quantity</TableCell>
                <TableCell sx={{ minWidth: 300 }}>Remarks</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {group.lines.map(line => {
                  const row = form.lines[line.code] ?? { amount: '', remarks: '' }
                  const rowError = lineErrors[line.code]
                  return <TableRow key={line.code}>
                    <TableCell sx={{ fontWeight: 700, fontSize: 12.5 }}>{line.label}</TableCell>
                    <TableCell><NumberCell line={line} value={row.amount} onChange={value => updateLine(line.code, 'amount', value)} error={rowError}/></TableCell>
                    <TableCell><RemarksCell line={line} value={row.remarks} onChange={value => updateLine(line.code, 'remarks', value)} error={rowError}/></TableCell>
                  </TableRow>
                })}
              </TableBody>
            </Table>
          </Box>
        </AccordionDetails>
      </Accordion>)}
    </Box>
  </FormDialog>
}

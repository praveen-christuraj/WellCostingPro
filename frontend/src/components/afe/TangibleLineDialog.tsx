import { useEffect, useState } from 'react'
import { Alert, Box, TextField, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import { amountText, emptyTangibleLine, tangibleProblems, toNumber, type AfeReference, type TangibleLineInput } from '../../lib/afe'
import { FactPanel, TangiblePicker } from './LinePickers'

type Props = {
  open: boolean
  initial: TangibleLineInput | null
  reference: AfeReference
  onClose: () => void
  onSave: (line: TangibleLineInput) => void
}

// Tangibles are priced at the captured master rate unless an override is entered.
export function TangibleLineDialog({ open, initial, reference, onClose, onSave }: Props) {
  const [line, setLine] = useState<TangibleLineInput>(() => emptyTangibleLine())
  const [baseline, setBaseline] = useState<TangibleLineInput | null>(null)
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    if (!open) return
    const next = initial ? structuredClone(initial) : emptyTangibleLine()
    setLine(next)
    setBaseline(next)
    setSubmitted(false)
  }, [open, initial])
  // Unsaved-changes guard: everything typed or picked in this dialog is protected.
  const dirty = baseline !== null && JSON.stringify(line) !== JSON.stringify(baseline)

  const item = reference.tangibles.find(entry => entry.id === line.tangible_id) ?? null
  const problems = tangibleProblems(line)
  const update = (patch: Partial<TangibleLineInput>) => setLine(current => ({ ...current, ...patch }))
  const noRate = Boolean(item) && toNumber(item?.captured_rate) === 0 && !line.override_rate

  const save = () => {
    setSubmitted(true)
    if (problems.length) return
    onSave({ ...line, remarks: line.remarks.trim(), override_rate: line.override_rate || null })
  }

  return <FormDialog
    open={open}
    title={initial ? 'Edit tangible line' : 'Add tangible'}
    subtitle="Search Master Data by code, name, manufacturer, description or category. The master rate is captured automatically."
    onClose={onClose}
    onSubmit={save}
    dirty={dirty}
    submitLabel={initial ? 'Save line' : 'Add tangible'}
    maxWidth="md"
  >
    <Box display="grid" gap={2}>
      <TangiblePicker value={line.tangible_id} options={reference.tangibles} onChange={id => update({ tangible_id: id })} error={submitted && !line.tangible_id}/>

      {item && <FactPanel rows={[
        { label: 'Manufacturer', value: item.manufacturer_name },
        { label: 'Description', value: item.description },
        { label: 'Category', value: [item.category_name, item.subcategory_name].filter(Boolean).join(' › ') },
        { label: 'Scope', value: item.scope },
        { label: 'Unit of measure', value: item.uom },
        { label: 'Master rate', value: amountText(item.captured_rate, item.currency) },
      ]}/>}

      <Box display="grid" gap={1.6} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField
          label={`Quantity${item?.uom ? ` (${item.uom})` : ''}`} required value={line.quantity}
          onChange={event => update({ quantity: event.target.value.replace(/[^0-9.]/g, '') })}
          inputProps={{ inputMode: 'decimal' }}
          error={submitted && toNumber(line.quantity) < 0}
        />
        <TextField
          label="Override unit rate (optional)"
          value={line.override_rate ?? ''}
          onChange={event => update({ override_rate: event.target.value.replace(/[^0-9.]/g, '') || null })}
          inputProps={{ inputMode: 'decimal' }}
          helperText={item ? `Leave empty to use the master rate. Override is in ${item.currency || 'the master currency'}.` : 'Leave empty to use the master rate.'}
        />
        <TextField label="Currency" value={item?.currency ?? ''} disabled helperText="Follows the tangible’s master record."/>
        <TextField label="Remarks" value={line.remarks} onChange={event => update({ remarks: event.target.value })} inputProps={{ maxLength: 500 }}/>
      </Box>

      {noRate && <Alert severity="warning">This tangible has no master rate. Enter an override rate or the line will be priced at zero.</Alert>}
      {submitted && problems.length > 0 && <Alert severity="error">
        {problems.map(problem => <Typography key={problem} fontSize={12.5}>{problem}</Typography>)}
      </Alert>}
    </Box>
  </FormDialog>
}

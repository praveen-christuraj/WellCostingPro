import { useEffect, useState } from 'react'
import { Box, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog } from '../Common'
import { MasterSelect } from './MasterSelect'
import {
  formatMoney,
  formatPercent,
  formToPayload,
  previewFinalCost,
  todayIso,
  type FormState,
  type PricedRecord,
  type TypeConfig,
} from '../../lib/catalogue'

// Records a new price. Every change needs a reason and an effective date, and is kept
// in the revision history beside the previous rate.
export function ReviseRateDialog({ config, record, busy, error, onClose, onSubmit }: {
  config: TypeConfig
  record: PricedRecord | null
  busy: boolean
  error: string
  onClose: () => void
  onSubmit: (payload: Record<string, unknown>) => void
}) {
  const [form, setForm] = useState<FormState>({})
  const [reason, setReason] = useState('')
  const [localError, setLocalError] = useState('')
  const uplift = config.priced === 'uplift'
  const fuel = config.fixed

  useEffect(() => {
    if (!record) return
    setForm({
      unit_rate: String(record.unit_rate ?? ''),
      cost_uplift: record.cost_uplift === null || record.cost_uplift === undefined ? '100' : String(record.cost_uplift),
      currency: record.currency ?? '',
      po_number: String(record.po_number ?? ''),
      effective_date: todayIso(),
    })
    setReason('')
    setLocalError('')
  }, [record])

  if (!record) return null
  const currentFinal = record.final_cost ?? null
  const newRate = form.unit_rate ?? ''
  const change = Number(record.unit_rate) > 0 && newRate !== ''
    ? ((Number(newRate) - Number(record.unit_rate)) / Number(record.unit_rate)) * 100
    : null
  const code = String(record[config.codeKey] ?? '')
  const name = String(record[config.nameKey] ?? '')

  const submit = () => {
    if (!newRate.trim()) { setLocalError('Enter the new rate.'); return }
    if (reason.trim().length < 3) { setLocalError('Give a reason for the change (at least 3 characters).'); return }
    if (!form.currency?.trim()) { setLocalError('Choose the currency.'); return }
    setLocalError('')
    onSubmit({ ...formToPayload(config, form, 'revise'), reason: reason.trim() })
  }

  return <FormDialog
    open
    title={fuel ? `Update price: ${name}` : `Revise rate: ${code}`}
    subtitle={fuel
      ? 'Enter the new price only when it changes. The previous price stays in the history.'
      : `${name} · current revision ${record.current_revision_number}. The previous rate stays in the history.`}
    onClose={() => { if (!busy) onClose() }}
    onSubmit={submit}
    busy={busy}
    submitLabel={fuel ? 'Save new price' : 'Save revision'}
  >
    <Box display="grid" gap={2} pt={.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
      <Box sx={{ gridColumn: { sm: '1 / -1' }, p: 1.5, borderRadius: 1.5, bgcolor: 'action.hover' }}>
        <Typography fontSize={12} color="text.secondary">Current {uplift ? 'rate as per PO' : fuel ? 'price' : 'unit rate'}</Typography>
        <Typography fontSize={18} fontWeight={800}>{formatMoney(record.unit_rate)} {record.currency}</Typography>
        {uplift && currentFinal !== null && <Typography fontSize={12} color="text.secondary">Current final cost {formatMoney(currentFinal)} at {formatPercent(record.cost_uplift)} uplift</Typography>}
        {record.effective_date && <Typography fontSize={12} color="text.secondary">Effective since {record.effective_date}</Typography>}
      </Box>
      <TextField label={uplift ? 'New rate as per PO' : fuel ? 'New price per litre' : 'New unit rate'} type="number" required value={form.unit_rate ?? ''}
        onChange={event => setForm({ ...form, unit_rate: event.target.value })} inputProps={{ min: 0, step: 'any' }}
        helperText={change === null ? ' ' : `Change ${change >= 0 ? '+' : ''}${change.toFixed(2)}% from current`} fullWidth/>
      {uplift && <TextField label="Cost uplift %" type="number" required value={form.cost_uplift ?? ''}
        onChange={event => setForm({ ...form, cost_uplift: event.target.value })} inputProps={{ min: 0, step: 'any' }}
        helperText={`New final cost ${previewFinalCost(newRate, form.cost_uplift ?? '')}`} fullWidth/>}
      <MasterSelect label="Currency" source="currencies" value={form.currency ?? ''} required onChange={code => setForm({ ...form, currency: code })} onError={setLocalError}/>
      {!fuel && <TextField label="PO number" value={form.po_number ?? ''} onChange={event => setForm({ ...form, po_number: event.target.value })} inputProps={{ maxLength: 100 }} fullWidth/>}
      <TextField label="Effective date" type="date" required value={form.effective_date ?? ''} onChange={event => setForm({ ...form, effective_date: event.target.value })}
        InputLabelProps={{ shrink: true }} helperText="Cannot be in the future or earlier than the current rate's date." fullWidth/>
      <TextField label="Reason for change" required value={reason} onChange={event => setReason(event.target.value)} multiline minRows={2}
        inputProps={{ maxLength: 500 }} helperText="For example: vendor re-quote, index change, PO amendment." sx={{ gridColumn: { sm: '1 / -1' } }} fullWidth/>
    </Box>
    <ErrorMessage message={localError || error}/>
  </FormDialog>
}

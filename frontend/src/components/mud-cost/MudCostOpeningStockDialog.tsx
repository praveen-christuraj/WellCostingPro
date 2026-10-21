import { useEffect, useState } from 'react'
import { Alert, Box, TextField } from '@mui/material'
import { ErrorMessage, FormDialog } from '../Common'
import type { MudCostEntry } from '../../lib/mudCost'

export function MudCostOpeningStockDialog({ entry, onClose, onSave }: {
  entry: MudCostEntry | null
  onClose: () => void
  onSave: (entry: MudCostEntry, payload: { amount: string; remarks: string }) => Promise<void>
}) {
  const [amount, setAmount] = useState('')
  const [remarks, setRemarks] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    setAmount(entry?.opening_stock ?? '')
    setRemarks(entry?.opening_stock_remarks ?? '')
    setError('')
  }, [entry])

  const submit = async () => {
    if (!entry) return
    const validFormat = /^(?:\d+|\d*\.\d{1,10})$/.test(amount.trim())
    const [whole = '0', fraction = ''] = amount.trim().split('.')
    const scaled = validFormat ? BigInt(whole || '0') * 10_000_000_000n + BigInt(fraction.padEnd(10, '0')) : 0n
    if (!validFormat || scaled > 9999999999999999999999999n) {
      setError('Enter a non-negative opening stock below 1,000,000,000,000,000 with up to 10 decimal places.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await onSave(entry, { amount: amount.trim(), remarks: remarks.trim() })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Opening stock could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  return <FormDialog
    open={Boolean(entry)}
    title="Correct initial opening stock"
    subtitle={entry ? `${entry.well_code} · ${entry.section_label} · ${entry.entry_date}` : undefined}
    onClose={onClose}
    onSubmit={submit}
    busy={saving}
    busyLabel="Recalculating section…"
    submitLabel="Save opening stock"
  >
    <Box display="grid" gap={1.6}>
      <TextField label="Initial opening stock (bbl)" type="number" value={amount}
        onChange={event => setAmount(event.target.value)} required
        inputProps={{ min: 0, step: '0.0000000001' }}/>
      <TextField label="Opening stock remarks" value={remarks} multiline minRows={2}
        onChange={event => setRemarks(event.target.value)} inputProps={{ maxLength: 500 }}/>
      <ErrorMessage message={error}/>
      <Alert severity="info">
        This corrects the initial inventory for this section’s configured mud type, not a daily carry-forward.
        All later stock balances, ALPHA, BETA, Cost/BBL and reconciled costs are recalculated.
        The correction is recorded in the audit log.
      </Alert>
    </Box>
  </FormDialog>
}

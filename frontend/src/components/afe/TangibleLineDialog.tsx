import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Divider,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import { AddRounded, DeleteOutlineRounded } from '@mui/icons-material'
import { FormDialog } from '../Common'
import {
  amountText,
  newKey,
  toNumber,
  type AfeReference,
  type TangibleLineInput,
} from '../../lib/afe'
import { FactPanel, TangiblePicker } from './LinePickers'

type TangibleEntry = {
  id: string
  tangible_id: string
  quantity: string
  override_rate: string | null
  remarks: string
}

type Props = {
  open: boolean
  initial: TangibleLineInput | null
  reference: AfeReference
  onClose: () => void
  onSave: (lines: TangibleLineInput[]) => void
}

// Tangibles are priced at the captured master rate unless an override is entered.
export function TangibleLineDialog({ open, initial, reference, onClose, onSave }: Props) {
  const [entries, setEntries] = useState<TangibleEntry[]>([])
  const [baselineState, setBaselineState] = useState<string>('')
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    if (!open) return
    if (initial) {
      setEntries([{
        id: initial.client_key || newKey(),
        tangible_id: initial.tangible_id,
        quantity: initial.quantity || '1',
        override_rate: initial.override_rate,
        remarks: initial.remarks || '',
      }])
    } else {
      setEntries([{
        id: newKey(),
        tangible_id: '',
        quantity: '1',
        override_rate: null,
        remarks: '',
      }])
    }
    setSubmitted(false)
  }, [open, initial])

  useEffect(() => {
    if (open && baselineState === '') {
      setBaselineState(JSON.stringify(entries))
    }
  }, [open, baselineState, entries])

  const currentState = JSON.stringify(entries)
  const dirty = baselineState !== '' && currentState !== baselineState

  const addEntry = () => {
    setEntries(prev => [
      ...prev,
      {
        id: newKey(),
        tangible_id: '',
        quantity: '1',
        override_rate: null,
        remarks: '',
      },
    ])
  }

  const updateEntry = (id: string, patch: Partial<TangibleEntry>) => {
    setEntries(prev => prev.map(entry => (entry.id === id ? { ...entry, ...patch } : entry)))
  }

  const removeEntry = (id: string) => {
    if (entries.length <= 1) return
    setEntries(prev => prev.filter(entry => entry.id !== id))
  }

  const totalQuantity = useMemo(() => {
    return entries.reduce((sum, entry) => sum + toNumber(entry.quantity), 0)
  }, [entries])

  const errors: string[] = []
  if (!entries.length) errors.push('Add at least one tangible line.')
  entries.forEach((entry, idx) => {
    if (!entry.tangible_id) errors.push(`Tangible #${idx + 1}: Select a tangible item from Master Data.`)
    if (toNumber(entry.quantity) < 0 || entry.quantity === '') errors.push(`Tangible #${idx + 1}: Quantity must be zero or greater.`)
  })

  const handleSave = () => {
    setSubmitted(true)
    if (errors.length > 0) return

    const lines: TangibleLineInput[] = entries.map(entry => ({
      client_key: initial?.client_key && entries.length === 1 ? initial.client_key : entry.id || newKey(),
      tangible_id: entry.tangible_id,
      quantity: entry.quantity,
      override_rate: entry.override_rate || null,
      remarks: entry.remarks.trim(),
    }))
    onSave(lines)
  }

  const dialogTitle = initial ? 'Edit tangible line' : 'Add tangibles'
  const submitText = initial
    ? 'Save line'
    : entries.length > 1
      ? `Add ${entries.length} tangibles`
      : 'Add tangible'

  return (
    <FormDialog
      open={open}
      title={dialogTitle}
      subtitle="Search Master Data by code, name, manufacturer, description or category. Multiple items can be added and saved as separate lines."
      onClose={onClose}
      onSubmit={handleSave}
      dirty={dirty}
      submitLabel={submitText}
      maxWidth="md"
    >
      <Box display="grid" gap={2}>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography fontSize={12} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={0.5}>
            Tangible items list ({entries.length})
          </Typography>
          {!initial && (
            <Button size="small" startIcon={<AddRounded sx={{ fontSize: 16 }} />} onClick={addEntry} variant="outlined">
              Add tangible
            </Button>
          )}
        </Box>

        <Box display="grid" gap={1.8}>
          {entries.map((entry, index) => {
            const item = reference.tangibles.find(t => t.id === entry.tangible_id) ?? null
            const noRate = Boolean(item) && toNumber(item?.captured_rate) === 0 && !entry.override_rate
            return (
              <Paper key={entry.id} variant="outlined" sx={{ p: 1.8, borderRadius: 1.5 }}>
                <Box display="flex" justifyContent="space-between" alignItems="center" mb={1.2}>
                  <Typography fontSize={12} fontWeight={800} color="primary">
                    Tangible item #{index + 1}
                  </Typography>
                  {!initial && entries.length > 1 && (
                    <Button size="small" color="error" startIcon={<DeleteOutlineRounded sx={{ fontSize: 16 }} />} onClick={() => removeEntry(entry.id)}>
                      Remove
                    </Button>
                  )}
                </Box>

                <Box display="grid" gap={1.5}>
                  <TangiblePicker
                    value={entry.tangible_id}
                    options={reference.tangibles}
                    onChange={id => updateEntry(entry.id, { tangible_id: id })}
                    error={submitted && !entry.tangible_id}
                  />

                  {item && (
                    <FactPanel
                      rows={[
                        { label: 'Manufacturer', value: item.manufacturer_name },
                        { label: 'Description', value: item.description },
                        { label: 'Category', value: [item.category_name, item.subcategory_name].filter(Boolean).join(' › ') },
                        { label: 'Scope', value: item.scope },
                        { label: 'Unit of measure', value: item.uom },
                        { label: 'Master rate', value: amountText(item.captured_rate, item.currency) },
                      ]}
                    />
                  )}

                  <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                    <TextField
                      size="small"
                      label={`Quantity${item?.uom ? ` (${item.uom})` : ''}`}
                      required
                      value={entry.quantity}
                      onChange={e => updateEntry(entry.id, { quantity: e.target.value.replace(/[^0-9.]/g, '') })}
                      inputProps={{ inputMode: 'decimal' }}
                      error={submitted && (toNumber(entry.quantity) < 0 || entry.quantity === '')}
                    />

                    <TextField
                      size="small"
                      label="Override unit rate (optional)"
                      value={entry.override_rate ?? ''}
                      onChange={e => updateEntry(entry.id, { override_rate: e.target.value.replace(/[^0-9.]/g, '') || null })}
                      inputProps={{ inputMode: 'decimal' }}
                      helperText={item ? `Master rate: ${amountText(item.captured_rate, item.currency)}` : 'Leave empty to use master rate.'}
                    />

                    <TextField
                      size="small"
                      label="Remarks (optional)"
                      value={entry.remarks}
                      onChange={e => updateEntry(entry.id, { remarks: e.target.value })}
                      inputProps={{ maxLength: 500 }}
                      sx={{ gridColumn: '1 / -1' }}
                    />
                  </Box>

                  {noRate && (
                    <Alert severity="warning" sx={{ py: 0.5 }}>
                      This tangible has no master rate. Enter an override rate or the line will be priced at zero.
                    </Alert>
                  )}
                </Box>
              </Paper>
            )
          })}
        </Box>

        <Box p={1.2} display="flex" justifyContent="space-between" alignItems="center" bgcolor="action.hover" borderRadius={1}>
          <Typography fontSize={12} color="text.secondary">
            {entries.length} tangible item{entries.length === 1 ? '' : 's'}
          </Typography>
          <Typography fontSize={13} fontWeight={700}>
            Total quantity: {totalQuantity}
          </Typography>
        </Box>

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
          Each item will be saved as an individual tangible line under this AFE estimate.
        </Typography>
      </Box>
    </FormDialog>
  )
}

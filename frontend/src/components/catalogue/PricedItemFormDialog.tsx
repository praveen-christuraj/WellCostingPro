import { useState } from 'react'
import { Box, MenuItem, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog } from '../Common'
import { MasterSelect } from './MasterSelect'
import { OptionSelect } from './OptionSelect'
import {
  formToPayload,
  previewFinalCost,
  type FieldDef,
  type FormState,
  type PricedRecord,
  type TypeConfig,
} from '../../lib/catalogue'

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <Typography fontSize={11} fontWeight={800} letterSpacing={1.1} color="text.secondary" textTransform="uppercase" sx={{ mt: .5 }}>{children}</Typography>
}

const WIDE_KEYS = new Set(['description', 'remarks'])

// One dialog for create and edit of any priced item. Rates are only entered on create;
// later price changes go through the Revise rate dialog so the history is kept.
export function PricedItemFormDialog({ config, open, mode, title, form, setForm, record, busy, error, onClose, onSubmit }: {
  config: TypeConfig
  open: boolean
  mode: 'create' | 'edit'
  title: string
  form: FormState
  setForm: (patch: FormState) => void
  record?: PricedRecord | null
  busy: boolean
  error: string
  onClose: () => void
  onSubmit: (payload: Record<string, unknown>) => void
}) {
  const [localError, setLocalError] = useState('')
  const master = config.fields.filter(field => field.section === 'master')
  const rate = config.fields.filter(field => field.section === 'rate')

  const setField = (key: string, value: string) => {
    const patch: FormState = { [key]: value }
    // Changing a parent clears children that belong to it.
    for (const field of config.fields) if (field.parentKey === key) patch[field.key] = ''
    setForm(patch)
  }

  const submit = () => {
    const missing = config.fields
      .filter(field => field.required && (mode === 'create' || field.section === 'master'))
      .filter(field => !(form[field.key] ?? '').trim())
      .map(field => field.label)
    if (missing.length) {
      setLocalError(`Complete the required fields: ${missing.join(', ')}.`)
      return
    }
    setLocalError('')
    onSubmit(formToPayload(config, form, mode))
  }

  const currentLabel = (field: FieldDef) => (record ? (record[field.key.replace(/_id$/, '_name')] as string | null) ?? null : null)

  const renderField = (field: FieldDef) => {
    const value = form[field.key] ?? ''
    const common = { fullWidth: true, required: field.required, helperText: field.help }
    const wide = WIDE_KEYS.has(field.key) ? { gridColumn: { sm: '1 / -1' } } : {}
    switch (field.kind) {
      case 'text':
        return <TextField key={field.key} label={field.label} value={value} onChange={event => setField(field.key, event.target.value)}
          inputProps={{ maxLength: field.maxLength, placeholder: field.placeholder }} sx={wide} {...common}/>
      case 'textarea':
        return <TextField key={field.key} label={field.label} value={value} onChange={event => setField(field.key, event.target.value)}
          multiline minRows={2} inputProps={{ maxLength: field.maxLength }} sx={wide} {...common}/>
      case 'number':
        return <TextField key={field.key} label={field.label} type="number" value={value} onChange={event => setField(field.key, event.target.value)}
          inputProps={{ min: 0, step: 'any' }} sx={wide} {...common}/>
      case 'date':
        return <TextField key={field.key} label={field.label} type="date" value={value} onChange={event => setField(field.key, event.target.value)}
          InputLabelProps={{ shrink: true }} sx={wide} {...common}/>
      case 'choice':
        return <TextField key={field.key} select label={field.label} value={value} onChange={event => setField(field.key, event.target.value)} sx={wide} {...common}>
          {(field.choices ?? []).map(choice => <MenuItem key={choice} value={choice}>{choice}</MenuItem>)}
        </TextField>
      case 'option':
        return <Box key={field.key} sx={wide}>
          <OptionSelect
            label={field.label}
            listKey={field.listKey!}
            value={value}
            currentLabel={currentLabel(field)}
            required={field.required}
            helper={field.help}
            parentId={field.parentKey ? form[field.parentKey] : undefined}
            parentLabel={field.parentKey ? config.fields.find(item => item.key === field.parentKey)?.label : undefined}
            onChange={id => setField(field.key, id)}
            onError={setLocalError}
          />
        </Box>
      case 'master':
        return <Box key={field.key} sx={wide}>
          <MasterSelect
            label={field.label}
            source={field.masterSource!}
            value={value}
            required={field.required}
            helper={field.help}
            onChange={code => setField(field.key, code)}
            onError={setLocalError}
          />
        </Box>
      default:
        return null
    }
  }

  const uplift = config.priced === 'uplift'
  const preview = uplift ? previewFinalCost(form.unit_rate ?? '', form.cost_uplift ?? '') : null

  return <FormDialog
    open={open}
    title={title}
    subtitle={mode === 'create'
      ? 'Codes are entered by you and must be unique. The first rate becomes revision 1 of the price history.'
      : 'Price changes are not made here. Use Revise rate so the history records the reason and the effective date.'}
    onClose={() => { if (!busy) { setLocalError(''); onClose() } }}
    onSubmit={submit}
    busy={busy}
    submitLabel={mode === 'create' ? `Create ${config.singular}` : 'Save changes'}
  >
    <Box display="grid" gap={2} pt={.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
      <Box sx={{ gridColumn: { sm: '1 / -1' } }}><SectionTitle>Item details</SectionTitle></Box>
      {master.map(renderField)}
      {mode === 'create' && <>
        <Box sx={{ gridColumn: { sm: '1 / -1' }, mt: 1 }}><SectionTitle>Rate and price history</SectionTitle></Box>
        {rate.map(renderField)}
        {uplift && <Box sx={{ gridColumn: { sm: '1 / -1' } }}>
          <Typography fontSize={12.5} color="text.secondary">Final cost preview (rate × uplift ÷ 100): <strong>{preview}</strong></Typography>
        </Box>}
      </>}
    </Box>
    <ErrorMessage message={localError || error}/>
  </FormDialog>
}

import { useEffect, useState } from 'react'
import { Autocomplete, Box, CircularProgress, TextField, Typography } from '@mui/material'
import { api, body } from '../../lib/api'
import { OPTION_LIST_LABELS, type CatalogueOption, type OptionListKey } from '../../lib/catalogue'

type Choice = { id: string; value: string; isNew?: boolean; removed?: boolean }

// A dropdown backed by Catalogue Lists. Users pick an active value, or type a new one and
// choose "Add ..." to create it on the spot (audited). Dependent lists (subcategory) load
// only the values under the selected parent.
export function OptionSelect({ label, listKey, value, currentLabel, onChange, required = false, parentId, parentLabel, helper, disabled = false, onError }: {
  label: string
  listKey: OptionListKey
  value: string
  currentLabel?: string | null
  onChange: (id: string) => void
  required?: boolean
  parentId?: string
  parentLabel?: string
  helper?: string
  disabled?: boolean
  onError?: (message: string) => void
}) {
  const [options, setOptions] = useState<CatalogueOption[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [input, setInput] = useState('')
  const needsParent = listKey === 'tangible_subcategory'
  const blockedByParent = needsParent && !parentId

  const load = async () => {
    if (blockedByParent) { setOptions([]); return }
    setLoading(true)
    try {
      const query = new URLSearchParams({ list_key: listKey })
      if (parentId) query.set('parent_id', parentId)
      setOptions(await api<CatalogueOption[]>(`/master-data/catalogue-options?${query.toString()}`))
    } catch (caught) {
      onError?.(caught instanceof Error ? caught.message : 'Could not load the list')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [listKey, parentId]) // eslint-disable-line react-hooks/exhaustive-deps

  const active = options.filter(option => !option.is_deleted)
  const selectedOption = active.find(option => option.id === value)
  const selected: Choice | null = value
    ? selectedOption
      ? { id: selectedOption.id, value: selectedOption.value }
      : { id: value, value: `${currentLabel ?? 'Removed value'} (removed)`, removed: true }
    : null

  const create = async (text: string) => {
    setCreating(true)
    try {
      const created = await api<CatalogueOption>('/master-data/catalogue-options', {
        method: 'POST',
        body: body({ list_key: listKey, value: text, parent_id: parentId || null }),
      })
      await load()
      onChange(created.id)
    } catch (caught) {
      onError?.(caught instanceof Error ? caught.message : 'Could not add this value')
    } finally {
      setCreating(false)
    }
  }

  const choices: Choice[] = active.map(option => ({ id: option.id, value: option.value }))
  const typed = input.trim()
  const exists = active.some(option => option.value.toLowerCase() === typed.toLowerCase())
  const canAdd = !!typed && !exists && !blockedByParent
  const withNew: Choice[] = canAdd ? [...choices, { id: '__new__', value: typed, isNew: true }] : choices

  return <Autocomplete<Choice, false, false, false>
    options={withNew}
    value={selected}
    inputValue={input}
    onInputChange={(_event, next, reason) => { if (reason !== 'reset') setInput(next) }}
    onChange={(_event, choice) => {
      if (!choice) { onChange(''); return }
      if (choice.isNew) { void create(choice.value); return }
      onChange(choice.id)
    }}
    getOptionLabel={option => option.value}
    isOptionEqualToValue={(option, current) => option.id === current.id}
    filterOptions={(list, state) => {
      const query = state.inputValue.trim().toLowerCase()
      return list.filter(option => option.isNew || option.value.toLowerCase().includes(query))
    }}
    renderOption={(props, option) => <li {...props} key={option.id}>
      {option.isNew
        ? <Typography fontSize={13} color="primary.main" fontWeight={700}>Add “{option.value}” to {OPTION_LIST_LABELS[listKey].toLowerCase()}</Typography>
        : <Typography fontSize={13}>{option.value}</Typography>}
    </li>}
    loading={loading || creating}
    disabled={disabled || blockedByParent}
    noOptionsText={blockedByParent ? `Select a ${parentLabel?.toLowerCase() ?? 'parent'} first` : 'No values yet. Type one to add it.'}
    renderInput={params => <TextField
      {...params}
      label={label}
      required={required}
      helperText={blockedByParent ? `Select a ${parentLabel?.toLowerCase() ?? 'parent'} first.` : helper}
      InputProps={{
        ...params.InputProps,
        endAdornment: <Box display="flex" alignItems="center">
          {(loading || creating) && <CircularProgress size={14}/>}
          {params.InputProps.endAdornment}
        </Box>,
      }}
    />}
    fullWidth
  />
}

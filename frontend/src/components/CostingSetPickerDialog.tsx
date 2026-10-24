import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Button, Chip, MenuItem, TextField, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { FormDialog, Tag } from './Common'
import { COSTING_SET_GROUPS, COSTING_SET_ITEM_KIND_LABEL, type CostingSet, type CostingSetGroup } from '../lib/costingSets'

type Props = {
  open: boolean
  group: CostingSetGroup
  destination: 'afe' | 'daily-cost'
  sets: CostingSet[]
  onClose: () => void
  onApply: (costingSet: CostingSet) => void
}

export function CostingSetPickerDialog({ open, group, destination, sets, onClose, onApply }: Props) {
  const choices = useMemo(() => sets.filter(set => set.item_group === group), [sets, group])
  const [selectedId, setSelectedId] = useState('')
  const selected = choices.find(set => set.id === selectedId) ?? null
  const availableItems = selected?.items.filter(item => item.is_available) ?? []
  const unavailableCount = (selected?.items.length ?? 0) - availableItems.length
  const groupLabel = COSTING_SET_GROUPS.find(item => item.value === group)?.label ?? group

  useEffect(() => {
    if (!open) return
    setSelectedId(choices.find(set => set.items.some(item => item.is_available))?.id ?? '')
  }, [open, choices])

  const apply = () => {
    if (selected && availableItems.length) onApply(selected)
  }

  return <FormDialog
    open={open}
    title={`Add a ${groupLabel.toLowerCase()} set`}
    subtitle={destination === 'afe'
      ? 'Choose a private or workspace-global set. The items are added as ordinary editable estimate lines; saved rates and amounts are not changed.'
      : 'Choose a private or workspace-global set. New lines use current AFE service rates and locked catalogue snapshots and remain editable until saved.'}
    onClose={onClose}
    onSubmit={apply}
    dirty={Boolean(selectedId)}
    submitLabel={`Add ${availableItems.length || ''} ${availableItems.length === 1 ? 'item' : 'items'}`.trim()}
    submitDisabled={!selected || availableItems.length === 0}
    maxWidth="sm"
  >
    <Box display="grid" gap={1.6}>
      {!choices.length
        ? <Alert severity="info">
          You do not have a saved {groupLabel.toLowerCase()} set yet.{' '}
          <Button component={RouterLink} to="/costing-sets" size="small" sx={{ verticalAlign: 'baseline' }} onClick={onClose}>Manage costing sets</Button>
        </Alert>
        : <TextField select label="Reusable set" value={selectedId} onChange={event => setSelectedId(event.target.value)}>
          {choices.map(set => <MenuItem key={set.id} value={set.id} disabled={!set.items.some(item => item.is_available)}>
            {set.name}{set.is_global ? ' (Global)' : ''} · {set.items.filter(item => item.is_available).length} available item(s)
          </MenuItem>)}
        </TextField>}

      {selected && <>
        {selected.description && <Typography fontSize={12.5} color="text.secondary">{selected.description}</Typography>}
        <Box display="flex" gap={.7} flexWrap="wrap" alignItems="center">
          {availableItems.map(item => <Chip
            key={item.id}
            size="small"
            variant="outlined"
            label={`${COSTING_SET_ITEM_KIND_LABEL[item.item_kind]} · ${item.display_name}`}
            sx={{ maxWidth: '100%' }}
          />)}
        </Box>
        {unavailableCount > 0 && <Alert severity="warning">
          {unavailableCount} item(s) in this set are no longer active in Master Data and will be skipped. Restore the items or update the set to use them.
        </Alert>}
        {destination === 'afe' && group === 'consumables' && <Alert severity="info">
          Lump-sum consumables are prepared as editable budget rows for the configured section/phase combinations. Drill bits are added as one editable line each; enter or confirm amounts before saving.
        </Alert>}
        {destination === 'daily-cost' && <Alert severity="info">
          Items without a matching price in this AFE’s locked rate baseline are skipped and reported; this shortcut never substitutes today’s live Master Data price.
        </Alert>}
        <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
          <Tag tone="info">{availableItems.length} available</Tag>
          {selected.items.length !== availableItems.length && <Tag tone="warning">{selected.items.length - availableItems.length} unavailable</Tag>}
          <Typography fontSize={11.5} color="text.secondary">Costing sets belong to your user account and are not shared with other workspace members.</Typography>
        </Box>
      </>}
    </Box>
  </FormDialog>
}

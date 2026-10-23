import { useMemo } from 'react'
import { Checkbox, MenuItem, Paper, Switch, TextField, Typography, Box, Button } from '@mui/material'
import { LIFECYCLE_OPTIONS, SCOPE_OPTIONS, type UsageReference, type UsageReportFilters, type UsageWellOption } from '../../lib/usageReports'

const ALL = ''

/** Well eligibility for the scope/lifecycle criteria, independent of the picker selection. */
export function wellMatches(well: UsageWellOption, filters: UsageReportFilters): boolean {
  if (filters.rigId && well.rig_id !== filters.rigId) return false
  if (filters.blockId && well.block_id !== filters.blockId) return false
  if (filters.scope && !well.scopes.includes(filters.scope)) return false
  if (filters.lifecycle) {
    const completion = filters.scope === 'completion'
    const status = completion ? well.completion_status : well.status
    const configStatus = completion ? well.completion_config_status : well.config_status
    if (filters.lifecycle === 'active' && status !== 'active') return false
    if (filters.lifecycle === 'completed' && status !== 'completed') return false
    if (filters.lifecycle === 'final_review' && configStatus !== 'final_review') return false
  }
  return true
}

export default function UsageReportFilters({
  reference,
  filters,
  onChange,
  disabled,
}: {
  reference: UsageReference | null
  filters: UsageReportFilters
  onChange: (patch: Partial<UsageReportFilters>) => void
  disabled?: boolean
}) {
  const eligibleWells = useMemo(
    () => (reference?.wells ?? []).filter(well => wellMatches(well, filters)),
    [reference, filters],
  )

  const blockOptions = reference?.blocks ?? []
  const rigOptions = reference?.rigs ?? []
  const currencyOptions = reference?.currencies ?? []

  const patch = (next: Partial<UsageReportFilters>) => onChange(next)

  return (
    <Paper variant="outlined" sx={{ p: 1.7, borderRadius: 2, mb: 1.7 }}>
      <Box display="grid" gap={1.3} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' } }}>
        <TextField
          select size="small" label="Block" value={filters.blockId} disabled={disabled}
          onChange={event => patch({ blockId: event.target.value, wellIds: [] })}
        >
          <MenuItem value={ALL}>All blocks</MenuItem>
          {blockOptions.map(option => <MenuItem key={option.id} value={option.id}>{option.block_code} — {option.block_name}</MenuItem>)}
        </TextField>
        <TextField
          select size="small" label="Rig" value={filters.rigId} disabled={disabled}
          onChange={event => patch({ rigId: event.target.value, wellIds: [] })}
        >
          <MenuItem value={ALL}>All rigs</MenuItem>
          {rigOptions.map(option => <MenuItem key={option.id} value={option.id}>{option.rig_code} — {option.rig_name}</MenuItem>)}
        </TextField>
        <TextField
          select size="small" label="Scope" value={filters.scope} disabled={disabled}
          onChange={event => patch({ scope: event.target.value as UsageReportFilters['scope'], wellIds: [] })}
        >
          {SCOPE_OPTIONS.map(option => <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>)}
        </TextField>
        <TextField
          select size="small" label="Well status" value={filters.lifecycle} disabled={disabled}
          onChange={event => patch({ lifecycle: event.target.value as UsageReportFilters['lifecycle'], wellIds: [] })}
        >
          {LIFECYCLE_OPTIONS.map(option => <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>)}
        </TextField>
        <TextField
          select size="small" label="Wells" disabled={disabled}
          value={filters.wellIds}
          SelectProps={{
            multiple: true,
            renderValue: (selected: unknown) => {
              const chosen = selected as string[]
              return chosen.length === 0
                ? 'All eligible wells'
                : `${chosen.length} well${chosen.length === 1 ? '' : 's'} selected`
            },
          }}
        >
          <MenuItem onClick={() => patch({ wellIds: eligibleWells.map(well => well.id) })}>
            <Typography fontSize={11.5} fontWeight={800}>Select all visible ({eligibleWells.length})</Typography>
          </MenuItem>
          <MenuItem onClick={() => patch({ wellIds: [] })}>
            <Typography fontSize={11.5} fontWeight={800}>Clear selection (all wells)</Typography>
          </MenuItem>
          {eligibleWells.map(well => (
            <MenuItem key={well.id} value={well.id}>
              <Checkbox size="small" checked={filters.wellIds.includes(well.id)} />
              <Box>
                <Typography fontSize={12.5}>{well.display_name}</Typography>
                <Typography fontSize={10.5} color="text.secondary">{well.scopes.join(' / ') || 'no scope'} · {well.status}</Typography>
              </Box>
            </MenuItem>
          ))}
          {eligibleWells.length === 0 && <MenuItem disabled>No wells match the current criteria</MenuItem>}
        </TextField>
        <TextField
          select size="small" label="Currency" value={filters.currency} disabled={disabled}
          onChange={event => patch({ currency: event.target.value })}
        >
          {currencyOptions.map(option => (
            <MenuItem key={option.code} value={option.code}>{option.code}{option.is_default ? ' (workspace default)' : ''}</MenuItem>
          ))}
        </TextField>
        <TextField
          size="small" type="date" label="From date" value={filters.dateFrom} disabled={disabled}
          onChange={event => patch({ dateFrom: event.target.value })} InputLabelProps={{ shrink: true }}
        />
        <TextField
          size="small" type="date" label="To date" value={filters.dateTo} disabled={disabled}
          onChange={event => patch({ dateTo: event.target.value })} InputLabelProps={{ shrink: true }}
        />
        <Box display="flex" alignItems="center" gap={1} sx={{ px: .5 }}>
          <Switch
            size="small" checked={filters.includeDraft} disabled={disabled}
            onChange={event => patch({ includeDraft: event.target.checked })}
            inputProps={{ 'aria-label': 'Include draft sheets' }}
          />
          <Box>
            <Typography fontSize={12.5} fontWeight={700}>Include draft sheets</Typography>
            <Typography fontSize={10.8} color="text.secondary">Off uses submitted sheets only</Typography>
          </Box>
        </Box>
      </Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mt={1}>
        <Typography color="text.secondary" fontSize={11.2}>
          {filters.wellIds.length === 0
            ? `All ${eligibleWells.length} eligible well${eligibleWells.length === 1 ? ' is' : 's are'} included.`
            : `${filters.wellIds.length} of ${eligibleWells.length} eligible wells selected.`}
        </Typography>
        <Button size="small" color="inherit" disabled={disabled || (
          !filters.blockId && !filters.rigId && !filters.scope && !filters.lifecycle
          && filters.wellIds.length === 0 && !filters.dateFrom && !filters.dateTo && filters.includeDraft
        )} onClick={() => patch({ blockId: '', rigId: '', wellIds: [], scope: '', lifecycle: '', dateFrom: '', dateTo: '', includeDraft: true })}>
          Reset filters
        </Button>
      </Box>
    </Paper>
  )
}

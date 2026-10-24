import { Alert, Box, Button, MenuItem, Paper, TextField, Typography } from '@mui/material'
import type { ActivityAllocation } from '../../lib/dailyAllocations'
import { deriveClassification, type DailyCostBaseline, type DailyCostReference } from '../../lib/dailyCost'

type Props = {
  value: ActivityAllocation[]
  onChange: (value: ActivityAllocation[]) => void
  baseline: DailyCostBaseline
  reference: DailyCostReference
  wellId: string
  scope: string
  timeBased?: boolean
}

export function ActivityAllocationEditor({ value, onChange, baseline, reference, wellId, scope, timeBased = true }: Props) {
  const update = (index: number, patch: Partial<ActivityAllocation>) => onChange(value.map((row, i) => i === index ? { ...row, ...patch } : row))
  const add = () => {
    const activity = reference.activities.find(item => !value.some(row => row.activity_id === item.id)) ?? reference.activities[0]
    const section = baseline.sections[0]
    onChange([...value, { activity_id: activity?.id ?? '', sub_activity_id: reference.sub_activities.find(sub => sub.well_id === wellId && (sub.scope ?? 'drilling') === scope && sub.activity_id === activity?.id)?.id ?? '', hole_section_id: section?.hole_section_id ?? '', phase_id: '', hours: String(Math.max(0, 24 - value.reduce((sum, row) => sum + Number(row.hours), 0))), actual_depth: '', actual_depth_unit: 'm' }])
  }
  return <Paper variant="outlined" sx={{ p: 2, display: 'grid', gap: 2 }}>
    <Box display="flex" gap={2} flexWrap="wrap" alignItems="center" justifyContent="space-between">
      <Typography variant="subtitle1">Activity allocation{timeBased ? ` · ${value.reduce((sum, row) => sum + Number(row.hours || 0), 0)} / 24 hours` : ' · no working hours required'}</Typography>
      <Button onClick={add}>Add activity allocation</Button>
    </Box>
    <Alert severity="info">Day-rate operating charges follow these hours. Mobilization, demobilization, fixed and per-section/per-service charges are charged once against the first allocation. Existing ledger rows remain individually editable. Leave this empty to use the common criteria.</Alert>
    {value.map((row, index) => {
      const section = baseline.sections.find(item => item.hole_section_id === row.hole_section_id)
      return <Box key={index} sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', md: 'repeat(4, minmax(0, 1fr))' } }}>
        <TextField select label={`Activity ${index + 1}`} value={row.activity_id} onChange={event => update(index, { activity_id: event.target.value, sub_activity_id: '' })}>{reference.activities.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name} · {deriveClassification(item)}</MenuItem>)}</TextField>
        <TextField select label="Well sub activity" value={row.sub_activity_id} onChange={event => update(index, { sub_activity_id: event.target.value })}>{reference.sub_activities.filter(item => item.well_id === wellId && (item.scope ?? 'drilling') === scope && item.activity_id === row.activity_id).map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}</MenuItem>)}</TextField>
        {timeBased && <TextField label="Working hours" type="number" value={row.hours} inputProps={{ min: 0, max: 24, step: 'any' }} onChange={event => update(index, { hours: event.target.value })}/>}
        <TextField select label="Hole section" value={row.hole_section_id} onChange={event => update(index, { hole_section_id: event.target.value, phase_id: '' })}><MenuItem value="">Whole well</MenuItem>{baseline.sections.map(item => <MenuItem key={item.hole_section_id} value={item.hole_section_id}>{item.section_name}</MenuItem>)}</TextField>
        <TextField select label="Phase" value={row.phase_id} onChange={event => update(index, { phase_id: event.target.value })}><MenuItem value="">All phases</MenuItem>{section?.phases.map(item => <MenuItem key={item.phase_id} value={item.phase_id}>{item.phase_name}</MenuItem>)}</TextField>
        <TextField label="Activity depth (optional)" type="number" value={row.actual_depth} inputProps={{ min: 0, step: 'any' }} onChange={event => update(index, { actual_depth: event.target.value })}/>
        <TextField select label="Depth unit" value={row.actual_depth_unit} onChange={event => update(index, { actual_depth_unit: event.target.value as 'm' | 'ft' })}><MenuItem value="m">m</MenuItem><MenuItem value="ft">ft</MenuItem></TextField>
        <Button color="error" onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove allocation {index + 1}</Button>
      </Box>
    })}
  </Paper>
}

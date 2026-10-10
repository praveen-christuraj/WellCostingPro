import { useEffect, useMemo, useRef, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { AddRounded, ArrowDownwardRounded, ArrowUpwardRounded, DeleteOutlineRounded } from '@mui/icons-material'
import { Alert, Box, Button, Card, CardContent, CircularProgress, Divider, MenuItem, Paper, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog, Tag } from './Common'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { MasterConfigurationOption, RigWellConfigurationOptions, Well, WellConfiguration } from '../lib/rigWell'

type PhaseInput = { key: string; phase_id: string; days: string; remarks: string }
type SectionInput = {
  key: string
  hole_section_id: string
  from_depth: string
  to_depth: string
  remarks: string
  phases: PhaseInput[]
}

const numberValue = (value: string) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

export function WellConfigurationDialog({ open, well, onClose, onSaved }: {
  open: boolean
  well: Well | null
  onClose: () => void
  onSaved: () => void
}) {
  const { can } = useAuth()
  const keyCounter = useRef(0)
  const nextKey = () => `row-${++keyCounter.current}`
  const [options, setOptions] = useState<RigWellConfigurationOptions>({ hole_sections: [], phases: [] })
  const [configuration, setConfiguration] = useState<WellConfiguration | null>(null)
  const [sections, setSections] = useState<SectionInput[]>([])
  const [depthUnit, setDepthUnit] = useState<'m' | 'ft'>('m')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const readOnly = !can('rig-well:update') || !configuration || configuration.status === 'completed' || configuration.config_status !== 'draft'
  const totalDays = useMemo(
    () => sections.reduce((total, section) => total + section.phases.reduce((sum, phase) => sum + numberValue(phase.days), 0), 0),
    [sections],
  )
  const finalDepth = sections.length ? sections[sections.length - 1].to_depth : ''

  useEffect(() => {
    if (!open || !well) return
    let current = true
    setLoading(true)
    setError('')
    setConfiguration(null)
    setSections([])
    Promise.all([
      api<RigWellConfigurationOptions>('/rig-well/configuration-options'),
      api<WellConfiguration>(`/rig-well/wells/${well.id}/configuration`),
    ]).then(([referenceOptions, result]) => {
      if (!current) return
      setOptions(referenceOptions)
      setConfiguration(result)
      setDepthUnit(result.depth_unit)
      setSections(result.sections.map(section => ({
        key: nextKey(),
        hole_section_id: section.hole_section_id,
        from_depth: String(section.from_depth),
        to_depth: String(section.to_depth),
        remarks: section.remarks ?? '',
        phases: section.phases.map(phase => ({
          key: nextKey(),
          phase_id: phase.phase_id,
          days: String(phase.days),
          remarks: phase.remarks ?? '',
        })),
      })))
    }).catch(caught => {
      if (current) setError(caught instanceof Error ? caught.message : 'Well configuration could not be loaded')
    }).finally(() => {
      if (current) setLoading(false)
    })
    return () => { current = false }
  }, [open, well?.id])

  const updateSection = (key: string, patch: Partial<SectionInput>) => {
    setSections(rows => rows.map(row => row.key === key ? { ...row, ...patch } : row))
  }
  const updatePhase = (sectionKey: string, phaseKey: string, patch: Partial<PhaseInput>) => {
    setSections(rows => rows.map(section => section.key === sectionKey
      ? { ...section, phases: section.phases.map(phase => phase.key === phaseKey ? { ...phase, ...patch } : phase) }
      : section))
  }
  const addSection = () => setSections(rows => [...rows, {
    key: nextKey(), hole_section_id: '', from_depth: '', to_depth: '', remarks: '', phases: [],
  }])
  const removeSection = (key: string) => setSections(rows => rows.filter(row => row.key !== key))
  const moveSection = (index: number, direction: -1 | 1) => {
    setSections(rows => {
      const target = index + direction
      if (target < 0 || target >= rows.length) return rows
      const reordered = [...rows]
      ;[reordered[index], reordered[target]] = [reordered[target], reordered[index]]
      return reordered
    })
  }
  const addPhase = (sectionKey: string) => setSections(rows => rows.map(section => section.key === sectionKey
    ? { ...section, phases: [...section.phases, { key: nextKey(), phase_id: '', days: '', remarks: '' }] }
    : section))
  const removePhase = (sectionKey: string, phaseKey: string) => setSections(rows => rows.map(section => section.key === sectionKey
    ? { ...section, phases: section.phases.filter(phase => phase.key !== phaseKey) }
    : section))

  const validate = (): string[] => {
    const problems: string[] = []
    if (!sections.length) return ['Add at least one hole section to create a well plan.']
    const seenSections = new Set<string>()
    let previousTo: number | null = null
    sections.forEach((section, index) => {
      const label = `Section ${index + 1}`
      if (!section.hole_section_id) problems.push(`${label}: choose a Hole Section.`)
      if (section.hole_section_id && seenSections.has(section.hole_section_id)) problems.push(`${label}: each Hole Section can appear once.`)
      if (section.hole_section_id) seenSections.add(section.hole_section_id)
      if (section.from_depth.trim() === '' || section.to_depth.trim() === '') {
        problems.push(`${label}: enter both start and end depth.`)
      } else {
        const from = Number(section.from_depth)
        const to = Number(section.to_depth)
        if (!Number.isFinite(from) || !Number.isFinite(to) || from < 0 || to < 0) problems.push(`${label}: depths must be non-negative numbers.`)
        else {
          if (from > to) problems.push(`${label}: start depth cannot exceed end depth.`)
          if (previousTo !== null && from < previousTo) problems.push(`${label}: start depth must be at or beyond the previous section's end depth.`)
          previousTo = to
        }
      }
      if (!section.phases.length) problems.push(`${label}: add at least one Phase.`)
      const seenPhases = new Set<string>()
      section.phases.forEach((phase, phaseIndex) => {
        if (!phase.phase_id) problems.push(`${label}, phase ${phaseIndex + 1}: choose a Phase.`)
        if (phase.phase_id && seenPhases.has(phase.phase_id)) problems.push(`${label}: a Phase can appear only once per section.`)
        if (phase.phase_id) seenPhases.add(phase.phase_id)
        if (phase.days.trim() === '' || !Number.isFinite(Number(phase.days)) || Number(phase.days) < 0) {
          problems.push(`${label}, phase ${phaseIndex + 1}: enter a non-negative day count.`)
        }
      })
    })
    return problems
  }

  const save = async () => {
    if (!well || !configuration) return
    setError('')
    const problems = validate()
    if (problems.length) {
      setError(problems.join(' '))
      return
    }
    setSaving(true)
    try {
      await api(`/rig-well/wells/${well.id}/configuration`, {
        method: 'PUT',
        body: body({
          depth_unit: depthUnit,
          sections: sections.map(section => ({
            hole_section_id: section.hole_section_id,
            from_depth: Number(section.from_depth),
            to_depth: Number(section.to_depth),
            remarks: section.remarks.trim(),
            phases: section.phases.map(phase => ({
              phase_id: phase.phase_id,
              days: Number(phase.days),
              remarks: phase.remarks.trim(),
            })),
          })),
        }),
      })
      onSaved()
      onClose()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The well plan could not be saved')
    } finally {
      setSaving(false)
    }
  }

  const optionById = (items: MasterConfigurationOption[], id: string) => items.find(item => item.id === id)

  return <FormDialog
    open={open}
    title={well ? `Well plan · ${well.well_code}` : 'Well plan'}
    subtitle={well ? `${well.rig_display}  /  ${well.well_name}. Build the well from Hole Sections, then assign one or more Master Data Phases per section.` : undefined}
    onClose={() => { if (!saving) { setError(''); onClose() } }}
    onSubmit={() => void save()}
    busy={saving}
    submitDisabled={loading || readOnly || !can('rig-well:update')}
    submitLabel="Save draft plan"
    maxWidth="lg"
  >
    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <Box display="grid" gap={2} pt={.5}>
      {configuration && <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap" sx={{ bgcolor: 'action.hover', borderRadius: 2, px: 2, py: 1.3 }}>
        <Box><Typography fontSize={12} fontWeight={800}>{configuration.rig_code} / {configuration.well_code} — {configuration.well_name}</Typography><Typography fontSize={11} color="text.secondary" mt={.25}>Plan total · {sections.length} section(s) · {totalDays.toFixed(2)} days</Typography></Box>
        <Box display="flex" gap={1} alignItems="center"><Tag tone={configuration.config_status === 'configured' ? 'success' : 'warning'}>{configuration.config_status}</Tag><Tag tone={configuration.status === 'completed' ? 'neutral' : 'info'}>{configuration.status}</Tag></Box>
      </Box>}

      {!can('rig-well:update') && configuration && <Alert severity="info">Your role has view-only access to this well plan. Contact an administrator if you need update access.</Alert>}
      {can('rig-well:update') && configuration && readOnly && <Alert severity="info">This well plan is read-only while the well is {configuration.status === 'completed' ? 'completed' : 'configured'}. Reopen the plan as Draft from the well register before editing.</Alert>}
      {options.hole_sections.length === 0 && <Alert severity="warning" action={can('master-data:read') ? <Button component={RouterLink} to="/master-data/records?module=hole-sections" size="small">Hole Sections</Button> : undefined}>No active Hole Sections are configured for this workspace yet.</Alert>}
      {options.phases.length === 0 && <Alert severity="warning" action={can('master-data:read') ? <Button component={RouterLink} to="/master-data/records?module=phases" size="small">Phases</Button> : undefined}>No active Phases are configured for this workspace yet.</Alert>}

      <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr 1fr' }} gap={1.5}>
        <TextField select label="Depth unit" value={depthUnit} disabled={readOnly} onChange={event => setDepthUnit(event.target.value as 'm' | 'ft')}>
          <MenuItem value="m">Metres (m)</MenuItem><MenuItem value="ft">Feet (ft)</MenuItem>
        </TextField>
        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, px: 1.5, py: 1 }}><Typography fontSize={10} fontWeight={800} color="text.secondary" textTransform="uppercase">Planned total depth</Typography><Typography fontSize={15} fontWeight={800} mt={.3}>{finalDepth ? `${Number(finalDepth).toLocaleString()} ${depthUnit}` : '—'}</Typography></Box>
        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, px: 1.5, py: 1 }}><Typography fontSize={10} fontWeight={800} color="text.secondary" textTransform="uppercase">Planned duration</Typography><Typography fontSize={15} fontWeight={800} mt={.3}>{totalDays.toFixed(2)} days</Typography></Box>
      </Box>

      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap">
        <Box><Typography fontWeight={800} fontSize={13}>Hole sections and phases</Typography><Typography color="text.secondary" fontSize={11.5} mt={.25}>Order sections from shallow to deep. Depth intervals may touch but cannot overlap.</Typography></Box>
        {!readOnly && <Button size="small" variant="outlined" startIcon={<AddRounded/>} onClick={addSection} disabled={!options.hole_sections.length}>Add section</Button>}
      </Box>

      {!sections.length && <Paper variant="outlined" sx={{ p: 3, textAlign: 'center', borderStyle: 'dashed' }}><Typography fontWeight={700} fontSize={13}>No plan sections yet</Typography><Typography color="text.secondary" fontSize={12} mt={.5}>Add the first Hole Section, then assign the planned Phase and days.</Typography></Paper>}

      {sections.map((section, sectionIndex) => {
        const phaseDays = section.phases.reduce((sum, phase) => sum + numberValue(phase.days), 0)
        const selectedSection = optionById(options.hole_sections, section.hole_section_id)
        return <Card key={section.key} variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent sx={{ p: '16px !important' }}>
            <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} mb={1.5}>
              <Box display="flex" alignItems="center" gap={1}><Box className="table-icon" sx={{ width: 28, height: 28, fontSize: 11, fontWeight: 800 }}>{String(sectionIndex + 1).padStart(2, '0')}</Box><Typography fontWeight={800} fontSize={13}>Hole Section {sectionIndex + 1}{selectedSection ? ` · ${selectedSection.code}` : ''}</Typography><Tag>{phaseDays.toFixed(2)} days</Tag></Box>
              {!readOnly && <Box display="flex" gap={.2}>
                <Button size="small" aria-label="Move section up" disabled={sectionIndex === 0} onClick={() => moveSection(sectionIndex, -1)}><ArrowUpwardRounded fontSize="small"/></Button>
                <Button size="small" aria-label="Move section down" disabled={sectionIndex === sections.length - 1} onClick={() => moveSection(sectionIndex, 1)}><ArrowDownwardRounded fontSize="small"/></Button>
                <Button size="small" color="error" aria-label="Remove section" onClick={() => removeSection(section.key)}><DeleteOutlineRounded fontSize="small"/></Button>
              </Box>}
            </Box>
            <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1.5fr 1fr 1fr 1fr' }} gap={1.2}>
              <TextField select label="Hole Section" required value={section.hole_section_id} disabled={readOnly} onChange={event => updateSection(section.key, { hole_section_id: event.target.value })}>
                {section.hole_section_id && !selectedSection && <MenuItem value={section.hole_section_id} disabled>Deleted or unavailable section · choose another</MenuItem>}
                {options.hole_sections.map(option => <MenuItem key={option.id} value={option.id}>{option.code} — {option.name}</MenuItem>)}
              </TextField>
              <TextField type="number" label={`From (${depthUnit})`} required value={section.from_depth} disabled={readOnly} inputProps={{ min: 0, step: .01 }} onChange={event => updateSection(section.key, { from_depth: event.target.value })}/>
              <TextField type="number" label={`To (${depthUnit})`} required value={section.to_depth} disabled={readOnly} inputProps={{ min: 0, step: .01 }} onChange={event => updateSection(section.key, { to_depth: event.target.value })}/>
              <TextField label="Section remarks" value={section.remarks} disabled={readOnly} inputProps={{ maxLength: 1000 }} onChange={event => updateSection(section.key, { remarks: event.target.value })}/>
            </Box>
            <Divider sx={{ my: 1.6 }}/>
            <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} mb={1}>
              <Box><Typography fontWeight={800} fontSize={12}>Phases</Typography><Typography color="text.secondary" fontSize={11}>Choose the phases applicable to this section and record planned days.</Typography></Box>
              {!readOnly && <Button size="small" startIcon={<AddRounded/>} onClick={() => addPhase(section.key)} disabled={!options.phases.length}>Add phase</Button>}
            </Box>
            {!section.phases.length && <Typography color="text.secondary" fontSize={12} sx={{ py: 1 }}>At least one Phase is needed for each section.</Typography>}
            <Box display="grid" gap={1}>
              {section.phases.map((phase, phaseIndex) => {
                const selectedPhase = optionById(options.phases, phase.phase_id)
                return <Box key={phase.key} display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1.6fr .6fr 1.4fr auto' }} gap={1} alignItems="center">
                  <TextField select label={`Phase ${phaseIndex + 1}`} required value={phase.phase_id} disabled={readOnly} onChange={event => updatePhase(section.key, phase.key, { phase_id: event.target.value })}>
                    {phase.phase_id && !selectedPhase && <MenuItem value={phase.phase_id} disabled>Deleted or unavailable phase · choose another</MenuItem>}
                    {options.phases.map(option => <MenuItem key={option.id} value={option.id}>{option.code} — {option.name}</MenuItem>)}
                  </TextField>
                  <TextField type="number" label="Days" required value={phase.days} disabled={readOnly} inputProps={{ min: 0, step: .01 }} onChange={event => updatePhase(section.key, phase.key, { days: event.target.value })}/>
                  <TextField label="Phase remarks" value={phase.remarks} disabled={readOnly} inputProps={{ maxLength: 1000 }} onChange={event => updatePhase(section.key, phase.key, { remarks: event.target.value })}/>
                  {!readOnly && <Button color="error" size="small" aria-label="Remove phase" onClick={() => removePhase(section.key, phase.key)}><DeleteOutlineRounded fontSize="small"/></Button>}
                </Box>
              })}
            </Box>
          </CardContent>
        </Card>
      })}
      <ErrorMessage message={error}/>
    </Box>}
  </FormDialog>
}

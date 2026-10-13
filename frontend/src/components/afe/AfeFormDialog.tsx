import { useEffect, useMemo, useState } from 'react'
import { Box, MenuItem, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog, useFormDirty } from '../Common'
import { api, body } from '../../lib/api'
import { AFE_TYPES, type Afe, type AfeReference, type AfeType } from '../../lib/afe'

type Form = { configuration_scope: 'drilling' | 'completion'; rig_id: string; well_id: string; afe_code: string; afe_name: string; afe_type: AfeType; remarks: string }

const emptyForm = (): Form => ({ configuration_scope: 'drilling', rig_id: '', well_id: '', afe_code: '', afe_name: '', afe_type: 'Drilling', remarks: '' })

// Create or edit an AFE header. Rig and well come from Rig & Well Management. The well must be active
// and its plan must be marked Configured, because the estimate prices against its sections and phases.
export function AfeFormDialog({ open, record, reference, onClose, onSaved }: {
  open: boolean
  record: Afe | null
  reference: AfeReference | null
  onClose: () => void
  onSaved: (afe: Afe, created: boolean) => void
}) {
  const [form, setForm] = useState<Form>(emptyForm)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const dirty = useFormDirty(form, open)

  useEffect(() => {
    if (!open) return
    setError('')
    setForm(record
      ? { configuration_scope: record.configuration_scope, rig_id: record.rig_id, well_id: record.well_id, afe_code: record.afe_code, afe_name: record.afe_name, afe_type: record.afe_type, remarks: record.remarks }
      : emptyForm())
  }, [open, record])

  const wells = useMemo(() => (reference?.wells ?? []).filter(well => well.rig_id === form.rig_id), [reference, form.rig_id])
  const selectedWell = wells.find(well => well.id === form.well_id)
  const scopeState = (well: AfeReference['wells'][number]) => form.configuration_scope === 'completion'
    ? { status: well.completion_status, config_status: well.completion_config_status, section_count: well.completion_section_count }
    : well
  const wellEligible = (well: AfeReference['wells'][number]) => {
    const plan = scopeState(well)
    return (plan.status === 'active' && plan.config_status === 'configured' && plan.section_count > 0)
      || (well.id === record?.well_id && form.configuration_scope === record.configuration_scope)
  }
  const wellNote = (well: AfeReference['wells'][number]) => {
    const plan = scopeState(well)
    return plan.section_count === 0 ? ' · no scoped plan saved' : plan.status !== 'active' ? ' · scope completed' : plan.config_status !== 'configured' ? ' · scope not configured' : ''
  }

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm(current => ({ ...current, [key]: value }))
  const setRig = (rigId: string) => setForm(current => ({ ...current, rig_id: rigId, well_id: '' }))

  const valid = Boolean(form.rig_id && form.well_id && form.afe_code.trim() && form.afe_name.trim() && form.afe_type && selectedWell && wellEligible(selectedWell))
  const noRigs = !reference?.rigs.length

  const save = async () => {
    setBusy(true)
    setError('')
    const payload = {
      rig_id: form.rig_id,
      well_id: form.well_id,
      afe_code: form.afe_code.trim().toUpperCase(),
      afe_name: form.afe_name.trim(),
      afe_type: form.afe_type,
      configuration_scope: form.configuration_scope,
      remarks: form.remarks.trim(),
    }
    try {
      const saved = record
        ? await api<Afe>(`/afe/afes/${record.id}`, { method: 'PATCH', body: body(payload) })
        : await api<Afe>('/afe/afes', { method: 'POST', body: body(payload) })
      onSaved(saved, !record)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The AFE could not be saved')
    } finally {
      setBusy(false)
    }
  }

  return <FormDialog
    open={open}
    title={record ? `Edit AFE ${record.afe_code}` : 'Create AFE'}
    subtitle="Each AFE is scoped to one well. A well can carry several AFEs, for example one drilling and one completion AFE, each with its own code."
    onClose={() => { if (!busy) onClose() }}
    onSubmit={() => void save()}
    busy={busy}
    dirty={dirty}
    submitDisabled={!valid || noRigs}
    submitLabel={record ? 'Save changes' : 'Create AFE'}
    maxWidth="md"
  >
    <Box display="grid" gap={2} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
      {noRigs && <Box sx={{ gridColumn: '1 / -1' }}><ErrorMessage message="Create an active rig and a well with a Configured plan in Rig & Well Management first."/></Box>}
      <TextField select label="Scoped configuration" required value={form.configuration_scope}
        onChange={event => set('configuration_scope', event.target.value as Form['configuration_scope'])}
        helperText="Only this plan supplies the estimate's sections, phases, depths and days."
        sx={{ gridColumn: '1 / -1' }}>
        <MenuItem value="drilling">Drilling Well Configuration</MenuItem>
        <MenuItem value="completion">Completion Well Configuration</MenuItem>
      </TextField>
      <TextField
        select label="Rig" required value={form.rig_id} onChange={event => setRig(event.target.value)}
        helperText="Only rigs from Rig & Well Management are listed."
      >
        {(reference?.rigs ?? []).map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
      </TextField>
      <TextField
        select label="Well" required value={form.well_id} onChange={event => set('well_id', event.target.value)}
        disabled={!form.rig_id}
        helperText={!form.rig_id ? 'Choose a rig first.' : !wells.length ? 'This rig has no wells yet.' : selectedWell && !wellEligible(selectedWell) ? 'This scoped plan is not active or not marked Configured.' : 'The selected scope must be active and have a plan marked Configured.'}
        error={Boolean(selectedWell) && !wellEligible(selectedWell!)}
      >
        {wells.map(well => <MenuItem key={well.id} value={well.id} disabled={!wellEligible(well)}>
          {well.display_name}{wellNote(well)}
        </MenuItem>)}
      </TextField>
      <TextField
        label="AFE code" required value={form.afe_code} onChange={event => set('afe_code', event.target.value)}
        helperText="Unique across the workspace. Stored in upper case."
        inputProps={{ maxLength: 50 }}
      />
      <TextField
        select label="AFE type" required value={form.afe_type} onChange={event => setForm(current => ({ ...current, afe_type: event.target.value as AfeType, configuration_scope: event.target.value === 'Completion' ? 'completion' : 'drilling' }))}
        helperText="Drilling or completion scope for this well."
      >
        {AFE_TYPES.map(type => <MenuItem key={type} value={type}>{type}</MenuItem>)}
      </TextField>
      <TextField
        label="AFE name" required value={form.afe_name} onChange={event => set('afe_name', event.target.value)}
        inputProps={{ maxLength: 200 }} sx={{ gridColumn: '1 / -1' }}
      />
      <TextField
        label="Remarks" value={form.remarks} onChange={event => set('remarks', event.target.value)}
        inputProps={{ maxLength: 1000 }} multiline minRows={2} sx={{ gridColumn: '1 / -1' }}
      />
      {record && <Typography fontSize={12} color="text.secondary" sx={{ gridColumn: '1 / -1' }}>
        Status is changed from AFE cost estimation, not here. Current status: {record.status}.
      </Typography>}
      <ErrorMessage message={error}/>
    </Box>
  </FormDialog>
}

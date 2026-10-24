import { useState } from 'react'
import { Alert, Box, Button, MenuItem, TextField } from '@mui/material'
import { FormDialog } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import type { DailyCostReference, WellScopeKey } from '../../lib/dailyCost'

type SubActivity = DailyCostReference['sub_activities'][number]

export function CreateWellSubActivity({ reference, wellId, scope, activityId, onCreated }: {
  reference: DailyCostReference; wellId: string; scope: WellScopeKey; activityId?: string; onCreated: (item: SubActivity) => void
}) {
  const { can } = useAuth()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ sub_activity_code: '', sub_activity_name: '', description: '', activity_id: '', responsible_party: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const well = reference.wells.find(item => item.id === wellId)
  const rig = reference.rigs.find(item => item.id === well?.rig_id)
  if (!can('rig-well:create')) return null
  const save = async () => {
    setBusy(true); setError('')
    try {
      const created = await api<SubActivity>('/rig-well/sub-activities', { method: 'POST', body: body({ ...form, well_id: wellId, scope }) })
      onCreated({ ...created, display_name: `${created.sub_activity_code} · ${created.sub_activity_name}` })
      setOpen(false)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not create the sub activity.') }
    finally { setBusy(false) }
  }
  return <>
    <Button onClick={() => { setForm({ sub_activity_code: '', sub_activity_name: '', description: '', activity_id: activityId ?? reference.activities[0]?.id ?? '', responsible_party: '' }); setError(''); setOpen(true) }}>Create well sub activity here</Button>
    <FormDialog open={open} title="Create well sub activity" subtitle={`Rig: ${rig?.rig_name ?? ''} · Well: ${well?.well_name ?? ''} · ${scope}. This context is fixed to the current sheet.`} onClose={() => setOpen(false)} onSubmit={() => void save()} busy={busy} submitLabel="Create sub activity">
      <Box display="grid" gap={2}>
        <TextField select required label="Activity" value={form.activity_id} onChange={event => setForm({ ...form, activity_id: event.target.value })}>{reference.activities.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}</MenuItem>)}</TextField>
        <TextField required label="Sub activity code" value={form.sub_activity_code} inputProps={{ maxLength: 50 }} onChange={event => setForm({ ...form, sub_activity_code: event.target.value })}/>
        <TextField required label="Sub activity name" value={form.sub_activity_name} inputProps={{ maxLength: 150 }} onChange={event => setForm({ ...form, sub_activity_name: event.target.value })}/>
        <TextField required label="Description" value={form.description} multiline inputProps={{ maxLength: 4000 }} onChange={event => setForm({ ...form, description: event.target.value })}/>
        <TextField label="Responsible party (NPT / UPA)" value={form.responsible_party} inputProps={{ maxLength: 200 }} onChange={event => setForm({ ...form, responsible_party: event.target.value })}/>
        {error && <Alert severity="error">{error}</Alert>}
      </Box>
    </FormDialog>
  </>
}

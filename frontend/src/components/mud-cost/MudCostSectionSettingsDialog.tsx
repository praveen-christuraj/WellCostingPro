import { useEffect, useState } from 'react'
import { Alert, Box, MenuItem, TextField } from '@mui/material'
import { ErrorMessage, FormDialog } from '../Common'
import {
  MUD_COST_MUD_TYPES, type MudCostMudType, type MudCostSectionSetting,
  type MudCostSectionSettingPayload,
} from '../../lib/mudCost'

type Props = {
  row: MudCostSectionSetting | null
  onClose: () => void
  onSave: (payload: MudCostSectionSettingPayload) => Promise<void>
}

/**
 * One dialog for the mud configuration that belongs to a section.
 *
 * The section is chosen before the dialog opens, so the form only collects the
 * mud type, its remark and the Cost/BBL base rate. OTHERS needs a remark and
 * every non-WBM type needs a positive rate; WBM stores no rate at all.
 */
export function MudCostSectionSettingsDialog({ row, onClose, onSave }: Props) {
  const [mudType, setMudType] = useState<MudCostMudType>('WBM')
  const [remarks, setRemarks] = useState('')
  const [baseRate, setBaseRate] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setMudType(row?.mud_type ?? 'WBM')
    setRemarks(row?.remarks ?? '')
    setBaseRate(row?.mud_type && row.mud_type !== 'WBM' ? row.base_rate : '')
    setError('')
    setSaving(false)
  }, [row])

  const submit = async () => {
    if (!row) return
    if (mudType === 'OTHERS' && !remarks.trim()) {
      setError('Remarks are mandatory when the mud type is OTHERS.')
      return
    }
    const rate = Number(baseRate)
    if (mudType !== 'WBM' && (!baseRate.trim() || !Number.isFinite(rate) || rate <= 0)) {
      setError('Enter a positive Cost/BBL base rate for this mud type.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await onSave({
        rig_id: row.rig_id,
        well_id: row.well_id,
        section_id: row.section_id,
        mud_type: mudType,
        remarks: remarks.trim(),
        base_rate: mudType === 'WBM' ? null : baseRate.trim(),
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The mud type configuration could not be saved')
    } finally {
      setSaving(false)
    }
  }

  return <FormDialog
    open={Boolean(row)}
    title={row ? `Mud type & Cost/BBL — ${row.section_code} · ${row.section_name}` : 'Mud type & Cost/BBL'}
    subtitle={row
      ? `${row.section_scope === 'completion' ? 'Completion' : 'Drilling'} section · ${row.section_label}. This configuration applies to every daily entry in this section.`
      : undefined}
    onClose={() => { if (!saving) onClose() }}
    onSubmit={submit}
    busy={saving}
    busyLabel="Saving mud type…"
    submitLabel="Save mud type"
  >
    <Box display="grid" gap={1.6} pt={0.5}>
      <TextField select size="small" label="Mud type" value={mudType} onChange={event => {
        const next = event.target.value as MudCostMudType
        setMudType(next)
        setError('')
        if (next === 'WBM') setBaseRate('')
      }} helperText={MUD_COST_MUD_TYPES.find(item => item.value === mudType)?.help}>
        {MUD_COST_MUD_TYPES.map(item => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
      </TextField>
      <TextField
        size="small"
        label={`Cost/BBL base rate${mudType === 'WBM' ? ' (not required for WBM)' : ''}`}
        value={baseRate}
        onChange={event => setBaseRate(event.target.value)}
        disabled={mudType === 'WBM'}
        type="number"
        required={mudType !== 'WBM'}
        inputProps={{ step: '0.0000000001', min: 0 }}
        helperText={row ? `Saved in ${row.currency || 'the workspace currency'} — the AFE standard currency of this well's daily cost sheets.` : ''}
      />
      <TextField
        size="small"
        label={`Remarks${mudType === 'OTHERS' ? ' (mandatory for OTHERS)' : ' (optional)'}`}
        value={remarks}
        onChange={event => setRemarks(event.target.value)}
        multiline
        minRows={3}
        inputProps={{ maxLength: 500 }}
        helperText={mudType === 'OTHERS' ? 'Explain which mud system this section uses.' : 'Optional context for the section mud system.'}
      />
      {error && <ErrorMessage message={error}/>}
      <Alert severity="info">
        Changing the base rate recalculates the reconciliation for every day of this section. The latest Cost/BBL is
        used for the cumulative reconciled amount in Well Cost Analysis.
      </Alert>
    </Box>
  </FormDialog>
}

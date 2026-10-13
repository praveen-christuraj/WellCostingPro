import { useEffect, useState } from 'react'
import { Alert, Box, FormControlLabel, MenuItem, Switch, TextField } from '@mui/material'
import { ErrorMessage, FormDialog } from '../Common'
import { api, body } from '../../lib/api'
import { displayDate, localToday, type DailyCostDay, type DailyCostWellOption } from '../../lib/dailyCost'
import { useCostPrint } from './DailyCostPrintSheet'

export function WellCostPrintDialog({ open, onClose, wells, initialWellId = '' }: {
  open: boolean; onClose: () => void; wells: DailyCostWellOption[]; initialWellId?: string
}) {
  const [wellId, setWellId] = useState('')
  const [mode, setMode] = useState('inception')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState(localToday())
  const [includeDraft, setIncludeDraft] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { print, printSheet } = useCostPrint()
  useEffect(() => {
    if (open) { setWellId(initialWellId); setError(''); setDateTo(localToday()) }
  }, [open, initialWellId])
  const invalidRange = mode === 'range' && (!dateFrom || !dateTo || dateFrom > dateTo)
  const submit = async () => {
    if (!wellId || invalidRange) return
    setBusy(true)
    setError('')
    try {
      const to = mode === 'inception' ? localToday() : dateTo
      const params = new URLSearchParams({ to, include_draft: String(includeDraft) })
      if (mode === 'range') params.set('from', dateFrom)
      const days = await api<DailyCostDay[]>(`/daily-cost/wells/${wellId}/cost-report?${params}`)
      if (!days.length) { setError('No saved daily sheets match this well and period.'); return }
      await api('/daily-cost/export-audit', { method: 'POST', body: body({
        module: 'well-cost-sheet', format: 'pdf', record_count: days.length, well_id: wellId,
        date_from: mode === 'range' ? dateFrom : null, date_to: to, include_draft: includeDraft,
      }) })
      const well = wells.find(item => item.id === wellId)
      print({ title: `Well costing sheet · ${well?.well_code ?? days[0].entry.well_code} · ${well?.well_name ?? days[0].entry.well_name}`,
        period: `${mode === 'range' ? displayDate(dateFrom) : 'Inception (first recorded cost)'} to ${displayDate(to)} · ${includeDraft ? 'Draft and submitted sheets' : 'Submitted sheets only'}`, days })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The costing sheet could not be printed')
    } finally { setBusy(false) }
  }
  return <>
    <FormDialog open={open} title="Print well costing sheet" subtitle="Print every saved section without grid pagination. Save as PDF using the browser print dialog. AFE and currency totals remain separate." onClose={onClose} onSubmit={() => void submit()} busy={busy} submitLabel="Print costing sheet" submitDisabled={!wellId || invalidRange}>
      <Box display="grid" gap={2}>
        <TextField select required label="Well" value={wellId} onChange={event => setWellId(event.target.value)}>
          <MenuItem value="">Select one well</MenuItem>
          {wells.map(well => <MenuItem key={well.id} value={well.id}>{well.well_code} · {well.well_name}</MenuItem>)}
        </TextField>
        <TextField select label="Report period" value={mode} onChange={event => setMode(event.target.value)}>
          <MenuItem value="inception">Inception to today</MenuItem><MenuItem value="range">Required date range</MenuItem>
        </TextField>
        {mode === 'range' && <Box display="grid" gap={2}>
          <TextField required type="date" label="From date" value={dateFrom} onChange={event => setDateFrom(event.target.value)} InputLabelProps={{ shrink: true }}/>
          <TextField required type="date" label="To date" value={dateTo} onChange={event => setDateTo(event.target.value)} InputLabelProps={{ shrink: true }}/>
          {invalidRange && <Alert severity="warning">Choose both dates with the start on or before the end date.</Alert>}
        </Box>}
        <FormControlLabel control={<Switch checked={includeDraft} onChange={event => setIncludeDraft(event.target.checked)}/>} label="Include draft sheets"/>
        <ErrorMessage message={error}/>
      </Box>
    </FormDialog>
    {printSheet}
  </>
}

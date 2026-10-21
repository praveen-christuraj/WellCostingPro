import { useEffect, useState } from 'react'
import { Alert, Box, FormControlLabel, MenuItem, Switch, TextField } from '@mui/material'
import { ErrorMessage, FormDialog } from '../Common'
import { api, body } from '../../lib/api'
import {
  costReportTitle, displayDate, localToday, type DailyCostDay, type DailyCostWellOption, type DailyCostWellSummary,
} from '../../lib/dailyCost'
import type { MudCostMaterialBalance, MudCostReconciliation } from '../../lib/mudCost'
import { useCostPrint } from './DailyCostPrintSheet'

export function WellCostPrintDialog({ open, onClose, wells, initialWellId = '' }: {
  open: boolean; onClose: () => void; wells: DailyCostWellOption[]; initialWellId?: string
}) {
  const [wellId, setWellId] = useState('')
  const [mode, setMode] = useState('inception')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState(localToday())
  const [includeDraft, setIncludeDraft] = useState(true)
  const [milestoneLabel, setMilestoneLabel] = useState('Spud date & time')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { print, printSheet } = useCostPrint()
  useEffect(() => {
    if (open) { setWellId(initialWellId); setError(''); setDateTo(localToday()); setMilestoneLabel('Spud date & time') }
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
      const well = wells.find(item => item.id === wellId)
      const mudParams = new URLSearchParams({
        rig_id: well?.rig_id ?? '', well_id: wellId, to, include_draft: String(includeDraft),
      })
      if (mode === 'range') mudParams.set('from', dateFrom)
      const mudBalanceParams = new URLSearchParams({ rig_id: well?.rig_id ?? '', well_id: wellId, view: 'section', to })
      if (mode === 'range') mudBalanceParams.set('from', dateFrom)
      const [days, summary, mudReconciliation, mudBalance] = await Promise.all([
        api<DailyCostDay[]>(`/daily-cost/wells/${wellId}/cost-report?${params}`),
        // A mixed-standard-currency well cannot expose one combined summary;
        // retain the existing per-AFE/currency print path in that case.
        api<DailyCostWellSummary>(`/daily-cost/wells/${wellId}/cost-summary?${params}`).catch(() => null),
        well?.rig_id
          ? api<MudCostReconciliation>(`/mud-cost/reconciliation?${mudParams}`).catch(() => null)
          : Promise.resolve(null),
        well?.rig_id
          ? api<MudCostMaterialBalance>(`/mud-cost/material-balance?${mudBalanceParams}`).catch(() => null)
          : Promise.resolve(null),
      ])
      if (!days.length) { setError('No saved daily sheets match this well and period.'); return }
      await api('/daily-cost/export-audit', { method: 'POST', body: body({
        module: 'well-cost-sheet', format: 'pdf', record_count: days.length, well_id: wellId,
        date_from: mode === 'range' ? dateFrom : null, date_to: to, include_draft: includeDraft,
      }) })
      // The title names the well scope(s) this report actually costs: each
      // printed sheet carries its AFE's scope, so the period — not the whole
      // well — decides between Drilling, Completions or both. The well summary's
      // AFE scopes are the fallback when a day has no progress payload.
      const dayScopes = days.map(day => day.progress?.scope).filter(Boolean)
      const scopes = dayScopes.length
        ? dayScopes
        : (summary?.well.afes.map(afe => afe.configuration_scope) ?? [])
      print({ title: costReportTitle('well', scopes, well?.well_name ?? days[0].entry.well_name),
        period: `${mode === 'range' ? displayDate(dateFrom) : 'Inception (first recorded cost)'} to ${displayDate(to)} · ${includeDraft ? 'Draft and submitted sheets' : 'Submitted sheets only'}`,
        days, overviewDays: days, summary, mudReconciliation, mudBalance, sections: well?.sections,
        reportKind: 'well', milestoneLabel: milestoneLabel.trim() || 'Spud date & time' })
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
        <TextField label="Milestone label in report" value={milestoneLabel} onChange={event => setMilestoneLabel(event.target.value)} inputProps={{ maxLength: 80 }} helperText="Edit the label when the milestone should read, for example, “Side track on date / time”. The recorded milestone date and time are unchanged."/>
        <ErrorMessage message={error}/>
      </Box>
    </FormDialog>
    {printSheet}
  </>
}

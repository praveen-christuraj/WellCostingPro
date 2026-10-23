import { useEffect, useState } from 'react'
import { PrintOutlined } from '@mui/icons-material'
import { Alert, Box, LinearProgress, Typography } from '@mui/material'
import { ErrorMessage, FormDialog } from '../Common'
import { api, body } from '../../lib/api'
import {
  costReportTitle, displayDate,
  type DailyCostDay, type DailyCostEntry, type DailyCostWellOption, type DailyCostWellSummary,
} from '../../lib/dailyCost'
import type { MudCostMaterialBalance, MudCostReconciliation } from '../../lib/mudCost'
import type { LihCostReport } from '../../lib/lihCost'
import { useCostPrint, type CostPrintReport } from './DailyCostPrintSheet'

/**
 * Bulk printing of saved daily cost registers.
 *
 * Each selected sheet contributes the first page of its cost report only — the
 * operational summary — and the pages are printed as one file, so the operator
 * can print the stack or save it with Print → Save as PDF.
 *
 * The cumulative page-one figures come from each sheet's own saved comparison,
 * which is already calculated through that sheet's cost date. The well's other
 * saved sheets are loaded once per well so section depths and the spud
 * milestone are resolved as they were on the report day.
 */
export function BulkDailyCostPrintDialog({ open, onClose, entries, wells }: {
  open: boolean
  onClose: () => void
  entries: DailyCostEntry[]
  wells: DailyCostWellOption[]
}) {
  const { printMany, printSheet } = useCostPrint()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')

  useEffect(() => {
    if (open) {
      setError('')
      setProgress('')
    }
  }, [open])

  const ordered = [...entries].sort((left, right) =>
    `${left.well_code}|${left.cost_date}|${left.afe_code}`.localeCompare(`${right.well_code}|${right.cost_date}|${right.afe_code}`),
  )
  const wellsInSelection = [...new Set(ordered.map(entry => `${entry.well_code} · ${entry.well_name}`))]
  const dates = ordered.map(entry => entry.cost_date).sort()
  const dateRange = dates.length
    ? dates[0] === dates[dates.length - 1]
      ? displayDate(dates[0])
      : `${displayDate(dates[0])} – ${displayDate(dates[dates.length - 1])}`
    : '—'

  /** Fetch a report context (mud and LIH panels) for one saved day. */
  const loadContext = async (entry: DailyCostEntry, rigId: string) => {
    const [mudReconciliation, mudBalance, lihReport] = await Promise.all([
      rigId
        ? api<MudCostReconciliation>(`/mud-cost/reconciliation?${new URLSearchParams({
          rig_id: rigId, well_id: entry.well_id, to: entry.cost_date, include_draft: 'true',
        })}`).catch(() => null)
        : Promise.resolve(null),
      rigId
        ? api<MudCostMaterialBalance>(`/mud-cost/material-balance?${new URLSearchParams({
          rig_id: rigId, well_id: entry.well_id, view: 'section', to: entry.cost_date,
        })}`).catch(() => null)
        : Promise.resolve(null),
      api<LihCostReport>(`/lih-cost/wells/${entry.well_id}/report?${new URLSearchParams({
        well_id: entry.well_id, from: entry.cost_date, to: entry.cost_date,
      })}`).catch(() => null),
    ])
    return { mudReconciliation, mudBalance, lihReport }
  }

  const submit = async () => {
    if (!ordered.length) return
    setBusy(true)
    setError('')
    setProgress('Loading the saved daily sheets…')
    try {
      // One saved-sheet history per well: every selected day is a row of it.
      const wellIds = [...new Set(ordered.map(entry => entry.well_id))]
      const historyByWell = new Map<string, DailyCostDay[]>()
      for (const wellId of wellIds) {
        const to = ordered.filter(entry => entry.well_id === wellId).map(entry => entry.cost_date).sort().at(-1)!
        const days = await api<DailyCostDay[]>(`/daily-cost/wells/${wellId}/cost-report?${new URLSearchParams({
          to, include_draft: 'true',
        })}`)
        historyByWell.set(wellId, days)
      }

      const reports: CostPrintReport[] = []
      const skipped: string[] = []
      for (const [index, entry] of ordered.entries()) {
        setProgress(`Preparing ${index + 1} of ${ordered.length} · ${entry.daily_cost_code}`)
        const history = historyByWell.get(entry.well_id) ?? []
        const saved = history.find(day => day.entry.id === entry.id)
        if (!saved) {
          skipped.push(entry.daily_cost_code)
          continue
        }
        const well = wells.find(item => item.id === entry.well_id)
        const context = await loadContext(entry, well?.rig_id ?? entry.rig_id)
        reports.push({
          title: costReportTitle('daily', [saved.progress?.scope], entry.well_name),
          period: displayDate(entry.cost_date),
          days: [saved],
          // The day's own AFE scope: depths and progress as they stood on that
          // date, never another AFE of the same well.
          overviewDays: history.filter(day =>
            day.entry.afe_id === entry.afe_id && day.entry.cost_date <= entry.cost_date),
          summary: null as DailyCostWellSummary | null,
          mudReconciliation: context.mudReconciliation,
          mudBalance: context.mudBalance,
          lihReport: context.lihReport,
          sections: well?.sections,
          reportKind: 'daily',
        })
      }

      if (!reports.length) {
        setError('None of the selected sheets could be read for printing. Refresh the register and try again.')
        return
      }
      await api('/daily-cost/export-audit', { method: 'POST', body: body({
        module: 'day-sheet', format: 'pdf', record_count: reports.length, include_deleted: false,
      }) })
      setProgress('Opening the print dialog…')
      printMany(reports)
      if (skipped.length) {
        setError(`${skipped.length} sheet(s) could not be included: ${skipped.slice(0, 5).join(', ')}${skipped.length > 5 ? '…' : ''}.`)
      } else {
        onClose()
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The selected daily cost reports could not be prepared')
    } finally {
      setBusy(false)
      setProgress('')
    }
  }

  return <>
    <FormDialog
      open={open}
      title="Print selected daily cost reports"
      subtitle="Only the first page of every selected cost report is printed — one operational summary per sheet, combined into a single printable file. Use the browser's print dialog to print or save it as a PDF."
      onClose={() => { if (!busy) onClose() }}
      onSubmit={() => void submit()}
      busy={busy}
      submitLabel={`Print ${ordered.length || ''} first page${ordered.length === 1 ? '' : 's'}`.trim()}
      submitDisabled={!ordered.length || busy}
      maxWidth="sm"
    >
      <Box display="grid" gap={1.4}>
        <Alert severity="info" sx={{ py: .5 }}>
          The milestone label and lead / lag printed on each page come from the register — no print-time entry is needed.
        </Alert>
        <Box display="grid" gap={.4}>
          <Typography fontSize={12.5} fontWeight={800}>{ordered.length} daily sheet{ordered.length === 1 ? '' : 's'} selected</Typography>
          <Typography fontSize={11.5} color="text.secondary">Report dates: {dateRange}</Typography>
          <Typography fontSize={11.5} color="text.secondary">Wells: {wellsInSelection.join(' · ') || '—'}</Typography>
        </Box>
        {busy && <Box>
          <LinearProgress/>
          <Typography fontSize={11.5} color="text.secondary" mt={.6}>{progress || 'Preparing…'}</Typography>
        </Box>}
        {error && <ErrorMessage message={error}/>}
        <Typography fontSize={11} color="text.secondary" display="flex" alignItems="center" gap={.6}>
          <PrintOutlined sx={{ fontSize: 16 }}/> The print dialog opens when all selected pages are ready.
        </Typography>
      </Box>
    </FormDialog>
    {printSheet}
  </>
}

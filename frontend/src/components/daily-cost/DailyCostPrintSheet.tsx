import { Fragment, useEffect, useState } from 'react'
import { createPortal, flushSync } from 'react-dom'
import { dailyMoney, displayDate, type DailyCostDay, type DailyCostLineOutput } from '../../lib/dailyCost'
import { formatDepthMeters } from '../../lib/units'

export type CostPrintReport = { title: string; period: string; days: DailyCostDay[] }

/** Reuses the existing AFE print layout: complete tables, not paginated grids. */
export function DailyCostPrintSheet({ report }: { report: CostPrintReport | null }) {
  if (!report) return null
  const groups = new Map<string, DailyCostDay[]>()
  for (const day of report.days) {
    const key = `${day.entry.afe_id}:${day.entry.standard_currency}`
    groups.set(key, [...(groups.get(key) ?? []), day])
  }
  return createPortal(<article className="afe-print-sheet" aria-hidden="true">
    <header>
      <div className="ps-eyebrow">WellCosting Pro · saved cost records</div>
      <h1>{report.title}</h1>
      <p>{report.period} · Printed {new Date().toLocaleString()}</p>
      <p>Draft sheets are identified below. Native amounts use the captured FX rate to reconcile to each AFE's standard currency. No amounts are combined across wells, AFEs or standard currencies.</p>
    </header>
    <section>
      <h2>Costing register · totals by AFE and currency for this report period</h2>
      {[...groups.entries()].map(([key, days]) => {
        const entry = days[0].entry
        const sum = (field: 'total_cost' | 'services_total' | 'consumables_total' | 'tangibles_total' | 'other_expenses_total') =>
          dailyMoney(days.reduce((total, day) => total + Number(day.entry[field]), 0), entry.standard_currency)
        return <Fragment key={key}>
          <h3>{entry.well_code} · {entry.afe_code} · {entry.afe_name} ({entry.standard_currency})</h3>
          <table><thead><tr><th>Date / daily sheet</th><th>Status</th><th>Actual depth (m)</th><th>Services</th><th>Consumables</th><th>Tangibles</th><th>Other expenses</th><th>Total</th><th>USD Total</th></tr></thead>
            <tbody>{days.map(day => <tr key={day.entry.id}>
              <td>{displayDate(day.entry.cost_date)} · {day.entry.daily_cost_code}</td><td>{day.entry.status}</td>
              <td className="num">{formatDepthMeters(day.entry.actual_depth, 'm')}</td>
              <td className="num">{dailyMoney(day.entry.services_total, entry.standard_currency)}</td>
              <td className="num">{dailyMoney(day.entry.consumables_total, entry.standard_currency)}</td>
              <td className="num">{dailyMoney(day.entry.tangibles_total, entry.standard_currency)}</td>
              <td className="num">{dailyMoney(day.entry.other_expenses_total, entry.standard_currency)}</td>
              <td className="num">{dailyMoney(day.entry.total_cost, entry.standard_currency)}</td>
              <td className="num">{dailyMoney(day.entry.total_cost_usd ?? day.entry.total_cost, 'USD')}</td>
            </tr>)}<tr className="ps-total"><th colSpan={3}>Period total · this AFE only</th><td className="num">{sum('services_total')}</td><td className="num">{sum('consumables_total')}</td><td className="num">{sum('tangibles_total')}</td><td className="num">{sum('other_expenses_total')}</td><td className="num">{sum('total_cost')}</td><td className="num">{dailyMoney(days.reduce((total, day) => total + Number(day.entry.total_cost_usd ?? day.entry.total_cost), 0), 'USD')}</td></tr></tbody>
          </table>
        </Fragment>
      })}
    </section>
    {report.days.map(day => <DailySections key={day.entry.id} day={day}/>)}
  </article>, document.body)
}

function DailySections({ day }: { day: DailyCostDay }) {
  const { entry, comparison } = day
  const money = (value: string) => dailyMoney(value, entry.standard_currency)
  const milestone = (value: string | null) => (value ? `${value.replace('T', ' ').slice(0, 16)} hrs` : '—')
  const progress = day.progress
  return <section>
    <h2>{entry.daily_cost_code} · {displayDate(entry.cost_date)}</h2>
    <h3>1. Well, AFE and daily sheet details</h3>
    <table><tbody>
      <tr><th>Well</th><td>{entry.well_code} · {entry.well_name}</td><th>Rig</th><td>{entry.rig_code} · {entry.rig_name}</td></tr>
      <tr><th>AFE</th><td>{entry.afe_code} · {entry.afe_name} ({entry.afe_status})</td><th>Sheet status</th><td>{entry.status} · {entry.standard_currency}{entry.is_deleted ? ` · Deleted ${entry.deleted_at}` : ''}</td></tr>
      {progress && <>
        <tr>
          <th>Well spud date &amp; time ({progress.scope_label.toLowerCase()})</th><td>{milestone(progress.spud_at)}</td>
          <th>{progress.progress_label}</th><td>{milestone(progress.progress_completed_at)}{progress.is_completed ? ' — day count stopped' : ''}</td>
        </tr>
        <tr>
          <th>Actual days (from spud, to sheet date)</th><td>{progress.actual_days ?? '—'}</td>
          <th>Planned days · difference (actual − planned)</th>
          <td>{Number(progress.planned_days).toFixed(3)} · {progress.days_variance === null ? '—' : `${Number(progress.days_variance) > 0 ? '+' : ''}${Number(progress.days_variance).toFixed(3)}`}</td>
        </tr>
      </>}
      <tr><th>Actual depth (standardized)</th><td>{formatDepthMeters(entry.actual_depth, 'm')}</td><th>USD total (FX {entry.usd_exchange_rate ?? '1'})</th><td>{dailyMoney(entry.total_cost_usd ?? entry.total_cost, 'USD')}</td></tr>
      <tr><th>Budget locked</th><td>{entry.budget_baseline_locked_at}</td><th>Rates locked</th><td>{entry.rate_baseline_locked_at}</td></tr>
      <tr><th>Created</th><td>{entry.created_at} · {entry.created_by}</td><th>Updated</th><td>{entry.updated_at} · {entry.updated_by}</td></tr>
      <tr><th>Submitted</th><td>{entry.submitted_at || '—'} · {entry.submitted_by || '—'}</td><th>Status remarks</th><td>{entry.status_remarks || '—'}</td></tr>
      <tr><th>Daily / shift remarks</th><td colSpan={3} className="ps-notes">{entry.remarks || '—'}</td></tr>
    </tbody></table>
    <h3>2. Daily actuals and this AFE's position as of {displayDate(comparison.effective_on)}</h3>
    <table><tbody>
      <tr><th>Daily actual</th><td>{money(entry.total_cost)}</td><th>Daily UPA / NPT (included in actual)</th><td>{money(entry.upa_total)} / {money(entry.npt_total)}</td></tr>
      <tr><th>Daily other expenses</th><td>{money(entry.other_expenses_total)}</td><th>Other expenses on this sheet</th><td>{day.other_expenses.length} line(s)</td></tr>
      <tr><th>Locked AFE budget</th><td>{money(comparison.planned_total)}</td><th>AFE actual to sheet date</th><td>{money(comparison.actual_to_date)}</td></tr>
      <tr><th>Less other expenses to sheet date</th><td>{money(comparison.other_expenses_to_date)}</td><th>Services, consumables and tangibles to sheet date</th><td>{money(comparison.tracked_actual_to_date)}</td></tr>
      <tr><th>AFE remaining</th><td>{money(comparison.balance)}</td><th>AFE UPA / NPT to sheet date</th><td>{money(comparison.upa_to_date)} / {money(comparison.npt_to_date)}</td></tr>
    </tbody></table>
    <p>Other expenses (Lost In Hole, hole problems, claims) carry no AFE allowance. They are recorded separately and deducted from the locked AFE total, which is why the remaining figure above is the AFE budget less every actual including those charges.</p>
    <p>AFE reconciliation includes {comparison.includes_draft_entries ? 'draft and submitted' : 'submitted'} sheets through the sheet date, including records outside a selected report period.</p>
    <PrintLines title="3. Services" lines={day.services} names={day.services.map(line => `${line.service_code} · ${line.service_name} · ${line.charging_basis} · ${line.charge_category}`)} standard={entry.standard_currency}/>
    <PrintLines title="4. Consumables" lines={day.consumables} names={day.consumables.map(line => `${line.category} · ${line.item_code} · ${line.item_name} · UOM ${line.uom}`)} standard={entry.standard_currency}/>
    <PrintLines title="5. Tangibles" lines={day.tangibles} names={day.tangibles.map(line => `${line.tangible_code} · ${line.tangible_name} · UOM ${line.uom}`)} standard={entry.standard_currency}/>
    <PrintLines title="6. Other expenses (LIH, hole problems and similar charges)" lines={day.other_expenses}
      names={day.other_expenses.map(line => `${line.expense_type_label}${line.expense_description ? ` · ${line.expense_description}` : ''}`)}
      standard={entry.standard_currency} remarkRequired/>
    <h3>7. AFE budget reconciliation</h3>
    <table><thead><tr><th>Budget line</th><th>Cost group</th><th>Planned</th><th>Actual to sheet date</th><th>Balance</th></tr></thead><tbody>
      {comparison.budget_lines.map(line => <tr key={line.budget_key}><td>{line.item_code} · {line.item_name}{line.is_planned ? '' : ' · unbudgeted'}</td><td>{line.cost_group}</td><td className="num">{money(line.planned)}</td><td className="num">{money(line.actual_to_date)}</td><td className="num">{money(line.balance)}</td></tr>)}
    </tbody></table>
    {day.warnings.length > 0 && <div className="ps-warnings"><strong>Sheet warnings</strong><ul>{day.warnings.map(warning => <li key={warning.code}>{warning.message}</li>)}</ul></div>}
  </section>
}

function PrintLines({ title, lines, names, standard, remarkRequired }: {
  title: string; names: string[]; standard: string
  lines: DailyCostLineOutput[]
  /** Other-expense remarks are mandatory, so the print says so instead of a dash. */
  remarkRequired?: boolean
}) {
  return <>
    <h3>{title} ({lines.length})</h3>
    {!lines.length ? <p className="ps-empty">No lines recorded.</p> : <table>
      <thead><tr><th>Item / service and classification</th><th>Section / phase</th><th>Actual depth (m)</th><th>Activity / sub activity</th><th>Quantity</th><th>Rate</th><th>Native amount</th><th>Standard amount</th></tr></thead>
      <tbody>{lines.map((line, index) => <Fragment key={line.id}>
        <tr><td>{names[index]}<div className="ps-sub">{line.classification}</div></td>
          <td>{line.section_code} · {line.section_name}<div className="ps-sub">{line.phase_code} · {line.phase_name}</div></td>
          <td className="num">{formatDepthMeters(line.actual_depth, 'm')}</td>
          <td>{line.activity_code} · {line.activity_name}<div className="ps-sub">{line.sub_activity_code} · {line.sub_activity_name}</div></td>
          <td>{line.quantity} {line.quantity_unit}</td><td className="num">{dailyMoney(line.effective_rate, line.currency)}</td>
          <td className="num">{dailyMoney(line.amount, line.currency)}</td><td className="num">{dailyMoney(line.standard_amount, standard)}</td></tr>
        <tr className="ps-component"><td colSpan={8}>
          <strong>Responsible party:</strong> {line.party_name || line.vendor_name || '—'} · Vendor {line.vendor_code} {line.vendor_name} · Sub activity party {line.sub_activity_party || '—'}<br/>
          <strong>Rate trace:</strong> {line.rate_source} · captured {dailyMoney(line.captured_rate, line.currency)} · FX {line.exchange_rate} to {standard} · USD {dailyMoney(line.usd_amount ?? line.standard_amount, 'USD')} · revision {line.rate_revision_number ?? '—'} · effective {displayDate(line.rate_effective_date)}<br/>
          <strong>Override:</strong> {line.override_rate === null ? 'None' : dailyMoney(line.override_rate, line.currency)} · {line.override_reason || '—'}<br/>
          <strong>Budget:</strong> {line.budget_name || 'Unbudgeted'} · {line.budget_key}<br/>
          <strong>Remarks{remarkRequired ? ' (mandatory)' : ''}:</strong> <span className="ps-notes">{line.remarks || '—'}</span>
        </td></tr>
      </Fragment>)}</tbody>
    </table>}
  </>
}

/** Mount the print-only portal synchronously before opening the browser dialog. */
export function useCostPrint() {
  const [report, setReport] = useState<CostPrintReport | null>(null)
  useEffect(() => {
    const clear = () => setReport(null)
    window.addEventListener('afterprint', clear)
    return () => window.removeEventListener('afterprint', clear)
  }, [])
  const print = (next: CostPrintReport) => {
    flushSync(() => setReport(next))
    window.print()
    // afterprint clears the portal, including in browsers with an asynchronous dialog.
  }
  return { print, printSheet: <DailyCostPrintSheet report={report}/> }
}

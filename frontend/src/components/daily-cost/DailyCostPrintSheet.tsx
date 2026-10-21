import { Fragment, useEffect, useState } from 'react'
import { createPortal, flushSync } from 'react-dom'
import {
  dailyMoney, displayDate, type DailyCostDay, type DailyCostLineOutput, type DailyCostSectionOption,
  type DailyCostWellSummary,
} from '../../lib/dailyCost'
import type { MudCostReconciliation } from '../../lib/mudCost'
import { formatDepthMeters } from '../../lib/units'

export type CostPrintReport = {
  title: string
  period: string
  days: DailyCostDay[]
  /** Cumulative rows used only by the model-report cover. Detail pages still use `days`. */
  overviewDays?: DailyCostDay[]
  summary?: DailyCostWellSummary | null
  mudReconciliation?: MudCostReconciliation | null
  sections?: DailyCostSectionOption[]
  reportKind?: 'daily' | 'well'
}

/** Reuses the existing AFE print layout: complete tables, not paginated grids. */
export function DailyCostPrintSheet({ report }: { report: CostPrintReport | null }) {
  if (!report) return null
  const groups = new Map<string, DailyCostDay[]>()
  for (const day of report.days) {
    const key = `${day.entry.afe_id}:${day.entry.standard_currency}`
    groups.set(key, [...(groups.get(key) ?? []), day])
  }
  return createPortal(<article className="afe-print-sheet daily-cost-print-sheet" aria-hidden="true">
    <ReportCover report={report}/>
    <div className="daily-report-details">
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
    </div>
  </article>, document.body)
}

type CoverIncident = { label: string; days: number; amount: number; party: string; remarks: string }

function asNumber(value: string | number | null | undefined) {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function percent(actual: number, planned: number) {
  return planned > 0 ? `${(actual / planned * 100).toFixed(1)}%` : '—'
}

function durationInDays(line: DailyCostLineOutput) {
  const quantity = asNumber(line.quantity)
  return line.quantity_unit === 'hours' ? quantity / 24 : line.quantity_unit === 'days' ? quantity : 0
}

function incidentRows(days: DailyCostDay[], classification: 'NPT' | 'UPA'): CoverIncident[] {
  const grouped = new Map<string, CoverIncident>()
  for (const day of days) {
    for (const line of [...(day.services ?? []), ...(day.consumables ?? []), ...(day.tangibles ?? []), ...(day.other_expenses ?? [])]) {
      if (line.classification !== classification) continue
      const party = line.party_name || line.vendor_name || line.sub_activity_party || '—'
      const remarks = line.remarks || line.override_reason || '—'
      const key = `${line.activity_code}|${line.activity_name}|${party}|${remarks}`
      const current = grouped.get(key) ?? {
        label: `${line.activity_code} · ${line.activity_name}`,
        days: 0, amount: 0, party, remarks,
      }
      current.days += durationInDays(line)
      current.amount += asNumber(line.standard_amount)
      grouped.set(key, current)
    }
  }
  return [...grouped.values()].sort((left, right) => right.amount - left.amount)
}

function ReportCover({ report }: { report: CostPrintReport }) {
  const detailDays = report.days
  const overviewDays = report.overviewDays?.length ? report.overviewDays : detailDays
  const latest = overviewDays[overviewDays.length - 1] ?? detailDays[0]
  if (!latest) return null
  const summary = report.summary
  // When a well contains incompatible AFE standard currencies, the API
  // deliberately withholds a combined summary. Keep the cover truthful by
  // using only the latest AFE/currency rather than adding unlike amounts.
  const coverDays = summary ? overviewDays : overviewDays.filter(day =>
    day.entry.afe_id === latest.entry.afe_id && day.entry.standard_currency === latest.entry.standard_currency)
  const currency = summary?.totals.currency || latest.entry.standard_currency
  const latestComparison = latest.comparison
  const budgetLines = summary?.budget_lines ?? latestComparison.budget_lines
  const groupLines = (group: string, limit: number) => budgetLines
    .filter(line => line.cost_group === group)
    .sort((left, right) => asNumber(right.actual_to_date) - asNumber(left.actual_to_date))
    .slice(0, limit)
  const services = groupLines('Services', 8)
  const consumables = groupLines('Consumables', 5)
  const groupPosition = (group: 'Services' | 'Consumables' | 'Tangibles') => {
    if (summary) {
      const factor = summary.factors.find(item => item.dimension === 'cost_group')?.rows.find(row => row.code === group)
      const actual = group === 'Services' ? summary.totals.services : group === 'Consumables' ? summary.totals.consumables : summary.totals.tangibles
      return { planned: asNumber(factor?.planned), actual: asNumber(actual) }
    }
    const groupRow = latestComparison.groups?.find(item => item.cost_group === group)
    return { planned: asNumber(groupRow?.planned), actual: asNumber(groupRow?.actual_to_date) }
  }
  const servicePosition = groupPosition('Services')
  const consumablePosition = groupPosition('Consumables')
  const tangiblePosition = groupPosition('Tangibles')
  const totalPlanned = asNumber(summary?.totals.planned ?? latestComparison.planned_total)
  const totalActual = asNumber(summary?.totals.comparison_actual ?? latestComparison.actual_to_date)
  const otherExpenses = asNumber(summary?.totals.other_expenses ?? latestComparison.other_expenses_to_date)
  const balance = asNumber(summary?.totals.comparison_balance ?? latestComparison.balance)
  const progressRows = report.reportKind === 'daily' && latest.progress ? [latest.progress] : (summary?.progress ?? (latest.progress ? [latest.progress] : []))
  const spud = progressRows.find(row => row.spud_at)?.spud_at
  const actualDays = progressRows.reduce((total, row) => total + asNumber(row.actual_days), 0)
  const plannedDays = progressRows.reduce((total, row) => total + asNumber(row.planned_days), 0)
  const sectionDepths = new Map<string, string>()
  for (const day of overviewDays) {
    for (const depth of day.entry.section_depths ?? []) sectionDepths.set(depth.hole_section_id ?? depth.section_code, depth.actual_depth)
  }
  const sections = report.sections?.length ? report.sections : [...sectionDepths.entries()].map(([key, depth]) => ({
    hole_section_id: key, section_code: key, section_name: key, from_depth: '0', to_depth: depth, total_days: '0', phases: [],
  }))
  const mudSections = report.mudReconciliation?.sections ?? summary?.mud_cost?.sections ?? []
  const npt = incidentRows(coverDays, 'NPT')
  const upa = incidentRows(coverDays, 'UPA')
  const printed = new Date().toLocaleString()
  const reportDate = summary?.as_of ?? latest.entry.cost_date

  const CostTable = ({ title, rows, position }: {
    title: string; rows: typeof budgetLines; position: { planned: number; actual: number }
  }) => <section className="dcr-panel dcr-cost-panel">
    <h2>{title}</h2>
    <table><thead><tr><th>Cost item</th><th>AFE</th><th>Cumulative actual</th><th>Balance</th><th>Used</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.budget_key}><td>{row.item_code ? `${row.item_code} · ` : ''}{row.item_name}</td><td className="num">{dailyMoney(row.planned, currency)}</td><td className="num">{dailyMoney(row.actual_to_date, currency)}</td><td className="num">{dailyMoney(row.balance, currency)}</td><td className="num">{percent(asNumber(row.actual_to_date), asNumber(row.planned))}</td></tr>)}</tbody>
      <tfoot><tr><th>{rows.length ? 'Group total' : 'No cost lines recorded'}</th><th className="num">{dailyMoney(position.planned, currency)}</th><th className="num">{dailyMoney(position.actual, currency)}</th><th className="num">{dailyMoney(position.planned - position.actual, currency)}</th><th className="num">{percent(position.actual, position.planned)}</th></tr></tfoot>
    </table>
  </section>

  const IncidentTable = ({ title, rows, total }: { title: string; rows: CoverIncident[]; total: number }) => <section className="dcr-panel dcr-incident">
    <h2>{title}</h2>
    <table><thead><tr><th>Activity</th><th>Days</th><th>Cost</th><th>Responsible party</th><th>Remarks</th></tr></thead>
      <tbody>{rows.slice(0, 4).map((row, index) => <tr key={`${row.label}-${index}`}><td>{row.label}</td><td className="num">{row.days ? row.days.toFixed(3) : '—'}</td><td className="num">{dailyMoney(row.amount, currency)}</td><td>{row.party}</td><td>{row.remarks}</td></tr>)}
      {!rows.length && <tr><td colSpan={5} className="dcr-none">No {title.split(' ')[0]} cost recorded.</td></tr>}</tbody>
      <tfoot><tr><th>Total</th><th className="num">{rows.reduce((sum, row) => sum + row.days, 0).toFixed(3)}</th><th className="num">{dailyMoney(total, currency)}</th><th colSpan={2}>{rows.length > 4 ? `${rows.length - 4} additional incident(s) continue in the detailed pages.` : ''}</th></tr></tfoot>
    </table>
  </section>

  return <section className="daily-report-cover ps-page">
    <header className="dcr-titlebar">
      <div><div className="dcr-eyebrow">Daily Cost Management · {report.reportKind === 'daily' ? 'Daily cost report' : 'Well cost report'}</div><h1>{report.title}</h1></div>
      <div className="dcr-report-meta"><strong>{latest.entry.well_code} · {latest.entry.well_name}</strong><span>{latest.entry.rig_code} · {latest.entry.rig_name}</span><span>{report.period}</span></div>
    </header>
    <div className="dcr-layout">
      <div className="dcr-main">
        <div className="dcr-topline">
          <section className="dcr-panel dcr-milestone"><h2>Reporting milestone</h2><dl><dt>Spud date &amp; time</dt><dd>{spud ? `${spud.replace('T', ' ').slice(0, 16)} hrs` : 'Not recorded'}</dd><dt>Current report date</dt><dd>{displayDate(reportDate)} · 24:00 hrs</dd></dl></section>
          <section className="dcr-panel dcr-depth"><h2>Section-wise planned depth &amp; current depth</h2><table><thead><tr><th>Section</th><th>Planned depth (m)</th><th>Current depth (m)</th></tr></thead><tbody>{sections.map(section => <tr key={section.hole_section_id}><td>{section.section_code} · {section.section_name}</td><td className="num">{formatDepthMeters(section.to_depth, 'm')}</td><td className="num">{formatDepthMeters(sectionDepths.get(section.hole_section_id), 'm')}</td></tr>)}</tbody></table></section>
          <section className="dcr-panel dcr-time"><h2>Time position</h2><dl><dt>Planned</dt><dd>{plannedDays.toFixed(3)} days</dd><dt>Actual from spud</dt><dd>{actualDays.toFixed(3)} days</dd><dt>Variance</dt><dd>{actualDays || plannedDays ? `${actualDays - plannedDays >= 0 ? '+' : ''}${(actualDays - plannedDays).toFixed(3)} days` : '—'}</dd><dt>Sheets / status</dt><dd>{summary?.totals.sheets ?? detailDays.length} · {summary ? `${summary.totals.draft_sheets} draft` : latest.entry.status}</dd></dl></section>
        </div>
        <CostTable title="Services cost · AFE vs cumulative actual" rows={services} position={servicePosition}/>
        <CostTable title="Consumables cost · AFE vs cumulative actual" rows={consumables} position={consumablePosition}/>
        <section className="dcr-panel dcr-tangibles"><h2>Tangibles cost · AFE vs actual</h2><div><span>AFE <strong>{dailyMoney(tangiblePosition.planned, currency)}</strong></span><span>Actual <strong>{dailyMoney(tangiblePosition.actual, currency)}</strong></span><span>Balance <strong>{dailyMoney(tangiblePosition.planned - tangiblePosition.actual, currency)}</strong></span><span>Used <strong>{percent(tangiblePosition.actual, tangiblePosition.planned)}</strong></span></div></section>
        <div className="dcr-bottomline">
          <section className="dcr-panel dcr-overall"><h2>AFE vs actual summary</h2><table><tbody><tr><th>Services</th><td>{dailyMoney(servicePosition.planned, currency)}</td><td>{dailyMoney(servicePosition.actual, currency)}</td></tr><tr><th>Consumables</th><td>{dailyMoney(consumablePosition.planned, currency)}</td><td>{dailyMoney(consumablePosition.actual, currency)}</td></tr><tr><th>Tangibles</th><td>{dailyMoney(tangiblePosition.planned, currency)}</td><td>{dailyMoney(tangiblePosition.actual, currency)}</td></tr><tr><th>Other expenses</th><td>—</td><td>{dailyMoney(otherExpenses, currency)}</td></tr><tr className="dcr-total"><th>Total</th><td>{dailyMoney(totalPlanned, currency)}</td><td>{dailyMoney(totalActual, currency)}</td></tr></tbody></table><p>Balance {dailyMoney(balance, currency)} · {percent(totalActual, totalPlanned)} used</p></section>
          <section className="dcr-panel dcr-mud-cost"><h2>Mud chemical cost · section-wise</h2><table><thead><tr><th>Section / mud</th><th>Planned</th><th>Actual</th><th>Reconciled</th></tr></thead><tbody>{mudSections.slice(0, 5).map(row => {
            const sectionFactor = summary?.factors.find(item => item.dimension === 'section')?.rows.find(item => item.code === ('section_code' in row ? row.section_code : ''))
            return <tr key={row.section_id}><td>{row.section_label} · {row.mud_type ?? 'Not configured'}</td><td className="num">{dailyMoney(sectionFactor?.planned ?? 0, currency)}</td><td className="num">{dailyMoney(row.actual_cost, currency)}</td><td className="num">{row.reconciled_cost == null ? '—' : dailyMoney(row.reconciled_cost, currency)}</td></tr>
          })}{!mudSections.length && <tr><td colSpan={4} className="dcr-none">No mud reconciliation data.</td></tr>}</tbody></table></section>
          <section className="dcr-panel dcr-loss"><h2>Consumption / losses · cumulative</h2><table><thead><tr><th>Section</th><th>Mud</th><th>Consumption / losses</th><th>Cost / BBL</th></tr></thead><tbody>{mudSections.slice(0, 5).map(row => <tr key={row.section_id}><td>{row.section_label}</td><td>{row.mud_type ?? '—'}</td><td className="num">{asNumber(row.consumption_losses).toLocaleString(undefined, { maximumFractionDigits: 3 })}</td><td className="num">{row.cost_per_bbl == null ? '—' : dailyMoney(row.cost_per_bbl, currency)}</td></tr>)}{!mudSections.length && <tr><td colSpan={4} className="dcr-none">No consumption or loss data.</td></tr>}</tbody></table></section>
        </div>
      </div>
      <aside className="dcr-side">
        <section className="dcr-panel dcr-mud-analysis"><h2>Mud cost analysis · section / mud type</h2><table><thead><tr><th>Section</th><th>Mud</th><th>Receipt</th><th>Additions</th><th>Total mud</th><th>Loss</th><th>Balance</th><th>Cost / BBL</th><th>Reconciled</th></tr></thead><tbody>{mudSections.map(row => {
          const receipt = 'extra_obm_received' in row ? asNumber(String(row.extra_obm_received ?? 0)) : 0
          const additions = 'additions' in row ? asNumber(String(row.additions ?? 0)) : 0
          const totalMud = 'total_mud' in row ? asNumber(String(row.total_mud ?? 0)) : receipt + additions
          const losses = asNumber(row.consumption_losses)
          return <tr key={row.section_id}><td>{row.section_label}</td><td>{row.mud_type ?? '—'}</td><td className="num">{receipt.toLocaleString()}</td><td className="num">{additions.toLocaleString()}</td><td className="num">{totalMud.toLocaleString()}</td><td className="num">{losses.toLocaleString()}</td><td className="num">{(totalMud - losses).toLocaleString()}</td><td className="num">{row.cost_per_bbl == null ? '—' : dailyMoney(row.cost_per_bbl, currency)}</td><td className="num">{row.reconciled_cost == null ? '—' : dailyMoney(row.reconciled_cost, currency)}</td></tr>
        })}{!mudSections.length && <tr><td colSpan={9} className="dcr-none">No mud material-balance data for this reporting period.</td></tr>}</tbody></table></section>
        <IncidentTable title="NPT summary" rows={npt} total={asNumber(summary?.totals.npt ?? latestComparison.npt_to_date)}/>
        <IncidentTable title="UPA summary" rows={upa} total={asNumber(summary?.totals.upa ?? latestComparison.upa_to_date)}/>
      </aside>
    </div>
    <footer className="dcr-footer"><span>Prepared from saved Daily Cost Management records · all figures in {currency}</span><span>Printed {printed} · detailed schedules begin on page 2</span></footer>
  </section>
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

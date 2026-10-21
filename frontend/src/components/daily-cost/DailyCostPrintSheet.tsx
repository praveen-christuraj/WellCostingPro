import { useEffect, useState } from 'react'
import { createPortal, flushSync } from 'react-dom'
import {
  dailyMoney, displayDate, type DailyCostComparisonLine, type DailyCostDay, type DailyCostLineOutput, type DailyCostSectionOption,
  type DailyCostWellSummary,
} from '../../lib/dailyCost'
import type { MudCostMaterialBalance, MudCostReconciliation } from '../../lib/mudCost'
import { depthToMeters } from '../../lib/units'

export type CostPrintReport = {
  title: string
  period: string
  days: DailyCostDay[]
  /** Cumulative saved rows used by the cover and the page-2 cumulative schedules. */
  overviewDays?: DailyCostDay[]
  summary?: DailyCostWellSummary | null
  mudReconciliation?: MudCostReconciliation | null
  mudBalance?: MudCostMaterialBalance | null
  sections?: DailyCostSectionOption[]
  reportKind?: 'daily' | 'well'
  milestoneLabel?: string
}

/** Prints the model-based summary followed by cumulative schedules, never one page per day. */
export function DailyCostPrintSheet({ report }: { report: CostPrintReport | null }) {
  if (!report) return null
  return createPortal(<article className="afe-print-sheet daily-cost-print-sheet" aria-hidden="true">
    <ReportCover report={report}/>
    <CumulativeReportDetails report={report}/>
  </article>, document.body)
}

type CoverIncident = { label: string; days: number; amount: number; party: string; remarks: string }

function asNumber(value: string | number | null | undefined) {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function optionalText(value: object, key: string) {
  const candidate = (value as Record<string, unknown>)[key]
  return typeof candidate === 'string' || typeof candidate === 'number' ? String(candidate) : undefined
}

function decimalText(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed)
    ? parsed.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '—'
}

function depthText(value: string | number | null | undefined, unit: string) {
  const meters = depthToMeters(value, unit)
  return meters === null ? '—' : `${decimalText(meters)} m`
}

/** Labels supplied as "CODE · Name" retain the descriptive name only in print. */
function nameOnly(label: string) {
  const parts = label.split(' · ').map(part => part.trim()).filter(Boolean)
  return parts.length > 1 ? parts.slice(1).join(' · ') : (label || '—')
}

function costName(label: string) {
  return label
    .replace(/\bMud Chemicals\s+allowance\b/gi, 'Mud Chemicals')
    .replace(/\bCement Additives\s+allowance\b/gi, 'Cement Additives')
    .trim()
}

const CONSUMABLE_ORDER = ['Mud Chemicals', 'Cement Additives', 'Fuel', 'Drill Bits'] as const

function reportCostRows(budgetLines: DailyCostComparisonLine[]) {
  const services = [...budgetLines]
    .filter(line => line.cost_group === 'Services')
    .sort((left, right) => left.item_code.localeCompare(right.item_code, undefined, { numeric: true, sensitivity: 'base' }))
  const consumableGroups = new Map<string, DailyCostComparisonLine>()
  for (const line of budgetLines.filter(item => item.cost_group === 'Consumables')) {
    const source = `${line.budget_kind} ${line.budget_key} ${line.item_code} ${line.item_name}`.toLowerCase()
    const category = source.includes('drill_bit') || source.includes('drill bit')
      ? 'Drill Bits'
      : source.includes('mud chemicals')
        ? 'Mud Chemicals'
        : source.includes('cement additives')
          ? 'Cement Additives'
          : source.includes('fuel')
            ? 'Fuel'
            : 'Other Consumables'
    const current = consumableGroups.get(category)
    const planned = asNumber(current?.planned) + asNumber(line.planned)
    const actual = asNumber(current?.actual_to_date) + asNumber(line.actual_to_date)
    consumableGroups.set(category, {
      ...line,
      budget_key: `consumable-summary:${category}`,
      budget_kind: 'consumable_summary',
      item_code: category,
      item_name: category,
      planned: String(planned),
      actual_to_date: String(actual),
      balance: String(planned - actual),
      is_planned: Boolean(current?.is_planned || line.is_planned),
    })
  }
  const example = budgetLines.find(line => line.cost_group === 'Consumables')
  const consumables = CONSUMABLE_ORDER.map(category => consumableGroups.get(category) ?? {
    budget_key: `consumable-summary:${category}`,
    budget_kind: 'consumable_summary',
    item_code: category,
    item_name: category,
    cost_group: 'Consumables' as const,
    planned: '0', actual_to_date: '0', balance: '0', is_planned: Boolean(example?.is_planned),
  })
  const tangibles = [...budgetLines]
    .filter(line => line.cost_group === 'Tangibles')
    .sort((left, right) => left.item_name.localeCompare(right.item_name, undefined, { numeric: true, sensitivity: 'base' }))
  return { services, consumables, tangibles }
}

function percent(actual: number, planned: number) {
  return planned > 0 ? `${decimalText(actual / planned * 100)}%` : '—'
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
        label: line.activity_name,
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
  // Codes define business order but remain hidden; consumables are four category totals.
  const costRows = reportCostRows(budgetLines)
  const services = costRows.services.slice(0, 8)
  const consumables = costRows.consumables
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
  const mudBalances = new Map((report.mudBalance?.rows ?? []).map(row => [row.section_id, row]))
  const npt = incidentRows(coverDays, 'NPT')
  const upa = incidentRows(coverDays, 'UPA')
  const nptDays = npt.reduce((sum, row) => sum + row.days, 0)
  const upaDays = upa.reduce((sum, row) => sum + row.days, 0)
  const plannedActivityDays = Math.max(0, actualDays - nptDays - upaDays)
  const printed = new Date().toLocaleString()
  const reportDate = summary?.as_of ?? latest.entry.cost_date
  type MudSection = typeof mudSections[number]
  const mudMatrixRows: { label: string; value: (row: MudSection) => string }[] = [
    { label: 'Opening Stock', value: row => decimalText(mudBalances.get(row.section_id)?.opening_stock) },
    { label: 'Receipt', value: row => decimalText(mudBalances.get(row.section_id)?.receipt) },
    { label: 'Additions', value: row => decimalText(optionalText(row, 'additions') ?? mudBalances.get(row.section_id)?.additions) },
    { label: 'Total Mud', value: row => decimalText(optionalText(row, 'total_mud') ?? asNumber(mudBalances.get(row.section_id)?.opening_stock) + asNumber(mudBalances.get(row.section_id)?.receipt) + asNumber(mudBalances.get(row.section_id)?.additions)) },
    { label: 'Losses', value: row => decimalText(row.consumption_losses) },
    { label: 'Closing Stock', value: row => decimalText(mudBalances.get(row.section_id)?.closing_stock) },
    { label: 'Meterage (current depth)', value: row => depthText(sectionDepths.get(optionalText(row, 'hole_section_id') ?? row.section_id), 'm') },
    { label: 'Cost / BBL', value: row => row.cost_per_bbl == null ? '—' : dailyMoney(row.cost_per_bbl, currency) },
    { label: 'Reconciled Cost', value: row => row.reconciled_cost == null ? '—' : dailyMoney(row.reconciled_cost, currency) },
  ]

  const CostTable = ({ title, rows, position }: {
    title: string; rows: typeof budgetLines; position: { planned: number; actual: number }
  }) => <section className="dcr-panel dcr-cost-panel">
    <h2>{title}</h2>
    <table><thead><tr><th>Cost item</th><th>AFE</th><th>Cumulative actual</th><th>Balance</th><th>Used</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.budget_key}><td>{costName(row.item_name)}</td><td className="num">{dailyMoney(row.planned, currency)}</td><td className="num">{dailyMoney(row.actual_to_date, currency)}</td><td className="num">{dailyMoney(row.balance, currency)}</td><td className="num">{percent(asNumber(row.actual_to_date), asNumber(row.planned))}</td></tr>)}</tbody>
      <tfoot><tr><th>{rows.length ? 'Group total' : 'No cost lines recorded'}</th><th className="num">{dailyMoney(position.planned, currency)}</th><th className="num">{dailyMoney(position.actual, currency)}</th><th className="num">{dailyMoney(position.planned - position.actual, currency)}</th><th className="num">{percent(position.actual, position.planned)}</th></tr></tfoot>
    </table>
  </section>

  const IncidentTable = ({ title, rows, total }: { title: string; rows: CoverIncident[]; total: number }) => <section className="dcr-panel dcr-incident">
    <h2>{title}</h2>
    <table><thead><tr><th>Activity</th><th>Days</th><th>Cost</th><th>Responsible party</th><th>Remarks</th></tr></thead>
      <tbody>{rows.slice(0, 4).map((row, index) => <tr key={`${row.label}-${index}`}><td>{row.label}</td><td className="num">{row.days ? decimalText(row.days) : '—'}</td><td className="num">{dailyMoney(row.amount, currency)}</td><td>{row.party}</td><td>{row.remarks}</td></tr>)}
      {!rows.length && <tr><td colSpan={5} className="dcr-none">No {title.split(' ')[0]} cost recorded.</td></tr>}</tbody>
      <tfoot><tr><th>Total</th><th className="num">{decimalText(rows.reduce((sum, row) => sum + row.days, 0))}</th><th className="num">{dailyMoney(total, currency)}</th><th colSpan={2}>{rows.length > 4 ? `${rows.length - 4} additional incident(s) are included in this total.` : ''}</th></tr></tfoot>
    </table>
  </section>

  return <section className="daily-report-cover ps-page">
    <header className="dcr-titlebar">
      <div><div className="dcr-eyebrow">Daily Cost Management · {report.reportKind === 'daily' ? 'Daily cost report' : 'Well cost report'}</div><h1>{report.title}</h1></div>
      <div className="dcr-report-meta"><strong>{latest.entry.well_name}</strong><span>{latest.entry.rig_name}</span><span>{report.period}</span></div>
    </header>
    <div className="dcr-layout">
      <div className="dcr-main">
        <div className="dcr-topline">
          <section className="dcr-panel dcr-milestone"><h2>Reporting milestone</h2><dl><dt>{report.milestoneLabel?.trim() || 'Spud date & time'}</dt><dd>{spud ? `${spud.replace('T', ' ').slice(0, 16)} hrs` : 'Not recorded'}</dd><dt>Current report date</dt><dd>{displayDate(reportDate)} · 24:00 hrs</dd></dl></section>
          <section className="dcr-panel dcr-depth"><h2>Section-wise planned depth &amp; current depth</h2><table><thead><tr><th>Section</th><th>Planned depth (m)</th><th>Current depth (m)</th></tr></thead><tbody>{sections.map(section => <tr key={section.hole_section_id}><td>{section.section_name}</td><td className="num">{depthText(section.to_depth, 'm')}</td><td className="num">{depthText(sectionDepths.get(section.hole_section_id), 'm')}</td></tr>)}</tbody></table></section>
          <section className="dcr-panel dcr-time"><h2>Time position</h2><dl><dt>Planned</dt><dd>{decimalText(plannedDays)} days</dd><dt>Actual from spud</dt><dd>{decimalText(actualDays)} days</dd><dt>Actual against planned activities</dt><dd>{decimalText(plannedActivityDays)} days</dd><dt>NPT</dt><dd>{decimalText(nptDays)} days</dd><dt>UPA</dt><dd>{decimalText(upaDays)} days</dd></dl></section>
        </div>
        <CostTable title="Services cost · AFE vs cumulative actual" rows={services} position={servicePosition}/>
        <CostTable title="Consumables cost · AFE vs cumulative actual" rows={consumables} position={consumablePosition}/>
        <section className="dcr-panel dcr-tangibles"><h2>Tangibles cost · AFE vs actual</h2><div><span>AFE <strong>{dailyMoney(tangiblePosition.planned, currency)}</strong></span><span>Actual <strong>{dailyMoney(tangiblePosition.actual, currency)}</strong></span><span>Balance <strong>{dailyMoney(tangiblePosition.planned - tangiblePosition.actual, currency)}</strong></span><span>Used <strong>{percent(tangiblePosition.actual, tangiblePosition.planned)}</strong></span></div></section>
        <div className="dcr-bottomline">
          <section className="dcr-panel dcr-overall"><h2>AFE vs actual summary</h2><table><tbody><tr><th>Services</th><td>{dailyMoney(servicePosition.planned, currency)}</td><td>{dailyMoney(servicePosition.actual, currency)}</td></tr><tr><th>Consumables</th><td>{dailyMoney(consumablePosition.planned, currency)}</td><td>{dailyMoney(consumablePosition.actual, currency)}</td></tr><tr><th>Tangibles</th><td>{dailyMoney(tangiblePosition.planned, currency)}</td><td>{dailyMoney(tangiblePosition.actual, currency)}</td></tr><tr><th>Other expenses</th><td>—</td><td>{dailyMoney(otherExpenses, currency)}</td></tr><tr className="dcr-total"><th>Total</th><td>{dailyMoney(totalPlanned, currency)}</td><td>{dailyMoney(totalActual, currency)}</td></tr></tbody></table><p>Balance {dailyMoney(balance, currency)} · {percent(totalActual, totalPlanned)} used</p></section>
          <section className="dcr-panel dcr-mud-cost"><h2>Mud chemical cost · section-wise</h2><table><thead><tr><th>Section / mud</th><th>Planned</th><th>Actual</th><th>Reconciled</th></tr></thead><tbody>{mudSections.slice(0, 5).map(row => {
            const sectionFactor = summary?.factors.find(item => item.dimension === 'section')?.rows.find(item => item.code === ('section_code' in row ? row.section_code : ''))
            return <tr key={row.section_id}><td>{nameOnly(row.section_label)} · {row.mud_type ?? 'Not configured'}</td><td className="num">{dailyMoney(sectionFactor?.planned ?? 0, currency)}</td><td className="num">{dailyMoney(row.actual_cost, currency)}</td><td className="num">{row.reconciled_cost == null ? '—' : dailyMoney(row.reconciled_cost, currency)}</td></tr>
          })}{!mudSections.length && <tr><td colSpan={4} className="dcr-none">No mud reconciliation data.</td></tr>}</tbody></table></section>
          <section className="dcr-panel dcr-loss"><h2>Consumption / losses · cumulative</h2><table><thead><tr><th>Section</th><th>Mud</th><th>Consumption / losses</th><th>Cost / BBL</th></tr></thead><tbody>{mudSections.slice(0, 5).map(row => <tr key={row.section_id}><td>{nameOnly(row.section_label)}</td><td>{row.mud_type ?? '—'}</td><td className="num">{decimalText(row.consumption_losses)}</td><td className="num">{row.cost_per_bbl == null ? '—' : dailyMoney(row.cost_per_bbl, currency)}</td></tr>)}{!mudSections.length && <tr><td colSpan={4} className="dcr-none">No consumption or loss data.</td></tr>}</tbody></table></section>
        </div>
      </div>
      <aside className="dcr-side">
        <section className="dcr-panel dcr-mud-analysis"><h2>Mud cost analysis · section / mud type</h2><table><thead><tr><th>Measure</th>{mudSections.map(row => <th key={row.section_id}>{nameOnly(row.section_label)}<span>{row.mud_type ?? 'Not configured'}</span></th>)}</tr></thead><tbody>
          {mudMatrixRows.map(metric => <tr key={metric.label}><th>{metric.label}</th>{mudSections.map(row => <td key={row.section_id} className="num">{metric.value(row)}</td>)}</tr>)}
          {!mudSections.length && <tr><td colSpan={2} className="dcr-none">No mud material-balance data for this reporting period.</td></tr>}
        </tbody></table></section>
        <IncidentTable title="NPT summary" rows={npt} total={asNumber(summary?.totals.npt ?? latestComparison.npt_to_date)}/>
        <IncidentTable title="UPA summary" rows={upa} total={asNumber(summary?.totals.upa ?? latestComparison.upa_to_date)}/>
      </aside>
    </div>
    <footer className="dcr-footer"><span>Prepared from saved Daily Cost Management records · all figures in {currency}</span><span>Printed {printed} · cumulative schedules begin on page 2</span></footer>
  </section>
}

function CumulativeSchedule({ title, rows, currency }: { title: string; rows: DailyCostComparisonLine[]; currency: string }) {
  return <section className="dcr-cumulative-section">
    <h2>{title}</h2>
    <table><thead><tr><th>Cost item</th><th>AFE</th><th>Cumulative actual</th><th>Balance</th><th>Used</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.budget_key}><td>{costName(row.item_name)}</td><td className="num">{dailyMoney(row.planned, currency)}</td><td className="num">{dailyMoney(row.actual_to_date, currency)}</td><td className="num">{dailyMoney(row.balance, currency)}</td><td className="num">{percent(asNumber(row.actual_to_date), asNumber(row.planned))}</td></tr>)}
      {!rows.length && <tr><td colSpan={5} className="dcr-none">No cumulative cost recorded.</td></tr>}</tbody>
    </table>
  </section>
}

function CumulativeReportDetails({ report }: { report: CostPrintReport }) {
  const groups = new Map<string, DailyCostDay[]>()
  for (const day of report.overviewDays?.length ? report.overviewDays : report.days) {
    const key = `${day.entry.afe_id}:${day.entry.standard_currency}`
    groups.set(key, [...(groups.get(key) ?? []), day])
  }
  const scopes = report.summary
    ? [{ key: 'well', label: `${report.summary.well.well_name} · all compatible AFEs`, currency: report.summary.totals.currency, rows: report.summary.budget_lines }]
    : [...groups.entries()].map(([key, days]) => {
      const latest = [...days].sort((left, right) => left.entry.cost_date.localeCompare(right.entry.cost_date)).at(-1)!
      return { key, label: `${latest.entry.well_name} · ${latest.entry.afe_name}`, currency: latest.entry.standard_currency, rows: latest.comparison.budget_lines }
    })
  return <div className="daily-report-details">
    <header>
      <div className="ps-eyebrow">WellCosting Pro · cumulative saved costs</div>
      <h1>{report.title}</h1>
      <p>{report.period} · Printed {new Date().toLocaleString()}</p>
      <p>These schedules consolidate saved daily sheets. Daily line-by-line breakdowns are intentionally omitted; currencies and incompatible AFEs remain separate.</p>
    </header>
    {scopes.map(scope => {
      const rows = reportCostRows(scope.rows)
      return <section className="dcr-cumulative-scope" key={scope.key}>
        <h1>{scope.label} ({scope.currency})</h1>
        <CumulativeSchedule title="Service-wise cumulative cost" rows={rows.services.filter(row => asNumber(row.actual_to_date) !== 0)} currency={scope.currency}/>
        <CumulativeSchedule title="Consumables cumulative cost · four categories" rows={rows.consumables} currency={scope.currency}/>
        <CumulativeSchedule title="Tangibles cumulative cost · item-wise" rows={rows.tangibles.filter(row => asNumber(row.actual_to_date) !== 0)} currency={scope.currency}/>
      </section>
    })}
  </div>
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

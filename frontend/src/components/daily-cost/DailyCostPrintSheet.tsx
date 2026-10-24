import { useEffect, useState } from 'react'
import { createPortal, flushSync } from 'react-dom'
import {
  displayDate, leadLagText, validLeadLagDays as isValidLeadLagDays,
  type DailyCostComparisonLine, type DailyCostDay, type DailyCostLineOutput, type DailyCostSectionOption,
  type DailyCostWellSummary, type DailyLeadLagKind,
} from '../../lib/dailyCost'
import { MUD_COST_LOSS_METRICS, type MudCostMaterialBalance, type MudCostReconciliation } from '../../lib/mudCost'
import { lihMeasure, type LihCostReport } from '../../lib/lihCost'
import type { NdtEntry } from '../../lib/ndtInspection'
import { compareServiceCodes, compareServiceGroups, serviceGroupLabel } from '../../lib/serviceGroups'
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
  /** Manual LIH Cost Register for the printed well/period. */
  lihReport?: LihCostReport | null
  /** Active manual NDT inspection lines for the printed well/scope. */
  ndtInspections?: NdtEntry[]
  sections?: DailyCostSectionOption[]
  reportKind?: 'daily' | 'well'
  /**
   * Report wording overrides. Nothing is typed at print time any more: the
   * milestone label lives on the well's progress record and the lead / lag is
   * saved with the daily sheet, so both are derived from the saved days.
   */
  milestoneLabel?: string
  leadLagKind?: DailyLeadLagKind
  leadLagDays?: string
}

export type LeadLagKind = DailyLeadLagKind

export { isValidLeadLagDays as validLeadLagDays }

export type CostPrintReports = {
  reports?: CostPrintReport[]
  /** Single-report form kept for callers that print one saved report. */
  report?: CostPrintReport | null
  /**
   * Bulk mode prints only page one (the operational summary) of every report
   * and omits the cumulative schedules that follow it.
   */
  coversOnly?: boolean
}

/**
 * The report day the cover describes: the latest sheet actually printed. The
 * cumulative history is only a fallback, because it may carry another AFE of
 * the same well on the same date.
 */
function latestDay(report: CostPrintReport): DailyCostDay | undefined {
  const days = report.days.length ? report.days : report.overviewDays ?? []
  return [...days].sort((left, right) => left.entry.cost_date.localeCompare(right.entry.cost_date)).at(-1)
}

/** Lead / lag saved with the report day, or an explicit override. */
function reportLeadLag(report: CostPrintReport): { kind: DailyLeadLagKind; days: string } {
  const entry = latestDay(report)?.entry
  return {
    kind: report.leadLagKind ?? entry?.lead_lag_kind ?? '',
    days: String(report.leadLagDays ?? entry?.lead_lag_days ?? ''),
  }
}

/** Wording saved with the well scope's progress record, else the default. */
function reportMilestoneLabel(report: CostPrintReport): string {
  if (report.milestoneLabel?.trim()) return report.milestoneLabel.trim()
  const progressRows = report.summary?.progress ?? []
  const scope = latestDay(report)?.progress?.scope
  const saved = (scope ? progressRows.find(row => row.scope === scope)?.milestone_label : undefined)
    ?? latestDay(report)?.progress?.milestone_label
    ?? progressRows.find(row => row.milestone_label)?.milestone_label
  return saved?.trim() || 'Spud date & time'
}

function reportTitle(report: CostPrintReport) {
  const { kind, days } = reportLeadLag(report)
  return `${report.title} (${leadLagText(kind, days)})`
}

/**
 * Prints the model-based summary followed by cumulative schedules, never one
 * page per day. In bulk mode every selected report contributes its first page
 * only, so the operator can print or save one combined PDF.
 */
export function DailyCostPrintSheet({ report, reports, coversOnly = false }: CostPrintReports) {
  const queue = reports?.length ? reports : report ? [report] : []
  if (!queue.length) return null
  const bulk = coversOnly || queue.length > 1
  return createPortal(<article
    className={`afe-print-sheet daily-cost-print-sheet${bulk ? ' daily-cost-print-sheet--bulk' : ''}`}
    aria-hidden="true"
  >
    {queue.map((item, index) => <div className="dcr-report-unit" key={`${item.title}-${item.period}-${index}`}>
      <ReportCover report={item}/>
      {!coversOnly && <CumulativeReportDetails report={item}/>}
    </div>)}
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

/**
 * Report currency: "USD" prints as the "$" symbol. Currencies without a known
 * symbol keep their ISO code so a printed total is never ambiguous.
 */
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$', US$: '$', EUR: '€', GBP: '£', NGN: '₦', CAD: 'C$', AUD: 'A$', ZAR: 'R', INR: '₹', AED: 'AED ',
}

export function printMoney(value: string | number | null | undefined, currency = '') {
  const amount = Number(value ?? 0)
  if (!Number.isFinite(amount)) return '—'
  const code = currency.trim().toUpperCase()
  const symbol = CURRENCY_SYMBOLS[code]
  const formatted = Math.abs(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const sign = amount < 0 ? '-' : ''
  return symbol ? `${sign}${symbol}${formatted}` : `${sign}${code ? `${code} ` : ''}${formatted}`
}

function currencyLabel(currency: string) {
  const code = currency.trim().toUpperCase()
  const symbol = CURRENCY_SYMBOLS[code]
  return symbol ? `${symbol} (${code})` : code || 'amount'
}

/** Cumulative up to the previous day, the report day's cost and the total. */
function daySplit(line: { actual_to_date: string; actual_prior?: string; actual_today?: string }) {
  const total = asNumber(line.actual_to_date)
  const today = line.actual_today === undefined ? 0 : asNumber(line.actual_today)
  const prior = line.actual_prior === undefined ? total - today : asNumber(line.actual_prior)
  return { prior, today, total }
}

function previousDate(value: string) {
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return value
  parsed.setUTCDate(parsed.getUTCDate() - 1)
  return parsed.toISOString().slice(0, 10)
}

function depthText(value: string | number | null | undefined, unit: string) {
  const meters = depthToMeters(value, unit)
  return meters === null ? '—' : `${decimalText(meters)} m`
}

/** Mud APIs append scope and depth to CODE · Name; report headers need the section name only. */
function sectionNameOnly(label: string) {
  const parts = label.split(' · ').map(part => part.trim()).filter(Boolean)
  return parts.length > 1 ? parts[1] : (label || '—')
}

/** The server may use Miscellaneous Services as a fallback; do not print that caption. */
function printedServiceGroup(group: string | null | undefined) {
  const label = serviceGroupLabel(group)
  return /\bmiscellaneous\b/i.test(label) ? '' : label
}

function costName(label: string) {
  return label
    .replace(/\bMud Chemicals\s+allowance\b/gi, 'Mud Chemicals')
    .replace(/\bCement Additives\s+allowance\b/gi, 'Cement Additives')
    .trim()
}

const CONSUMABLE_ORDER = ['Mud Chemicals', 'Cement Additives', 'Fuel', 'Drill Bits'] as const

function reportCostRows(budgetLines: DailyCostComparisonLine[]) {
  // Services print in the fixed reporting-group sequence, then by item code.
  const services = [...budgetLines]
    .filter(line => line.cost_group === 'Services')
    // The AFE estimate's reporting groups and line sequence define the print
    // order; the item code is only the tie-break.
    .sort((left, right) => compareServiceGroups(left.service_group, right.service_group)
      || (left.sort_order ?? 0) - (right.sort_order ?? 0)
      || compareServiceCodes(left.item_code, right.item_code))
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
    const currentSplit = current ? classificationSplit(current) : { planned: '0', upa: '0', npt: '0' }
    const lineSplit = classificationSplit(line)
    consumableGroups.set(category, {
      ...line,
      budget_key: `consumable-summary:${category}`,
      budget_kind: 'consumable_summary',
      item_code: category,
      item_name: category,
      planned: String(planned),
      actual_to_date: String(actual),
      actual_planned: String(asNumber(currentSplit.planned) + asNumber(lineSplit.planned)),
      actual_upa: String(asNumber(currentSplit.upa) + asNumber(lineSplit.upa)),
      actual_npt: String(asNumber(currentSplit.npt) + asNumber(lineSplit.npt)),
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
    actual_planned: '0', actual_upa: '0', actual_npt: '0',
  })
  const tangibles = [...budgetLines]
    .filter(line => line.cost_group === 'Tangibles')
    .sort((left, right) => left.item_name.localeCompare(right.item_name, undefined, { numeric: true, sensitivity: 'base' }))
  return { services, consumables, tangibles }
}

function percent(actual: number, planned: number) {
  return planned > 0 ? `${decimalText(actual / planned * 100)}%` : '—'
}

/**
 * Cumulative actual split by the activity classification it was recorded under.
 * Older payloads without the split are read as wholly planned, so a report never
 * shows a total that its three columns cannot explain.
 */
function classificationSplit(line: {
  actual_to_date: string; actual_planned?: string; actual_upa?: string; actual_npt?: string
}) {
  if (line.actual_planned === undefined && line.actual_upa === undefined && line.actual_npt === undefined) {
    return { planned: line.actual_to_date, upa: '0', npt: '0' }
  }
  return { planned: line.actual_planned ?? '0', upa: line.actual_upa ?? '0', npt: line.actual_npt ?? '0' }
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
  // Every AFE allowance prints, in its reporting group, including lines with no
  // cost yet (they show 0). The density step keeps a long schedule on page one.
  const services = costRows.services
  const consumables = costRows.consumables
  const densityStep = services.length > 26 ? 4 : services.length > 18 ? 3 : services.length > 12 ? 2 : 1
  const groupPosition = (group: 'Services' | 'Consumables' | 'Tangibles') => {
    // Planned values come from the locked AFE budget schedule. Summary factor
    // rows are driven by recorded actuals and can omit a planned-only group
    // (most visibly Tangibles), which previously made its printed AFE value 0.
    const planned = budgetLines
      .filter(line => line.cost_group === group)
      .reduce((total, line) => total + asNumber(line.planned), 0)
    if (summary) {
      const actual = group === 'Services' ? summary.totals.services : group === 'Consumables' ? summary.totals.consumables : summary.totals.tangibles
      return { planned, actual: asNumber(actual) }
    }
    const groupRow = latestComparison.groups?.find(item => item.cost_group === group)
    return { planned, actual: asNumber(groupRow?.actual_to_date) }
  }
  /** Day split for a cost group, taken from the report day's own comparison. */
  const groupSplit = (group: 'Services' | 'Consumables' | 'Tangibles') => {
    const row = latestComparison.groups?.find(item => item.cost_group === group)
    const actual = groupPosition(group).actual
    const today = row?.actual_today === undefined ? 0 : asNumber(row.actual_today)
    const prior = row?.actual_prior === undefined ? actual - today : asNumber(row.actual_prior)
    return { prior, today }
  }
  const servicePosition = groupPosition('Services')
  const serviceDay = groupSplit('Services')
  const consumablePosition = groupPosition('Consumables')
  const consumableDay = groupSplit('Consumables')
  const tangiblePosition = groupPosition('Tangibles')
  const tangibleDay = groupSplit('Tangibles')
  const totalPlanned = asNumber(summary?.totals.planned ?? latestComparison.planned_total)
  const totalActual = asNumber(summary?.totals.comparison_actual ?? latestComparison.actual_to_date)
  const otherExpenses = asNumber(summary?.totals.other_expenses ?? latestComparison.other_expenses_to_date)
  // LIH Cost Register: separate from every budgeted group, added to the actual
  // cost and deducted explicitly from the AFE amount.
  const lihBucket = (report.lihReport?.totals ?? []).find(row => row.currency === currency)
  const lihTotal = asNumber(summary?.totals.lih_cost ?? lihBucket?.total ?? 0)
  const lihLineCount = summary?.totals.lih_line_count ?? lihBucket?.line_count ?? 0
  const lihEntryCount = summary?.totals.lih_entries ?? lihBucket?.entry_count ?? 0
  const ndtInspections = report.ndtInspections ?? []
  const actualIncludingLih = totalActual + lihTotal
  const afeAvailable = totalPlanned - lihTotal
  const balance = asNumber(
    summary?.totals.comparison_balance_including_lih
      ?? (summary ? totalPlanned - lihTotal - totalActual : latestComparison.balance),
  )
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
    { label: 'Cost / BBL', value: row => row.cost_per_bbl == null ? '—' : printMoney(row.cost_per_bbl, currency) },
    { label: 'Reconciled Cost', value: row => row.reconciled_cost == null ? '—' : printMoney(row.reconciled_cost, currency) },
  ]
  const lossMetricRows = MUD_COST_LOSS_METRICS.map(metric => ({
    ...metric,
    value: (row: MudSection) => decimalText(optionalText(row, metric.key)),
  }))
  const surfaceLossPerMeter = (row: MudSection) => {
    const depth = asNumber(sectionDepths.get(optionalText(row, 'hole_section_id') ?? row.section_id))
    if (depth <= 0) return '—'
    return decimalText(asNumber(optionalText(row, 'surface_loss_total')) / depth)
  }

  /**
   * Cost vs AFE by item. The report day is split out of the cumulative cost:
   * AFE allowance, everything up to the previous day, the cost recorded on the
   * report date itself, and the cumulative total. Every AFE allowance prints in
   * its reporting group, including lines with no cost (0), so the schedule
   * always reconciles to the AFE.
   */
  const priorDate = previousDate(String(reportDate))
  const CostTable = ({ title, rows, position, day, grouped = false }: {
    title: string
    rows: typeof budgetLines
    position: { planned: number; actual: number }
    day: { prior: number; today: number }
    grouped?: boolean
  }) => {
    const cumulative = rows.reduce((totals, row) => {
      const split = classificationSplit(row)
      totals.planned += asNumber(split.planned)
      totals.npt += asNumber(split.npt)
      totals.upa += asNumber(split.upa)
      return totals
    }, { planned: 0, npt: 0, upa: 0 })
    return <section className="dcr-panel dcr-cost-panel">
      <h2>{title}</h2>
      <table>
        <colgroup>{Array.from({ length: 10 }, (_, index) => <col key={index}/>)}</colgroup>
        <thead>
          <tr>
            <th rowSpan={2}>Cost item</th>
            <th rowSpan={2}>AFE</th>
            <th rowSpan={2}>Up to<br/>{displayDate(priorDate)}</th>
            <th rowSpan={2}>Cost on<br/>{displayDate(String(reportDate))}</th>
            <th colSpan={4}>Cumulative</th>
            <th rowSpan={2}>Balance</th>
            <th rowSpan={2}>Used</th>
          </tr>
          <tr><th>Planned</th><th>NPT</th><th>UPA</th><th>Total</th></tr>
        </thead>
      <tbody>{rows.map((row, index) => {
        const dayCost = daySplit(row)
        const activityCost = classificationSplit(row)
        const groupLabel = printedServiceGroup(row.service_group)
        return <tr key={row.budget_key}>
          <td>
            {grouped && groupLabel && row.service_group !== rows[index - 1]?.service_group
              && <span className="dcr-group">{groupLabel} · </span>}
            {costName(row.item_name)}
          </td>
          <td className="num">{printMoney(row.planned, currency)}</td>
          <td className="num">{printMoney(dayCost.prior, currency)}</td>
          <td className="num">{printMoney(dayCost.today, currency)}</td>
          <td className="num">{printMoney(activityCost.planned, currency)}</td>
          <td className="num">{printMoney(activityCost.npt, currency)}</td>
          <td className="num">{printMoney(activityCost.upa, currency)}</td>
          <td className="num">{printMoney(dayCost.total, currency)}</td>
          <td className="num">{printMoney(asNumber(row.planned) - dayCost.total, currency)}</td>
          <td className="num">{percent(dayCost.total, asNumber(row.planned))}</td>
        </tr>
      })}
      {!rows.length && <tr><td colSpan={10} className="dcr-none">No AFE allowance recorded.</td></tr>}
      </tbody>
      <tfoot><tr>
        <th>{rows.length ? 'Group total' : 'No cost lines recorded'}</th>
        <th className="num">{printMoney(position.planned, currency)}</th>
        <th className="num">{printMoney(day.prior, currency)}</th>
        <th className="num">{printMoney(day.today, currency)}</th>
        <th className="num">{printMoney(cumulative.planned, currency)}</th>
        <th className="num">{printMoney(cumulative.npt, currency)}</th>
        <th className="num">{printMoney(cumulative.upa, currency)}</th>
        <th className="num">{printMoney(position.actual, currency)}</th>
        <th className="num">{printMoney(position.planned - position.actual, currency)}</th>
        <th className="num">{percent(position.actual, position.planned)}</th>
      </tr></tfoot>
      </table>
    </section>
  }

  const IncidentTable = ({ title, rows, total }: { title: string; rows: CoverIncident[]; total: number }) => <section className="dcr-panel dcr-incident">
    <h2>{title}</h2>
    <table><thead><tr><th>Activity</th><th>Days</th><th>Cost</th><th>Responsible party</th><th>Remarks</th></tr></thead>
      <tbody>{rows.slice(0, 4).map((row, index) => <tr key={`${row.label}-${index}`}><td>{row.label}</td><td className="num">{row.days ? decimalText(row.days) : '—'}</td><td className="num">{printMoney(row.amount, currency)}</td><td>{row.party}</td><td>{row.remarks}</td></tr>)}
      {!rows.length && <tr><td colSpan={5} className="dcr-none">No {title.split(' ')[0]} cost recorded.</td></tr>}</tbody>
      <tfoot><tr><th>Total</th><th className="num">{decimalText(rows.reduce((sum, row) => sum + row.days, 0))}</th><th className="num">{printMoney(total, currency)}</th><th colSpan={2}>{rows.length > 4 ? `${rows.length - 4} additional incident(s) are included in this total.` : ''}</th></tr></tfoot>
    </table>
  </section>

  return <section className={`daily-report-cover ps-page dcr-density-${densityStep}${ndtInspections.length ? ' dcr-has-ndt' : ''}`}>
    <header className="dcr-titlebar">
      <div><div className="dcr-eyebrow">Daily Cost Management · {report.reportKind === 'daily' ? 'Daily cost report' : 'Well cost report'}</div><h1>{reportTitle(report)}</h1></div>
      <div className="dcr-report-meta"><strong>{latest.entry.well_name}</strong><span>{latest.entry.rig_name}</span><span>{report.period}</span></div>
    </header>
    <div className="dcr-layout">
      <div className="dcr-main">
        <div className="dcr-topline">
          <section className="dcr-panel dcr-milestone"><h2>Reporting milestone</h2><dl><dt>{reportMilestoneLabel(report)}</dt><dd>{spud ? `${spud.replace('T', ' ').slice(0, 16)} hrs` : 'Not recorded'}</dd><dt>Current report date</dt><dd>{displayDate(reportDate)} · 24:00 hrs</dd></dl></section>
          <section className="dcr-panel dcr-depth"><h2>Section-wise planned depth &amp; current depth</h2><table><thead><tr><th>Section</th><th>Planned depth (m)</th><th>Current depth (m)</th></tr></thead><tbody>{sections.map(section => <tr key={section.hole_section_id}><td>{section.section_name}</td><td className="num">{depthText(section.to_depth, 'm')}</td><td className="num">{depthText(sectionDepths.get(section.hole_section_id), 'm')}</td></tr>)}</tbody></table></section>
          <section className="dcr-panel dcr-time"><h2>Time position</h2><dl><dt>Planned</dt><dd>{decimalText(plannedDays)} days</dd><dt>Actual</dt><dd>{decimalText(actualDays)} days</dd><dt>Actual against planned activities</dt><dd>{decimalText(plannedActivityDays)} days</dd><dt>NPT</dt><dd>{decimalText(nptDays)} days</dd><dt>UPA</dt><dd>{decimalText(upaDays)} days</dd></dl></section>
        </div>
        <CostTable title="Services cost · AFE vs last day, this day and cumulative" rows={services} position={servicePosition}
          day={serviceDay} grouped/>
        <CostTable title="Consumables cost · AFE vs last day, this day and cumulative" rows={consumables} position={consumablePosition}
          day={consumableDay}/>
        <section className="dcr-panel dcr-tangibles"><h2>Tangibles cost · AFE vs actual</h2><div>
          <span>AFE <strong>{printMoney(tangiblePosition.planned, currency)}</strong></span>
          <span>Up to {displayDate(priorDate)} <strong>{printMoney(tangibleDay.prior, currency)}</strong></span>
          <span>Cost on {displayDate(String(reportDate))} <strong>{printMoney(tangibleDay.today, currency)}</strong></span>
          <span>Actual <strong>{printMoney(tangiblePosition.actual, currency)}</strong></span>
          <span>Balance <strong>{printMoney(tangiblePosition.planned - tangiblePosition.actual, currency)}</strong></span>
          <span>Used <strong>{percent(tangiblePosition.actual, tangiblePosition.planned)}</strong></span>
        </div></section>
        <div className="dcr-bottomline">
          {/* The LIH register panel owns the bottom-left slot directly under
              Tangibles; the AFE vs actual summary follows it downward. */}
          <div className={`dcr-stack${ndtInspections.length ? ' dcr-stack--ndt' : ''}`}>
            <section className="dcr-panel dcr-lih"><h2>LIH cost · manual register deduction from the AFE</h2><div><span>LIH cost <strong>{printMoney(lihTotal, currency)}</strong></span><span className="dcr-lih-deduct">Deducted from AFE <strong>{printMoney(lihTotal, currency)}</strong></span><span>Actual incl. LIH <strong>{printMoney(actualIncludingLih, currency)}</strong></span><span>AFE available after LIH <strong>{printMoney(afeAvailable, currency)}</strong></span></div><p className="dcr-lih-note">{lihEntryCount ? `${lihLineCount} item${lihLineCount === 1 ? '' : 's'} across ${lihEntryCount} LIH register day${lihEntryCount === 1 ? '' : 's'} · item detail prints on the cumulative pages.` : 'No LIH cost recorded for this report.'}</p></section>
            <section className="dcr-panel dcr-overall"><h2>AFE vs actual summary</h2><table><tbody><tr><th>Services</th><td>{printMoney(servicePosition.planned, currency)}</td><td>{printMoney(servicePosition.actual, currency)}</td></tr><tr><th>Consumables</th><td>{printMoney(consumablePosition.planned, currency)}</td><td>{printMoney(consumablePosition.actual, currency)}</td></tr><tr><th>Tangibles</th><td>{printMoney(tangiblePosition.planned, currency)}</td><td>{printMoney(tangiblePosition.actual, currency)}</td></tr><tr><th>Other expenses</th><td>—</td><td>{printMoney(otherExpenses, currency)}</td></tr><tr><th>LIH cost · register</th><td>—</td><td>{printMoney(lihTotal, currency)}</td></tr><tr className="dcr-total"><th>Total</th><td>{printMoney(totalPlanned, currency)}</td><td>{printMoney(actualIncludingLih, currency)}</td></tr></tbody></table><p>AFE available = {printMoney(balance, currency)} · {percent(actualIncludingLih, totalPlanned)} used</p></section>
            {ndtInspections.length > 0 && <section className="dcr-panel dcr-ndt"><h2>NDT Inspection Details</h2><table><colgroup><col/><col/><col/><col/><col/></colgroup><thead><tr><th rowSpan={2}>Description</th><th rowSpan={2}>Received</th><th rowSpan={2}>Consumed</th><th colSpan={2}>Backloads</th></tr><tr><th>Good</th><th>Bad</th></tr></thead><tbody>{ndtInspections.map(row => <tr key={row.id}><td>{row.description}</td><td className="num">{decimalText(row.quantity_received)}</td><td className="num">{decimalText(row.quantity_consumed)}</td><td className="num">{decimalText(row.quantity_backloaded_good)}</td><td className="num">{decimalText(row.quantity_backloaded_bad)}</td></tr>)}</tbody></table></section>}
          </div>
          <section className="dcr-panel dcr-mud-cost"><h2>Mud chemical cost · section-wise</h2><table><thead><tr><th>Section / mud</th><th>Planned</th><th>Actual</th><th>Reconciled</th></tr></thead><tbody>{mudSections.slice(0, 5).map(row => {
            const sectionFactor = summary?.factors.find(item => item.dimension === 'section')?.rows.find(item => item.code === ('section_code' in row ? row.section_code : ''))
            return <tr key={row.section_id}><td>{sectionNameOnly(row.section_label)} · {row.mud_type ?? 'Not configured'}</td><td className="num">{printMoney(sectionFactor?.planned ?? 0, currency)}</td><td className="num">{printMoney(row.actual_cost, currency)}</td><td className="num">{row.reconciled_cost == null ? '—' : printMoney(row.reconciled_cost, currency)}</td></tr>
          })}{!mudSections.length && <tr><td colSpan={4} className="dcr-none">No mud reconciliation data.</td></tr>}</tbody></table></section>
          <section className="dcr-panel dcr-loss dcr-loss-matrix"><h2>Consumption / losses · cumulative matrix</h2><table><thead><tr><th>Loss measure</th>{mudSections.map(row => <th key={row.section_id}>{sectionNameOnly(row.section_label)}<span>{row.mud_type ?? 'Not configured'}</span></th>)}</tr></thead><tbody>
            <tr className="dcr-matrix-group"><th colSpan={Math.max(2, mudSections.length + 1)}>Surface losses</th></tr>
            {lossMetricRows.filter(metric => metric.group === 'surface' || metric.group === 'surface-total').map(metric => <tr className={metric.group === 'surface-total' ? 'dcr-matrix-total' : ''} key={metric.key}><th>{metric.label}</th>{mudSections.map(row => <td key={row.section_id} className="num">{metric.value(row)}</td>)}</tr>)}
            <tr className="dcr-matrix-total"><th>Loss (bbl/m)</th>{mudSections.map(row => <td key={row.section_id} className="num">{surfaceLossPerMeter(row)}</td>)}</tr>
            <tr className="dcr-matrix-group"><th colSpan={Math.max(2, mudSections.length + 1)}>Other losses</th></tr>
            {lossMetricRows.filter(metric => metric.group === 'other' || metric.group === 'other-total').map(metric => <tr className={metric.group === 'other-total' ? 'dcr-matrix-total' : ''} key={metric.key}><th>{metric.label}</th>{mudSections.map(row => <td key={row.section_id} className="num">{metric.value(row)}</td>)}</tr>)}
            {lossMetricRows.filter(metric => metric.group === 'grand-total').map(metric => <tr className="dcr-matrix-grand" key={metric.key}><th>{metric.label}</th>{mudSections.map(row => <td key={row.section_id} className="num">{metric.value(row)}</td>)}</tr>)}
            {!mudSections.length && <tr><td colSpan={2} className="dcr-none">No consumption or loss data.</td></tr>}
          </tbody></table></section>
        </div>
      </div>
      <aside className="dcr-side">
        <section className="dcr-panel dcr-mud-analysis"><h2>Mud cost analysis · section / mud type</h2><table><thead><tr><th>Measure</th>{mudSections.map(row => <th key={row.section_id}>{sectionNameOnly(row.section_label)}<span>{row.mud_type ?? 'Not configured'}</span></th>)}</tr></thead><tbody>
          {mudMatrixRows.map(metric => <tr key={metric.label}><th>{metric.label}</th>{mudSections.map(row => <td key={row.section_id} className="num">{metric.value(row)}</td>)}</tr>)}
          {!mudSections.length && <tr><td colSpan={2} className="dcr-none">No mud material-balance data for this reporting period.</td></tr>}
        </tbody></table></section>
        <IncidentTable title="NPT summary" rows={npt} total={asNumber(summary?.totals.npt ?? latestComparison.npt_to_date)}/>
        <IncidentTable title="UPA summary" rows={upa} total={asNumber(summary?.totals.upa ?? latestComparison.upa_to_date)}/>
      </aside>
    </div>
    <footer className="dcr-footer"><span>Prepared from saved Daily Cost Management records · all figures in {currencyLabel(currency)}</span><span>Printed {printed}{report.reportKind === 'daily' ? '' : ' · cumulative schedules begin on page 2'}</span></footer>
  </section>
}

function CumulativeSchedule({ title, rows, currency }: { title: string; rows: DailyCostComparisonLine[]; currency: string }) {
  return <section className="dcr-cumulative-section">
    <h2>{title}</h2>
    <table><thead><tr><th>Cost item</th><th>AFE</th><th>Cumulative actual</th><th>Balance</th><th>Used</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.budget_key}><td>{costName(row.item_name)}</td><td className="num">{printMoney(row.planned, currency)}</td><td className="num">{printMoney(row.actual_to_date, currency)}</td><td className="num">{printMoney(row.balance, currency)}</td><td className="num">{percent(asNumber(row.actual_to_date), asNumber(row.planned))}</td></tr>)}
      {!rows.length && <tr><td colSpan={5} className="dcr-none">No cumulative cost recorded.</td></tr>}</tbody>
    </table>
  </section>
}

/**
 * Item-level LIH Cost Register schedule. The cover panel shows the day totals in
 * the bottom-left slot; this page carries every recorded item so the printed
 * report can be audited line by line.
 */
function LihSchedule({ report }: { report: CostPrintReport }) {
  const days = report.lihReport?.days ?? []
  if (!days.length) return null
  const currencies = [...new Set(days.map(day => day.entry.currency))].sort()
  return <>
    {currencies.map(currency => {
      const rows = days.filter(day => day.entry.currency === currency)
      const total = rows.reduce((sum, day) => sum + asNumber(day.entry.total_cost), 0)
      return <section className="dcr-cumulative-scope" key={`lih-${currency}`}>
        <h1>LIH Cost Register · {currency}</h1>
        <section className="dcr-cumulative-section">
          <h2>Lost In Hole items · deduct from the AFE, add to actual</h2>
          <table>
            <thead><tr><th>Date</th><th>AFE</th><th>Item description</th><th>OD / ID</th><th>Fish neck</th><th>Serial number</th><th>Connection</th><th>Units</th><th>Unit cost</th><th>Total cost</th><th>Remarks</th></tr></thead>
            <tbody>
              {rows.flatMap(day => day.lines.map(line => <tr key={line.id}>
                <td>{displayDate(day.entry.cost_date)}</td>
                <td>{day.entry.afe_code || '—'}</td>
                <td>{line.item_description}</td>
                <td>{lihMeasure(line.od_size)} / {lihMeasure(line.id_size)}</td>
                <td>{lihMeasure(line.fish_neck_od)} × {lihMeasure(line.fish_neck_length)}</td>
                <td>{line.serial_number || '—'}</td>
                <td>{line.connection || '—'}</td>
                <td className="num">{lihMeasure(line.no_of_units)} {line.unit}</td>
                <td className="num">{printMoney(line.unit_cost, currency)}</td>
                <td className="num">{printMoney(line.total_cost, currency)}</td>
                <td>{line.remarks || '—'}</td>
              </tr>))}
              {!rows.some(day => day.lines.length) && <tr><td colSpan={11} className="dcr-none">No LIH items recorded in this period.</td></tr>}
            </tbody>
            <tfoot><tr><th colSpan={9}>Total LIH cost · deducted from the AFE</th><td className="num">{printMoney(total, currency)}</td><td/></tr></tfoot>
          </table>
        </section>
      </section>
    })}
  </>
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
      <h1>{reportTitle(report)}</h1>
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
    <LihSchedule report={report}/>
  </div>
}

type PrintQueue = { reports: CostPrintReport[]; coversOnly: boolean }

/** Mount the print-only portal synchronously before opening the browser dialog. */
export function useCostPrint() {
  const [queue, setQueue] = useState<PrintQueue>({ reports: [], coversOnly: false })
  useEffect(() => {
    const clear = () => setQueue({ reports: [], coversOnly: false })
    window.addEventListener('afterprint', clear)
    return () => window.removeEventListener('afterprint', clear)
  }, [])
  const print = (next: CostPrintReport) => {
    flushSync(() => setQueue({ reports: [next], coversOnly: false }))
    window.print()
    // afterprint clears the portal, including in browsers with an asynchronous dialog.
  }
  /**
   * Bulk print: every report contributes its first page only, so the selected
   * daily cost reports form one printable file (print or save as PDF).
   */
  const printMany = (next: CostPrintReport[]) => {
    flushSync(() => setQueue({ reports: next, coversOnly: true }))
    window.print()
  }
  return { print, printMany, printSheet: <DailyCostPrintSheet reports={queue.reports} coversOnly={queue.coversOnly}/> }
}

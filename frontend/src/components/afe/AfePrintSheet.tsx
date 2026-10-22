import { createPortal } from 'react-dom'
import { depthToMeters } from '../../lib/units'
import { amountText, type AfeEstimate, type AfeStatusEvent, type CurrencySetup, type ServiceLineOut } from '../../lib/afe'
import { groupServiceOptions, sortServicesByGroup } from '../../lib/serviceGroups'

// Print layout for a saved AFE, in the fixed two-page AFE format:
//   page 1 - title, compact well / AFE metadata, one categorized cost table,
//            the total AFE amount, and the section / depth plan;
//   page 2 - detailed consumable and tangible line lists, warnings and sign-off.
// Plain HTML tables (not the grid), so every line prints. Hidden on screen, shown only by the
// @media print rules in styles.css, which Daily Cost printing reuses through .ps-* classes.

const quantityText = (value: string): string =>
  Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const daysText = (value: string | number | null | undefined): string => {
  const parsed = Number(value)
  return value === null || value === undefined || value === '' || !Number.isFinite(parsed)
    ? '—'
    : `${parsed.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} d`
}

const depthText = (value: string | number | null | undefined, unit: string): string => {
  const meters = depthToMeters(value, unit)
  return meters === null
    ? '—'
    : `${meters.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} m`
}

/** Labels arrive as "CODE · Name"; printed reports intentionally keep only the name. */
const nameOnly = (label: string): string => {
  const parts = label.split(' · ').map(part => part.trim()).filter(Boolean)
  return parts.length > 1 ? parts.slice(1).join(' · ') : (label || '—')
}

/** Keep the entered rates (and their currency) beside the charging basis on page one. */
function basisDetail(line: ServiceLineOut) {
  if (line.charging_basis === 'Per Section Rate') {
    return line.section_rates.length
      ? line.section_rates.map((rate, index) => (
          <div className="ps-sub" key={`${rate.hole_section_id}-${rate.phase_id ?? ''}-${index}`}>
            {rate.section_label ? nameOnly(rate.section_label) : 'Section'}{rate.phase_label ? ` · ${nameOnly(rate.phase_label)}` : ''}: {amountText(rate.amount, line.currency)}
          </div>
        ))
      : <div className="ps-sub">No section rates</div>
  }

  const scope = [line.section_label ? nameOnly(line.section_label) : '', line.phase_label ? nameOnly(line.phase_label) : ''].filter(Boolean).join(' · ')
  return <>
    {line.charging_basis === 'Day Rate'
      ? (line.rates.length ? line.rates.map(rate => {
          const charge = line.charges.find(item => item.category === rate.category)
          const quantity = charge ? ` × ${quantityText(charge.quantity)} ${charge.quantity_unit}` : ''
          return <div className="ps-sub" key={rate.category}>{rate.category} {amountText(rate.unit_rate, line.currency)}{quantity}</div>
        }) : <div className="ps-sub">—</div>)
      : <div className="ps-sub">Fixed {amountText(line.service_amount, line.currency)}</div>}
    {scope && <div className="ps-sub">{scope}</div>}
  </>
}

// Report-only subtotals use the saved, non-negative ten-place amounts and FX rates.
// Convert each priced component and round half-up, just like the existing AFE summary;
// adding native-currency line amounts together would give incorrect mixed-currency totals.
const AMOUNT_SCALE = 10_000_000_000n
const amountUnits = (value: string): bigint => {
  const [whole, fraction = ''] = value.split('.')
  return BigInt(whole || '0') * AMOUNT_SCALE + BigInt(fraction.padEnd(10, '0'))
}

function costGroupTotal(lines: { amount: string; currency: string; components: { amount: string }[] }[], currency: CurrencySetup): string | null {
  if (!currency.converted) return null
  const rates = new Map(currency.exchange_rates.map(rate => [rate.currency_code, amountUnits(rate.rate)]))
  let total = 0n
  for (const line of lines) {
    const factor = line.currency === currency.standard_currency ? AMOUNT_SCALE : rates.get(line.currency)
    if (factor === undefined) return null
    // Older payloads may have only the already-priced line amount.
    for (const component of line.components.length ? line.components : [line]) {
      total += (amountUnits(component.amount) * factor + AMOUNT_SCALE / 2n) / AMOUNT_SCALE
    }
  }
  return `${total / AMOUNT_SCALE}.${String(total % AMOUNT_SCALE).padStart(10, '0')}`
}

export function AfePrintSheet({ estimate }: { estimate: AfeEstimate }) {
  const { afe, well, services, consumables, tangibles, summary } = estimate
  // Keep the existing group order and natural service-code order within each block.
  const printServices = sortServicesByGroup(services)
  const printGroups = groupServiceOptions(printServices)
  const consumableCategories = ['Mud Chemicals', 'Cement Additives', 'Fuel', 'Drill Bits'] as const
  const standard = summary.currency.standard_currency
  const multiCurrency = summary.currency.multi_currency
  const pending = 'Pending conversion'

  // Latest recorded move per workflow action. A reopen cancels the stages before it, so a
  // reopened AFE never prints a stale review or approval.
  const history = estimate.status_history ?? []
  const latest = new Map<string, AfeStatusEvent>()
  for (const event of [...history].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))) {
    if (!latest.has(event.action)) latest.set(event.action, event)
  }
  const reopened = latest.get('reopen')
  const reopenedAt = reopened ? Date.parse(reopened.created_at) : Number.NEGATIVE_INFINITY
  const stageEvent = (action: AfeStatusEvent['action']): AfeStatusEvent | null => {
    const event = latest.get(action)
    return event && Date.parse(event.created_at) > reopenedAt ? event : null
  }
  const stages: { action: AfeStatusEvent['action']; label: string }[] = [
    { action: 'submit', label: 'Submitted by' },
    { action: 'review', label: 'Reviewed by' },
    { action: 'approve', label: 'Approved by' },
  ]

  const lineCount = (count: number): string => (count ? `${count} line(s)` : 'no lines')
  // Count entered-rate detail plus each group's heading and total for print compaction.
  const pageOneDetailRows = printServices.reduce((count, line) => count + Math.max(1,
    line.charging_basis === 'Per Section Rate' ? line.section_rates.length
      : line.charging_basis === 'Day Rate' ? line.rates.length : 1), 0)
    + printGroups.length * 2 + consumableCategories.length + well.sections.length + 8

  return createPortal(<div className="afe-print-sheet afe-cost-print-sheet" aria-hidden="true">
    {/* Page 1 - compact summary: metadata, one categorized cost table, total and well plan. */}
    <div className={`ps-page ps-afe-summary${pageOneDetailRows > 20 ? ' ps-afe-dense' : ''}`}>
      <header className="ps-titlebar">
        <div className="ps-title">
          <h1>AFE Cost Estimate</h1>
        </div>
        <div className="ps-titlemeta">
          <span className="ps-titlecode">{afe.afe_name}</span>
        </div>
      </header>

      <table className="ps-meta">
        <tbody>
          <tr>
            <th>Rig</th><td>{afe.rig_name}</td>
            <th>Well</th><td>{afe.well_name}</td>
          </tr>
          <tr>
            <th>AFE</th><td>{afe.afe_name}</td>
            <th>AFE type</th><td>{afe.afe_type}</td>
          </tr>
          <tr>
            <th>Objective of the well</th><td colSpan={3} className="ps-notes">{well.objective || '—'}</td>
          </tr>
          <tr>
            <th>Location / block</th><td>{[well.well_location, well.block].filter(Boolean).join(' / ') || '—'}</td>
            <th>Total depth (m)</th><td>{depthText(well.total_depth, well.depth_unit)}</td>
          </tr>
          <tr>
            <th>Planned days</th><td colSpan={3}>{daysText(well.total_days)}</td>
          </tr>
        </tbody>
      </table>

      <h2>Services, consumables and tangibles</h2>
      <table className="ps-table ps-afe-cost-table">
          <colgroup>
            <col style={{ width: '4%' }}/><col style={{ width: '26%' }}/><col style={{ width: '34%' }}/><col style={{ width: '17%' }}/><col style={{ width: '19%' }}/>
          </colgroup>
          <thead>
            <tr>
              <th>#</th><th>Service</th><th>Basis / entered rates</th><th className="num">Amount</th><th>Remarks</th>
            </tr>
          </thead>
          {printGroups.map(({ group, options: lines }, groupIndex) => {
            const label = group || 'Unclassified services'
            const total = costGroupTotal(lines, summary.currency)
            return <tbody className="ps-service-group-block" key={group}>
              <tr className="ps-service-group-heading">
                <td>{groupIndex + 1}.0</td>
                <th colSpan={4} scope="rowgroup">{label}</th>
              </tr>
              {lines.map((line, index) => (
                <tr className="ps-line" key={line.client_key ?? line.id ?? line.service_id}>
                  <td>{groupIndex + 1}.{index + 1}</td>
                  <td>
                    <strong>{line.service_name}</strong><div className="ps-sub">{[line.provider_type, line.vendor_name || 'No vendor'].join(' · ')}</div>
                  </td>
                  <td>{line.charging_basis}{basisDetail(line)}</td>
                  <td className="num">{amountText(line.amount, line.currency)}</td>
                  <td className="ps-notes">{line.remarks || '—'}</td>
                </tr>
              ))}
              <tr className="ps-subtotal ps-total ps-service-group-total">
                <td/>
                <th colSpan={2} scope="row">Total {label}{standard ? ` (${standard})` : ''}</th>
                <td className="num">{total === null ? pending : amountText(total, standard)}</td>
                <td/>
              </tr>
            </tbody>
          })}
          <tbody>
            {services.length === 0 && <tr className="ps-line ps-services-empty"><td/><td colSpan={4} className="ps-empty">No service lines.</td></tr>}
            <tr className="ps-subtotal ps-services-total">
              <td colSpan={3}>Services total{standard ? ` (${standard})` : ''}</td>
              <td className="num">{summary.services_total === null ? pending : amountText(summary.services_total, standard)}</td>
              <td>{multiCurrency ? 'converted at saved rates' : ''}</td>
            </tr>
          </tbody>
          <tbody className="ps-cost-group-block ps-consumable-group-block">
            <tr className="ps-service-group-heading ps-cost-group-heading">
              <td>{printGroups.length + 1}.0</td>
              <th colSpan={4} scope="rowgroup">Consumables</th>
            </tr>
            {consumableCategories.map((category, index) => {
              const lines = consumables.filter(line => line.category === category)
              const total = costGroupTotal(lines, summary.currency)
              return <tr className="ps-line ps-consumable-summary" key={category}>
                <td>{printGroups.length + 1}.{index + 1}</td>
                <td><strong>{category}</strong></td>
                <td>{lineCount(lines.length)} · lump sum</td>
                <td className="num">{total === null ? pending : amountText(total, standard)}</td>
                <td/>
              </tr>
            })}
            <tr className="ps-subtotal ps-total ps-service-group-total ps-cost-group-total">
              <td/>
              <th colSpan={2} scope="row">Total Consumables{standard ? ` (${standard})` : ''}</th>
              <td className="num">{summary.consumables_total === null ? pending : amountText(summary.consumables_total, standard)}</td>
              <td>{multiCurrency ? 'converted at saved rates' : ''}</td>
            </tr>
          </tbody>
          <tbody className="ps-cost-group-block ps-tangible-group-block">
            <tr className="ps-service-group-heading ps-cost-group-heading">
              <td>{printGroups.length + 2}.0</td>
              <th colSpan={4} scope="rowgroup">Tangibles</th>
            </tr>
            <tr className="ps-line ps-tangible-summary">
              <td>{printGroups.length + 2}.1</td>
              <td><strong>Tangibles lump sum</strong></td>
              <td>{lineCount(tangibles.length)} · lump sum</td>
              <td className="num">{summary.tangibles_total === null ? pending : amountText(summary.tangibles_total, standard)}</td>
              <td/>
            </tr>
            <tr className="ps-subtotal ps-total ps-service-group-total ps-cost-group-total">
              <td/>
              <th colSpan={2} scope="row">Total Tangibles{standard ? ` (${standard})` : ''}</th>
              <td className="num">{summary.tangibles_total === null ? pending : amountText(summary.tangibles_total, standard)}</td>
              <td>{multiCurrency ? 'converted at saved rates' : ''}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr className="ps-total ps-grand">
              <th colSpan={3}>Total AFE amount{standard ? ` (${standard})` : ''}</th>
              <td className="num">{summary.total === null ? pending : amountText(summary.total, standard)}</td>
              <td/>
            </tr>
          </tfoot>
        </table>
      {multiCurrency && <p className="ps-note">Line amounts stay in each line's currency. Every subtotal and total above is converted to {standard} at the rates saved with this estimate.</p>}

      <div className="ps-keep ps-section-plan">
        <h2>Sections and depths</h2>
        {well.sections.length === 0 ? <p className="ps-empty">The well has no configured sections.</p> : (
          <table className="ps-table">
            <colgroup><col style={{ width: '34%' }}/><col style={{ width: '10%' }}/><col style={{ width: '10%' }}/><col style={{ width: '9%' }}/><col style={{ width: '37%' }}/></colgroup>
            <thead><tr><th>Section</th><th className="num">From (m)</th><th className="num">To (m)</th><th className="num">Days</th><th>Phases</th></tr></thead>
            <tbody>{well.sections.map(section => <tr key={section.hole_section_id}>
              <td>{section.section_name}</td><td className="num">{depthText(section.from_depth, well.depth_unit)}</td>
              <td className="num">{depthText(section.to_depth, well.depth_unit)}</td><td className="num">{daysText(section.total_days)}</td>
              <td>{section.phases.length ? section.phases.map(phase => `${phase.phase_name} (${daysText(phase.days)})`).join(', ') : 'No phases'}</td>
            </tr>)}</tbody>
            <tfoot><tr className="ps-subtotal"><td>Well plan · {well.sections.length} section(s)</td>
              <td className="num" colSpan={2}>{depthText(well.total_depth, well.depth_unit)}</td><td className="num">{daysText(well.total_days)}</td>
              <td>{well.sections.reduce((total, section) => total + section.phases.length, 0)} phase(s)</td></tr></tfoot>
          </table>
        )}
      </div>

      <footer className="ps-pagefoot">
        <span>WellCosting Pro · AFE cost estimate · {afe.afe_name}</span>
      </footer>
    </div>

    {/* Page 2 - line detail behind page 1's categorized totals, warnings and sign-off. */}
    <div className="ps-page">
      <header className="ps-titlebar">
        <div className="ps-title">
          <h1>AFE Cost Estimate</h1>
        </div>
        <div className="ps-titlemeta">
          <span className="ps-titlecode">{afe.afe_name}</span>
        </div>
      </header>

      <h2>Consumables ({lineCount(consumables.length)})</h2>
      {consumables.length === 0 ? <p className="ps-empty">No consumable lines.</p> : (
        <table className="ps-table">
          <colgroup>
            <col style={{ width: '23%' }}/><col style={{ width: '12%' }}/><col style={{ width: '12%' }}/><col style={{ width: '8%' }}/><col style={{ width: '9%' }}/><col style={{ width: '6%' }}/><col style={{ width: '16%' }}/><col style={{ width: '14%' }}/>
          </colgroup>
          <thead>
            <tr>
              <th>Category / item</th><th>Section</th><th>Phase</th><th className="num">Quantity</th><th className="num">Rate</th><th>Ccy</th><th className="num">Amount</th><th>Remarks</th>
            </tr>
          </thead>
          <tbody>
            {consumables.map(line => (
              <tr className="ps-line" key={line.client_key ?? line.id ?? `${line.category}-${line.hole_section_id}-${line.phase_id ?? ''}`}>
                <td>
                  <strong>{line.category}</strong>
                  {line.category === 'Drill Bits'
                    ? <div className="ps-sub">{[line.bit_name, line.manufacturer || 'No make', line.bit_type, line.size].filter(Boolean).join(' · ')}{line.bit_description ? ` · ${line.bit_description}` : ''}</div>
                    : <div className="ps-sub">Lump sum estimate</div>}
                </td>
                <td>{nameOnly(line.section_label)}</td>
                <td>{line.phase_label ? nameOnly(line.phase_label) : '—'}</td>
                <td className="num">{line.category === 'Drill Bits' ? quantityText(line.quantity) : '—'}</td>
                <td className="num">{line.effective_rate ? amountText(line.effective_rate) : '—'}</td>
                <td>{line.currency}</td>
                <td className="num">{amountText(line.amount, line.currency)}</td>
                <td className="ps-notes">{line.remarks || '—'}</td>
              </tr>
            ))}
            <tr className="ps-subtotal">
              <td colSpan={6}>Consumables total{standard ? ` (${standard})` : ''}</td>
              <td className="num">{summary.consumables_total === null ? pending : amountText(summary.consumables_total, standard)}</td>
              <td>{multiCurrency ? 'converted at saved rates' : ''}</td>
            </tr>
          </tbody>
        </table>
      )}

      <h2>Tangibles ({lineCount(tangibles.length)})</h2>
      {tangibles.length === 0 ? <p className="ps-empty">No tangible lines.</p> : (
        <table className="ps-table">
          <colgroup>
            <col style={{ width: '23%' }}/><col style={{ width: '12%' }}/><col style={{ width: '8%' }}/><col style={{ width: '8%' }}/><col style={{ width: '9%' }}/><col style={{ width: '6%' }}/><col style={{ width: '16%' }}/><col style={{ width: '18%' }}/>
          </colgroup>
          <thead>
            <tr>
              <th>Tangible</th><th>Manufacturer</th><th>UOM</th><th className="num">Quantity</th><th className="num">Rate</th><th>Ccy</th><th className="num">Amount</th><th>Remarks</th>
            </tr>
          </thead>
          <tbody>
            {tangibles.map(line => (
              <tr className="ps-line" key={line.client_key ?? line.id ?? line.tangible_id}>
                <td>
                  <strong>{line.tangible_name}</strong>
                  {line.tangible_description ? <div className="ps-sub">{line.tangible_description}</div> : null}
                </td>
                <td>{line.manufacturer_name || '—'}</td>
                <td>{line.uom || '—'}</td>
                <td className="num">{quantityText(line.quantity)}</td>
                <td className="num">{amountText(line.effective_rate)}{line.override_rate ? ' (override)' : ''}</td>
                <td>{line.currency}</td>
                <td className="num">{amountText(line.amount, line.currency)}</td>
                <td className="ps-notes">{line.remarks || '—'}</td>
              </tr>
            ))}
            <tr className="ps-subtotal">
              <td colSpan={6}>Tangibles total{standard ? ` (${standard})` : ''}</td>
              <td className="num">{summary.tangibles_total === null ? pending : amountText(summary.tangibles_total, standard)}</td>
              <td>{multiCurrency ? 'converted at saved rates' : ''}</td>
            </tr>
          </tbody>
        </table>
      )}

      <div className="ps-notes">
        {afe.remarks && <p><strong>AFE remarks:</strong> {afe.remarks}</p>}
        <p>Prepared from the saved cost estimate. Page 1 shows categorized cost totals and the well plan; this page lists every consumable and tangible line behind them, in each line's currency.</p>
      </div>

      {summary.warnings.length > 0 && <div className="ps-warnings">
        <strong>Estimate warnings</strong>
        <ul>{summary.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
      </div>}

      <div className="ps-keep">
        <h2>Authorisation</h2>
        <table className="ps-table ps-signoff">
          <colgroup><col style={{ width: '13%' }}/><col/><col/><col/></colgroup>
          <thead>
            <tr><th>Stage</th>{stages.map(stage => <th key={stage.action}>{stage.label}</th>)}</tr>
          </thead>
          <tbody>
            <tr>
              <th>Name</th>
              {stages.map(stage => <td key={stage.action}>{stageEvent(stage.action)?.actor_name || '—'}</td>)}
            </tr>
            <tr>
              <th>Email</th>
              {stages.map(stage => <td key={stage.action}>{stageEvent(stage.action)?.actor_email || '—'}</td>)}
            </tr>
            <tr>
              <th>Date</th>
              {stages.map(stage => {
                const event = stageEvent(stage.action)
                return <td key={stage.action}>{event ? new Date(event.created_at).toLocaleString() : '—'}</td>
              })}
            </tr>
            <tr className="ps-sign">
              <th>Signature</th>
              {stages.map(stage => <td key={stage.action}>&nbsp;</td>)}
            </tr>
          </tbody>
        </table>
        {afe.status_remarks && <p className="ps-note"><strong>Status remarks:</strong> {afe.status_remarks}</p>}
      </div>

      <footer className="ps-pagefoot">
        <span>WellCosting Pro · AFE cost estimate · {afe.afe_name}</span>
      </footer>
    </div>
  </div>, document.body)
}

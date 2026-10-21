import { createPortal } from 'react-dom'
import { depthToMeters } from '../../lib/units'
import { amountText, STATUS_LABEL, type AfeEstimate, type AfeStatusEvent, type ServiceLineOut } from '../../lib/afe'
import { compareServiceCodes, compareServiceGroups, serviceGroupLabel } from '../../lib/serviceGroups'

// Print layout for a saved AFE, in the fixed two-page AFE format:
//   page 1 - title, well and AFE metadata, the service schedule with remarks,
//            consumable and tangible lump sums, and the total AFE amount;
//   page 2 - sections, detailed consumable and tangible line lists, and sign-off.
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

export function AfePrintSheet({ estimate }: { estimate: AfeEstimate }) {
  const { afe, well, services, consumables, tangibles, summary } = estimate
  // Report order is the fixed service-group sequence, then natural service code.
  const printServices = [...services].sort((left, right) =>
    compareServiceGroups(left.service_group, right.service_group)
    || compareServiceCodes(left.service_code, right.service_code))
  const standard = summary.currency.standard_currency
  const printedAt = new Date().toLocaleString()
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
  // Multiple entered rates occupy multiple lines within Basis, even for one service.
  const serviceDetailRows = printServices.reduce((count, line) => count + Math.max(1,
    line.charging_basis === 'Per Section Rate' ? line.section_rates.length
      : line.charging_basis === 'Day Rate' ? line.rates.length : 1), 0)

  return createPortal(<div className="afe-print-sheet afe-cost-print-sheet" aria-hidden="true">
    {/* Page 1 - compact summary: metadata, services, group lump sums and total. */}
    <div className={`ps-page ps-afe-summary${serviceDetailRows > 14 ? ' ps-afe-dense' : ''}`}>
      <header className="ps-titlebar">
        <div className="ps-title">
          <div className="ps-eyebrow">Authorization for expenditure · cost estimate</div>
          <h1>AFE Cost Estimate</h1>
        </div>
        <div className="ps-titlemeta">
          <span className="ps-titlecode">{afe.afe_name}</span>
          <span className="ps-printed">Printed {printedAt}</span>
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
            <th>Configuration</th><td>{afe.configuration_scope === 'completion' ? 'Completion plan' : 'Drilling plan'}</td>
          </tr>
          <tr>
            <th>Objective of the well</th><td colSpan={3} className="ps-notes">{well.objective || '—'}</td>
          </tr>
          <tr>
            <th>Location / block</th><td>{[well.well_location, well.block].filter(Boolean).join(' / ') || '—'}</td>
            <th>Well plan</th><td>{[well.config_status, well.status].filter(Boolean).join(' · ') || '—'}</td>
          </tr>
          <tr>
            <th>Total depth (m)</th><td>{depthText(well.total_depth, well.depth_unit)}</td>
            <th>Planned days</th><td>{daysText(well.total_days)}</td>
          </tr>
          <tr>
            <th>AFE type</th><td>{afe.afe_type} · {afe.configuration_scope === 'completion' ? 'Completion plan' : 'Drilling plan'}</td>
            <th>Status</th><td>{STATUS_LABEL[afe.status]}</td>
          </tr>
          <tr>
            <th>Estimate saved</th>
            <td colSpan={3}>{afe.estimate_saved_at ? `${new Date(afe.estimate_saved_at).toLocaleString()} by ${afe.estimate_saved_by || '—'}` : 'Not saved'}</td>
          </tr>
        </tbody>
      </table>

      <h2>Services and cost</h2>
      {services.length === 0 ? <p className="ps-empty">No service lines.</p> : (
        <table className="ps-table">
          <colgroup>
            <col style={{ width: '4%' }}/><col style={{ width: '26%' }}/><col style={{ width: '34%' }}/><col style={{ width: '17%' }}/><col style={{ width: '19%' }}/>
          </colgroup>
          <thead>
            <tr>
              <th>#</th><th>Service</th><th>Basis / entered rates</th><th className="num">Amount</th><th>Remarks</th>
            </tr>
          </thead>
          <tbody>
            {printServices.map((line, index) => (
              <tr className="ps-line" key={line.client_key ?? line.id ?? line.service_id}>
                <td>{index + 1}</td>
                <td>
                  {serviceGroupLabel(line.service_group) && line.service_group !== printServices[index - 1]?.service_group
                    && <span className="ps-group">{line.service_group} · </span>}
                  <strong>{line.service_name}</strong><div className="ps-sub">{[line.provider_type, line.vendor_name || 'No vendor'].join(' · ')}</div>
                </td>
                <td>{line.charging_basis}{basisDetail(line)}</td>
                <td className="num">{amountText(line.amount, line.currency)}</td>
                <td className="ps-notes">{line.remarks || '—'}</td>
              </tr>
            ))}
            <tr className="ps-subtotal">
              <td colSpan={3}>Services total{standard ? ` (${standard})` : ''}</td>
              <td className="num">{summary.services_total === null ? pending : amountText(summary.services_total, standard)}</td>
              <td>{multiCurrency ? 'converted at saved rates' : ''}</td>
            </tr>
          </tbody>
        </table>
      )}

      <div className="ps-keep">
        <h2>Consumables and tangibles</h2>
        <table className="ps-table">
          <colgroup><col style={{ width: '55%' }}/><col style={{ width: '29%' }}/><col style={{ width: '16%' }}/></colgroup>
          <thead>
            <tr><th>Cost group</th><th>Basis</th><th className="num">Amount{standard ? ` (${standard})` : ''}</th></tr>
          </thead>
          <tbody>
            <tr className="ps-subtotal">
              <td>Consumables lump sum</td>
              <td>{lineCount(consumables.length)}</td>
              <td className="num">{summary.consumables_total === null ? pending : amountText(summary.consumables_total, standard)}</td>
            </tr>
            <tr className="ps-subtotal">
              <td>Tangibles lump sum</td>
              <td>{lineCount(tangibles.length)}</td>
              <td className="num">{summary.tangibles_total === null ? pending : amountText(summary.tangibles_total, standard)}</td>
            </tr>
            <tr className="ps-total ps-grand">
              <td colSpan={2}>Total AFE amount</td>
              <td className="num">{summary.total === null ? pending : amountText(summary.total, standard)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {multiCurrency && <p className="ps-note">Line amounts stay in each line's currency. Every subtotal and total above is converted to {standard} at the rates saved with this estimate.</p>}

      <footer className="ps-pagefoot">
        <span>WellCosting Pro · AFE cost estimate · {afe.afe_name}</span>
      </footer>
    </div>

    {/* Page 2 - well plan, line detail behind page 1's lump sums, warnings and sign-off. */}
    <div className="ps-page">
      <header className="ps-titlebar">
        <div className="ps-title">
          <div className="ps-eyebrow">Authorization for expenditure · cost estimate</div>
          <h1>AFE supporting detail</h1>
        </div>
        <div className="ps-titlemeta">
          <span className="ps-titlecode">{afe.afe_name}</span>
          <span>{afe.well_name}</span>
          <span className="ps-printed">{afe.afe_type} AFE · {STATUS_LABEL[afe.status]}</span>
        </div>
      </header>

      <div className="ps-keep">
        <h2>Sections and depths</h2>
        {well.sections.length === 0 ? <p className="ps-empty">The well has no configured sections.</p> : (
          <table className="ps-table">
            <colgroup><col style={{ width: '34%' }}/><col style={{ width: '10%' }}/><col style={{ width: '10%' }}/><col style={{ width: '9%' }}/><col style={{ width: '37%' }}/></colgroup>
            <thead>
              <tr>
                <th>Section</th>
                <th className="num">From (m)</th>
                <th className="num">To (m)</th>
                <th className="num">Days</th>
                <th>Phases</th>
              </tr>
            </thead>
            <tbody>
              {well.sections.map(section => (
                <tr key={section.hole_section_id}>
                  <td>{section.section_name}</td>
                  <td className="num">{depthText(section.from_depth, well.depth_unit)}</td>
                  <td className="num">{depthText(section.to_depth, well.depth_unit)}</td>
                  <td className="num">{daysText(section.total_days)}</td>
                  <td>{section.phases.length
                    ? section.phases.map(phase => `${phase.phase_name} (${daysText(phase.days)})`).join(', ')
                    : 'No phases'}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="ps-subtotal">
                <td>Well plan · {well.sections.length} section(s)</td>
                <td className="num" colSpan={2}>{depthText(well.total_depth, well.depth_unit)}</td>
                <td className="num">{daysText(well.total_days)}</td>
                <td>{well.sections.reduce((total, section) => total + section.phases.length, 0)} phase(s)</td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>

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
            <tr className="ps-total ps-grand">
              <td colSpan={6}>Total AFE amount</td>
              <td className="num">{summary.total === null ? pending : amountText(summary.total, standard)}</td>
              <td/>
            </tr>
          </tbody>
        </table>
      )}

      <div className="ps-notes">
        {afe.remarks && <p><strong>AFE remarks:</strong> {afe.remarks}</p>}
        <p>Prepared from the saved cost estimate. Page 1 shows the lump sums; this page lists every consumable and tangible line behind them, in each line's currency.</p>
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

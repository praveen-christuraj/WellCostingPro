import { Fragment } from 'react'
import { createPortal } from 'react-dom'
import { amountText, daysText, STATUS_LABEL, totalsText, type AfeComponent, type AfeEstimate } from '../../lib/afe'

// Print layout for a saved AFE. Plain HTML tables (not the grid), so every line and every
// section prints, in this order: well configuration, cost summary, services, consumables, tangibles.
// It is hidden on screen and shown only by the @media print rules in styles.css.
export function AfePrintSheet({ estimate }: { estimate: AfeEstimate }) {
  const { afe, well, services, consumables, tangibles, summary } = estimate
  const printedAt = new Date().toLocaleString()

  const componentRows = (components: AfeComponent[], currency: string) => components.map((component, index) => (
    <tr key={`${component.category}-${index}`} className="ps-component">
      <td colSpan={2}>{component.category} · {component.description}</td>
      <td>{component.section_label || '—'}</td>
      <td>{component.phase_label || '—'}</td>
      <td className="num">{component.quantity ? `${Number(component.quantity).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${component.unit}` : component.unit}</td>
      <td className="num">{component.rate ? amountText(component.rate) : '—'}</td>
      <td className="num">{amountText(component.amount, currency)}</td>
    </tr>
  ))

  return createPortal(<div className="afe-print-sheet" aria-hidden="true">
    <header className="ps-header">
      <div className="ps-eyebrow">Authority for expenditure · cost estimate</div>
      <h1>{afe.afe_code} · {afe.afe_name}</h1>
      <table className="ps-meta">
        <tbody>
          <tr><th>Rig</th><td>{afe.rig_code} · {afe.rig_name}</td><th>Well</th><td>{afe.well_code} · {afe.well_name}</td></tr>
          <tr><th>AFE type</th><td>{afe.afe_type}</td><th>Status</th><td>{STATUS_LABEL[afe.status]}</td></tr>
          <tr><th>Estimate saved</th><td>{afe.estimate_saved_at ? `${new Date(afe.estimate_saved_at).toLocaleString()} by ${afe.estimate_saved_by || '—'}` : 'Not saved'}</td><th>Printed</th><td>{printedAt}</td></tr>
        </tbody>
      </table>
    </header>

    <section>
      <h2>1. Well configuration</h2>
      <table className="ps-table">
        <tbody>
          <tr><th>Well code</th><td>{well.well_code}</td><th>Well name</th><td>{well.well_name}</td><th>Location / block</th><td>{well.well_location} / {well.block}</td></tr>
          <tr><th>Objective</th><td>{well.objective || '—'}</td><th>Plan status</th><td>{well.config_status}</td><th>Well status</th><td>{well.status}</td></tr>
          <tr><th>Total depth</th><td>{well.total_depth ? `${Number(well.total_depth).toLocaleString()} ${well.depth_unit}` : '—'}</td><th>Planned days</th><td>{daysText(well.total_days)}</td><th>Sections</th><td>{well.sections.length}</td></tr>
        </tbody>
      </table>
      {well.sections.length === 0 ? <p className="ps-empty">The well has no configured sections.</p> : <table className="ps-table ps-grid">
        <thead>
          <tr><th>Section</th><th>From depth</th><th>To depth</th><th>Planned days</th><th>Phase</th><th className="num">Phase days</th></tr>
        </thead>
        <tbody>
          {well.sections.flatMap(section => section.phases.length
            ? section.phases.map((phase, index) => <tr key={`${section.hole_section_id}-${phase.phase_id}`}>
              {index === 0 && <>
                <td rowSpan={section.phases.length}>{section.section_code} · {section.section_name}</td>
                <td rowSpan={section.phases.length} className="num">{section.from_depth}</td>
                <td rowSpan={section.phases.length} className="num">{section.to_depth}</td>
                <td rowSpan={section.phases.length} className="num">{daysText(section.total_days)}</td>
              </>}
              <td>{phase.phase_code} · {phase.phase_name}</td>
              <td className="num">{daysText(phase.days)}</td>
            </tr>)
            : [<tr key={section.hole_section_id}>
              <td>{section.section_code} · {section.section_name}</td>
              <td className="num">{section.from_depth}</td>
              <td className="num">{section.to_depth}</td>
              <td className="num">{daysText(section.total_days)}</td>
              <td>No phases</td>
              <td className="num">—</td>
            </tr>])}
        </tbody>
      </table>}
    </section>

    <section>
      <h2>2. AFE cost estimate summary</h2>
      <table className="ps-table">
        <tbody>
          <tr><th>Services</th><td className="num">{amountText(summary.services_total)}</td></tr>
          <tr><th>Consumables</th><td className="num">{amountText(summary.consumables_total)}</td></tr>
          <tr><th>Tangibles</th><td className="num">{amountText(summary.tangibles_total)}</td></tr>
          <tr className="ps-total"><th>Total estimate</th><td className="num">{totalsText(summary.totals_by_currency)}</td></tr>
        </tbody>
      </table>
      <h3>By hole section and phase</h3>
      {summary.by_section.length === 0 ? <p className="ps-empty">No section totals.</p> : <table className="ps-table ps-grid">
        <thead>
          <tr><th>Section / phase</th><th className="num">Planned days</th><th className="num">Services</th><th className="num">Consumables</th><th className="num">Tangibles</th><th className="num">Total</th></tr>
        </thead>
        <tbody>
          {summary.by_section.map(row => <tr key={`${row.hole_section_id ?? 'well'}-${row.label}`}>
            <td>{row.label}</td>
            <td className="num">{daysText(row.planned_days)}</td>
            <td className="num">{amountText(row.services)}</td>
            <td className="num">{amountText(row.consumables)}</td>
            <td className="num">{amountText(row.tangibles)}</td>
            <td className="num">{amountText(row.total)}</td>
          </tr>)}
        </tbody>
      </table>}
      {summary.warnings.length > 0 && <div className="ps-warnings">
        <strong>Warnings</strong>
        <ul>{summary.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
      </div>}
    </section>

    <section>
      <h2>3. Services ({services.length})</h2>
      {services.length === 0 ? <p className="ps-empty">No service lines.</p> : <table className="ps-table ps-grid">
        <thead>
          <tr><th>Service</th><th>Basis</th><th>Section</th><th>Phase</th><th className="num">Service amount</th><th>Unit rates</th><th className="num">Amount</th></tr>
        </thead>
        <tbody>
          {services.map(line => <Fragment key={line.client_key ?? line.id ?? line.service_id}>
            <tr className="ps-line">
              <td><strong>{line.service_code}</strong> · {line.service_name}<div className="ps-sub">{line.provider_type} · {line.vendor_name || 'No vendor'}{line.remarks ? ` · ${line.remarks}` : ''}</div></td>
              <td>{line.charging_basis}</td>
              <td>{line.section_label || (line.charging_basis === 'Per Section Rate' ? 'Per section' : 'All sections')}</td>
              <td>{line.phase_label || '—'}</td>
              <td className="num">{line.charging_basis === 'Per Service Rate' ? amountText(line.service_amount, line.currency) : '—'}</td>
              <td>{line.rates.length ? line.rates.map(rate => `${rate.category} ${amountText(rate.unit_rate)}`).join('; ') : '—'}</td>
              <td className="num">{amountText(line.amount, line.currency)}</td>
            </tr>
            {componentRows(line.components, line.currency)}
          </Fragment>)}
        </tbody>
      </table>}
    </section>

    <section>
      <h2>4. Consumables ({consumables.length})</h2>
      {consumables.length === 0 ? <p className="ps-empty">No consumable lines.</p> : <table className="ps-table ps-grid">
        <thead>
          <tr><th>Category / item</th><th>Section</th><th>Phase</th><th className="num">Quantity</th><th className="num">Rate</th><th>Currency</th><th className="num">Amount</th></tr>
        </thead>
        <tbody>
          {consumables.map(line => <Fragment key={line.client_key ?? line.id ?? `${line.category}-${line.hole_section_id}-${line.phase_id ?? ''}`}>
            <tr className="ps-line">
              <td><strong>{line.category}</strong>{line.category === 'Drill Bits'
                ? <div className="ps-sub">{line.bit_code} · {line.bit_name} · {line.manufacturer || 'No make'} · {line.bit_type} · {line.size}{line.bit_description ? ` · ${line.bit_description}` : ''}</div>
                : <div className="ps-sub">Lump sum estimate{line.remarks ? ` · ${line.remarks}` : ''}</div>}</td>
              <td>{line.section_label}</td>
              <td>{line.phase_label || '—'}</td>
              <td className="num">{line.category === 'Drill Bits' ? line.quantity : '—'}</td>
              <td className="num">{line.effective_rate ? amountText(line.effective_rate) : '—'}</td>
              <td>{line.currency}</td>
              <td className="num">{amountText(line.amount)}</td>
            </tr>
            {componentRows(line.components, line.currency)}
          </Fragment>)}
        </tbody>
      </table>}
    </section>

    <section>
      <h2>5. Tangibles ({tangibles.length})</h2>
      {tangibles.length === 0 ? <p className="ps-empty">No tangible lines.</p> : <table className="ps-table ps-grid">
        <thead>
          <tr><th>Tangible</th><th>Manufacturer</th><th>UOM</th><th className="num">Quantity</th><th className="num">Rate</th><th>Currency</th><th className="num">Amount</th></tr>
        </thead>
        <tbody>
          {tangibles.map(line => <Fragment key={line.client_key ?? line.id ?? line.tangible_id}>
            <tr className="ps-line">
              <td><strong>{line.tangible_code}</strong> · {line.tangible_name}<div className="ps-sub">{line.tangible_description}{line.remarks ? ` · ${line.remarks}` : ''}</div></td>
              <td>{line.manufacturer_name || '—'}</td>
              <td>{line.uom || '—'}</td>
              <td className="num">{line.quantity}</td>
              <td className="num">{amountText(line.effective_rate)}{line.override_rate ? ' (override)' : ''}</td>
              <td>{line.currency}</td>
              <td className="num">{amountText(line.amount)}</td>
            </tr>
            {componentRows(line.components, line.currency)}
          </Fragment>)}
        </tbody>
      </table>}
    </section>

    <footer className="ps-footer">
      <p><strong>AFE remarks:</strong> {afe.remarks || '—'}</p>
      {afe.status_remarks && <p><strong>Status remarks:</strong> {afe.status_remarks}</p>}
      <p>Prepared from the saved cost estimate. Amounts are shown in each line’s currency; totals are not converted between currencies.</p>
    </footer>
  </div>, document.body)
}

import { useEffect, useState } from 'react'
import { createPortal, flushSync } from 'react-dom'
import { mudQuantity, type MudCostBalanceRow } from '../../lib/mudCost'

export type MudCostPrintReport = {
  rig: string
  well: string
  section: string
  view: string
  period: string
  rows: MudCostBalanceRow[]
  entryCount: number
  sectionCount: number
}

export function MudCostPrintSheet({ report }: { report: MudCostPrintReport | null }) {
  if (!report) return null
  return createPortal(<article className="afe-print-sheet mud-cost-print-sheet" aria-hidden="true">
    <header className="ps-titlebar">
      <div className="ps-title">
        <div className="ps-eyebrow">WellCosting Pro · Daily Cost Management</div>
        <h1>Mud Cost Analysis — Material Balance</h1>
      </div>
      <div className="ps-titlemeta">
        <strong className="ps-titlecode">{report.rig}</strong>
        <span>{report.well}</span>
        <span className="ps-printed">Printed {new Date().toLocaleString()}</span>
      </div>
    </header>
    <table className="ps-meta"><tbody>
      <tr><th>Section scope</th><td>{report.section}</td><th>View</th><td>{report.view}</td></tr>
      <tr><th>Period</th><td colSpan={3}>{report.period}</td></tr>
      <tr><th>Sections</th><td>{report.sectionCount}</td><th>Daily entries</th><td>{report.entryCount}</td></tr>
    </tbody></table>
    <p className="ps-note">Values are shown in the unit entered for each well section. No quantities are combined across sections.</p>
    {report.rows.length ? <table className="ps-table">
      <thead><tr>
        <th>Date / period</th><th>Section</th><th className="num">Opening stock</th><th className="num">Receipt</th>
        <th className="num">Additions</th><th className="num">Consumption / losses</th><th className="num">Others</th>
        <th className="num">Book closing</th><th className="num">Actual closing</th><th className="num">Variance</th>
      </tr></thead>
      <tbody>{report.rows.map(row => <tr key={row.id}>
        <td>{row.period_label}{row.entry_count > 1 ? <div className="ps-sub">{row.first_entry_date} to {row.last_entry_date} · {row.entry_count} entries</div> : null}</td>
        <td>{row.section_label}</td>
        <td className="num">{mudQuantity(row.opening_stock)}</td>
        <td className="num">{mudQuantity(row.receipt)}</td>
        <td className="num">{mudQuantity(row.additions)}</td>
        <td className="num">{mudQuantity(row.consumption_losses)}</td>
        <td className="num">{mudQuantity(row.others)}</td>
        <td className="num">{mudQuantity(row.book_closing_stock)}</td>
        <td className="num">{mudQuantity(row.actual_closing_stock)}</td>
        <td className="num">{mudQuantity(row.variance)}</td>
      </tr>)}</tbody>
    </table> : <p className="ps-empty">No material-balance rows in the selected scope and period.</p>}
    <p className="ps-note">Book closing stock = opening stock + receipt + additions − consumption/losses − others. Variance = actual closing stock − book closing stock.</p>
  </article>, document.body)
}

export function useMudCostPrint() {
  const [report, setReport] = useState<MudCostPrintReport | null>(null)
  useEffect(() => {
    const clear = () => {
      setReport(null)
      document.getElementById('mud-cost-print-page')?.remove()
    }
    window.addEventListener('afterprint', clear)
    return () => {
      window.removeEventListener('afterprint', clear)
      document.getElementById('mud-cost-print-page')?.remove()
    }
  }, [])
  const print = (next: MudCostPrintReport) => {
    document.getElementById('mud-cost-print-page')?.remove()
    const pageStyle = document.createElement('style')
    pageStyle.id = 'mud-cost-print-page'
    pageStyle.media = 'print'
    pageStyle.textContent = '@page { size: A4 landscape; margin: 8mm; }'
    document.head.appendChild(pageStyle)
    flushSync(() => setReport(next))
    window.print()
  }
  return { print, printSheet: <MudCostPrintSheet report={report}/> }
}

// Print regression check. Run after make ui-check (which installs jsdom):
// cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
// ../.agent/tools/daily-cost-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
// --outfile=node_modules/.cache/daily-cost-check.mjs --external:jsdom && node node_modules/.cache/daily-cost-check.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { url: 'http://localhost/' })
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Event']) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { DailyCostPrintSheet, useCostPrint } = await import('../../frontend/src/components/daily-cost/DailyCostPrintSheet')
const line = {
  quantity: '12', quantity_unit: 'hours', currency: 'USD', effective_rate: '100', captured_rate: '100',
  amount: '50', standard_amount: '50', exchange_rate: '1', rate_source: 'Locked AFE rate',
  rate_revision_number: 2, rate_effective_date: '2026-10-01', classification: 'Planned',
  service_code: 'SVC', service_name: 'Mud logging', charging_basis: 'Day Rate', charge_category: 'Operation',
  activity_code: 'DRL', activity_name: 'Drilling', sub_activity_code: 'SA1', sub_activity_name: 'Logging',
  section_code: 'SURFACE', section_name: 'Surface hole', phase_code: 'DRILL', phase_name: 'Drilling',
  party_name: 'Operator', vendor_code: 'V1', vendor_name: 'Vendor', sub_activity_party: 'Operations',
  override_rate: null, override_reason: '', budget_name: 'Service budget', budget_key: 'service:1', remarks: 'Line notes',
}
const day = {
  entry: { id: 'd1', daily_cost_code: 'DC-1', cost_date: '2026-10-10', afe_id: 'afe1', afe_code: 'AFE-1', afe_name: 'Drilling',
    well_code: 'WELL-1', well_name: 'Well one', rig_code: 'RIG-1', rig_name: 'Rig one', afe_status: 'approved',
    standard_currency: 'USD', status: 'draft', remarks: '<script>unsafe</script>', services_total: '6000', consumables_total: '0',
    tangibles_total: '0', other_expenses_total: '3000', total_cost: '9000', upa_total: '0', npt_total: '3000' },
  comparison: { effective_on: '2026-10-10', includes_draft_entries: true, planned_total: '7000', actual_to_date: '9000', balance: '-2000',
    tracked_actual_to_date: '6000', other_expenses_to_date: '3000',
    upa_to_date: '0', npt_to_date: '3000', budget_lines: [
      { budget_key: 'service:1', item_code: 'SVC', item_name: 'Logging', cost_group: 'Services', planned: '7000', actual_to_date: '6000', balance: '1000', is_planned: true },
      { budget_key: 'other:LIH', item_code: 'LIH', item_name: 'Lost In Hole (LIH)', cost_group: 'Other Expenses', planned: '0', actual_to_date: '3000', balance: '-3000', is_planned: false }] },
  services: Array.from({ length: 120 }, (_, index) => ({ ...line, id: `line-${index}`, remarks: `Row ${index} notes` })),
  consumables: [], tangibles: [], warnings: [{ code: 'draft', message: 'Includes draft actuals' }],
  other_expenses: [{ ...line, id: 'other1', expense_type: 'LIH', expense_type_label: 'Lost In Hole (LIH)',
    expense_description: 'Three joints of BHA left in hole', classification: 'NPT', quantity: '2', quantity_unit: 'unit',
    effective_rate: '1500', captured_rate: '1500', amount: '3000', standard_amount: '3000', rate_source: 'Other expense (entered rate)',
    budget_key: 'other:LIH', budget_name: 'Other expenses — Lost In Hole (LIH)', remarks: 'Drill collar lost in hole on tripping' }],
}
const second = { ...day, entry: { ...day.entry, id: 'd2', afe_id: 'afe2', afe_code: 'AFE-2', daily_cost_code: 'DC-2', standard_currency: 'EUR', services_total: '0', total_cost: '100', consumables_total: '100', other_expenses_total: '0', npt_total: '0' },
  comparison: { ...day.comparison, tracked_actual_to_date: '100', other_expenses_to_date: '0', actual_to_date: '100', balance: '6900', npt_to_date: '0',
    budget_lines: [{ budget_key: 'consumable:BAR', item_code: 'BAR', item_name: 'Barite', cost_group: 'Consumables', planned: '7000', actual_to_date: '100', balance: '6900', is_planned: true }] },
  services: [], other_expenses: [],
  consumables: [{ ...line, id: 'chemical1', currency: 'EUR', category: 'Mud Chemicals', item_code: 'BAR', item_name: 'Barite', uom: 'MT', quantity_unit: 'unit', override_rate: '50', override_reason: 'Justified daily override' }],
  tangibles: [{ ...line, id: 'tangible1', tangible_code: 'T1', tangible_name: 'Casing', uom: 'm' }],
}
const root = createRoot(document.getElementById('root'))
await act(async () => root.render(<DailyCostPrintSheet report={{ title: 'Well costing sheet', period: 'Inception to date', days: [day, second] }}/>))
let sheet = document.querySelector('.afe-print-sheet')
assert.ok(sheet, 'print sheet is a body portal')
assert.equal(sheet.parentElement, document.body)
assert.ok(sheet.classList.contains('daily-cost-print-sheet'), 'daily costing opts into the landscape report page')
assert.ok(sheet.querySelector('.daily-report-cover'), 'the model-report summary is page one')
assert.ok(sheet.querySelector('.daily-report-details'), 'the retained detailed schedules follow the cover')
for (const heading of [
  'Reporting milestone', 'Section-wise planned depth & current depth', 'Services cost · AFE vs cumulative actual',
  'Consumables cost · AFE vs cumulative actual', 'Tangibles cost · AFE vs actual', 'AFE vs actual summary',
  'Mud chemical cost · section-wise', 'Consumption / losses · cumulative', 'Mud cost analysis · section / mud type',
  'NPT summary', 'UPA summary',
]) assert.ok(sheet.textContent.includes(heading), `cover prints ${heading}`)
assert.ok(sheet.textContent.includes('Row 119 notes'), 'all 120 rows print, no grid pagination')
assert.equal(sheet.querySelectorAll('.ps-total').length, 2, 'separate AFE/currency totals')
assert.ok(sheet.querySelector('.ps-total').textContent.includes('USD 6,000.00'))
assert.ok(sheet.querySelectorAll('.ps-total')[1].textContent.includes('EUR 100.00'))
for (const text of ['Services (120)', 'Consumables (1)', 'Tangibles (1)', 'Barite', 'Casing', 'Rate trace:', 'FX 1', 'Justified daily override', 'AFE budget reconciliation', 'Includes draft actuals', '<script>unsafe</script>',
  // Other expenses print as their own section and as their own deduction from the AFE.
  '6. Other expenses (LIH, hole problems and similar charges) (1)', 'Lost In Hole (LIH) · Three joints of BHA left in hole',
  'Drill collar lost in hole on tripping', 'Remarks (mandatory):', 'Daily other expenses', '1 line(s)',
  'Less other expenses to sheet date', 'Services, consumables and tangibles to sheet date', 'Other expenses (Lost In Hole, hole problems, claims) carry no AFE allowance',
  'Other expenses', 'LIH · Lost In Hole (LIH) · unbudgeted']) {
  assert.ok(sheet.textContent.includes(text), `prints ${text}`)
}
assert.equal(sheet.querySelector('script'), null, 'remarks remain escaped')
assert.ok(sheet.textContent.includes('6. Other expenses (LIH, hole problems and similar charges) (0)'), 'a day without unexpected charges prints an empty section')
assert.equal(sheet.querySelectorAll('.ps-empty').length, 4, 'the three empty groups and the empty other-expense group say so')
// A single deduction is printed in the AFE register as well as in the day sheet.
assert.ok(sheet.textContent.includes('Other expenses') && sheet.querySelector('.ps-total').textContent.includes('USD 3,000.00'), 'other expenses are a column of the AFE register')
assert.ok(sheet.textContent.includes('USD 9,000.00'), 'the period total still adds the deduction into the day cost')
let trigger
function PrintHarness() { const hook = useCostPrint(); trigger = hook.print; return hook.printSheet }
await act(async () => root.render(<PrintHarness/>))
let printCalled = false
window.print = () => {
  printCalled = true
  assert.ok(document.querySelector('.afe-print-sheet').textContent.includes('DC-1'), 'portal is mounted before window.print')
}
await act(async () => trigger({ title: 'Daily sheet', period: 'Today', days: [day] }))
assert.ok(printCalled)
await act(async () => window.dispatchEvent(new Event('afterprint')))
assert.equal(document.querySelector('.afe-print-sheet'), null, 'afterprint removes stale output')
await act(async () => root.unmount())
const register = readFileSync('../frontend/src/pages/DailyCostManagement.tsx', 'utf8')
for (const forbidden of ['daily-cost/overview', 'StatCard', 'ReactECharts', 'cumulativeById', 'ACTUAL TO DATE']) {
  assert.ok(!register.includes(forbidden), `register does not contain ${forbidden}`)
}
for (const retained of ['New daily sheet', 'Well cost analysis', 'Filter by well', 'Filter by AFE', '<DataTable', 'Print well costing sheet', 'exportAudit', 'Deleted entries']) {
  assert.ok(register.includes(retained), `register retains ${retained}`)
}
const sheetPage = readFileSync('../frontend/src/pages/DailyCostSheet.tsx', 'utf8')
for (const retained of ["'other_expenses'", 'Less other expenses', 'Other Expenses']) {
  assert.ok(sheetPage.includes(retained), `day sheet retains ${retained}`)
}
const analysis = readFileSync('../frontend/src/pages/DailyCostAnalysis.tsx', 'utf8')
for (const retained of ["headerName: 'OTHER EXPENSES'", "name: 'Other expenses'", 'other_expenses']) {
  assert.ok(analysis.includes(retained), `analysis retains ${retained}`)
}
const styles = readFileSync('../frontend/src/styles.css', 'utf8')
assert.ok(styles.includes('.MuiModal-root { display: none !important; }'), 'print hides the report dialog overlay')
assert.ok(styles.includes('overflow: visible !important'), 'print removes dialog body scroll lock')
assert.ok(styles.includes('@page daily-cost-report'), 'daily reports define a dedicated landscape print page')
assert.ok(styles.includes('size: A4 landscape'), 'daily reports print in landscape')
assert.ok(styles.includes('margin: 4mm'), 'daily reports use minimal print margins')
console.log('Daily cost checks passed: landscape model-report cover, retained complete print sections with other-expense deduction, 120 rows, separate AFE/currency totals, escaped remarks, synchronous print portal, cleanup, list-only register, other-expense wiring on sheet and analysis.')

dom.window.close()
process.exit(0)

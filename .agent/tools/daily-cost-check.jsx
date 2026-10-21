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
  quantity: '12.126', quantity_unit: 'hours', currency: 'USD', effective_rate: '100', captured_rate: '100',
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
    tangibles_total: '0', other_expenses_total: '3000', total_cost: '9000', upa_total: '0', npt_total: '3000', actual_depth: '1234.567' },
  comparison: { effective_on: '2026-10-10', includes_draft_entries: true, planned_total: '7000', actual_to_date: '9000', balance: '-2000',
    tracked_actual_to_date: '6000', other_expenses_to_date: '3000',
    upa_to_date: '0', npt_to_date: '3000', budget_lines: [
      { budget_key: 'service:1', item_code: 'SVC', item_name: 'Logging', cost_group: 'Services', planned: '7000', actual_to_date: '6000', balance: '1000', is_planned: true },
      { budget_key: 'other:LIH', item_code: 'LIH', item_name: 'Lost In Hole (LIH)', cost_group: 'Other Expenses', planned: '0', actual_to_date: '3000', balance: '-3000', is_planned: false }] },
  services: Array.from({ length: 120 }, (_, index) => ({ ...line, id: `line-${index}`, remarks: `Row ${index} notes` })),
  consumables: [], tangibles: [], warnings: [{ code: 'draft', message: 'Includes draft actuals' }],
  progress: { scope: 'drilling', scope_label: 'Drilling', progress_label: 'Drilling complete', spud_at: '2026-10-02T12:00',
    progress_completed_at: null, is_completed: false, planned_days: '10.126', actual_days: '8.126', days_variance: '-2', as_of_date: '2026-10-10' },
  other_expenses: [{ ...line, id: 'other1', expense_type: 'LIH', expense_type_label: 'Lost In Hole (LIH)',
    expense_description: 'Three joints of BHA left in hole', classification: 'NPT', quantity: '48', quantity_unit: 'hours',
    effective_rate: '1500', captured_rate: '1500', amount: '3000', standard_amount: '3000', rate_source: 'Other expense (entered rate)',
    budget_key: 'other:LIH', budget_name: 'Other expenses — Lost In Hole (LIH)', remarks: 'Drill collar lost in hole on tripping' }],
}
const second = { ...day, entry: { ...day.entry, id: 'd2', afe_id: 'afe2', afe_code: 'AFE-2', daily_cost_code: 'DC-2', standard_currency: 'EUR', services_total: '0', total_cost: '100', consumables_total: '100', other_expenses_total: '0', npt_total: '0' },
  comparison: { ...day.comparison, tracked_actual_to_date: '100', other_expenses_to_date: '0', actual_to_date: '100', balance: '6900', npt_to_date: '0',
    budget_lines: [
      { budget_key: 'service:20', budget_kind: 'service', item_code: 'SVC-20', item_name: 'Directional drilling', cost_group: 'Services', planned: '2000', actual_to_date: '400', balance: '1600', is_planned: true },
      { budget_key: 'service:03', budget_kind: 'service', item_code: 'SVC-03', item_name: 'Mud logging', cost_group: 'Services', planned: '1000', actual_to_date: '300', balance: '700', is_planned: true },
      { budget_key: 'consumable:Fuel', budget_kind: 'consumable_category', item_code: 'Fuel', item_name: 'Fuel allowance', cost_group: 'Consumables', planned: '7000', actual_to_date: '100', balance: '6900', is_planned: true },
      { budget_key: 'consumable:Mud Chemicals', budget_kind: 'consumable_category', item_code: 'Mud Chemicals', item_name: 'Mud Chemicals allowance', cost_group: 'Consumables', planned: '2000', actual_to_date: '250', balance: '1750', is_planned: true },
      { budget_key: 'consumable:Cement Additives', budget_kind: 'consumable_category', item_code: 'Cement Additives', item_name: 'Cement Additives allowance', cost_group: 'Consumables', planned: '1500', actual_to_date: '125', balance: '1375', is_planned: true },
      { budget_key: 'drill-bit:BIT-A', budget_kind: 'drill_bit', item_code: 'BIT-A', item_name: 'Bit Alpha', cost_group: 'Consumables', planned: '3000', actual_to_date: '800', balance: '2200', is_planned: true },
      { budget_key: 'drill-bit:BIT-B', budget_kind: 'drill_bit', item_code: 'BIT-B', item_name: 'Bit Beta', cost_group: 'Consumables', planned: '2500', actual_to_date: '700', balance: '1800', is_planned: true },
      { budget_key: 'tangible:T1', budget_kind: 'tangible', item_code: 'T1', item_name: 'Casing', cost_group: 'Tangibles', planned: '4000', actual_to_date: '900', balance: '3100', is_planned: true },
    ] },
  services: [], other_expenses: [],
  consumables: [{ ...line, id: 'chemical1', currency: 'EUR', category: 'Mud Chemicals', item_code: 'BAR', item_name: 'Barite', uom: 'MT', quantity_unit: 'unit', override_rate: '50', override_reason: 'Justified daily override' }],
  tangibles: [{ ...line, id: 'tangible1', tangible_code: 'T1', tangible_name: 'Casing', uom: 'm' }],
}
day.entry.section_depths = [{ hole_section_id: 'section-1', section_code: 'SURFACE', section_name: 'Surface hole', actual_depth: '1234.567', depth_unit: 'm', entered_depth: '1234.567', entered_unit: 'm', daily_cost_code: 'DC-1' }]
second.entry.section_depths = day.entry.section_depths
const mudReconciliation = { currency: 'EUR', sections: [{ section_id: 'section-1', hole_section_id: 'section-1', section_label: 'SURFACE · Surface hole', mud_type: 'OBM', additions: '60', total_mud: '90', consumption_losses: '15', cost_per_bbl: '12.5', reconciled_cost: '187.5', actual_cost: '200' }] }
const mudBalance = { view: 'section', rows: [{ section_id: 'section-1', opening_stock: '20', receipt: '30', additions: '60', consumption_losses: '15', closing_stock: '95' }] }
const root = createRoot(document.getElementById('root'))
await act(async () => root.render(<DailyCostPrintSheet report={{ title: 'Well costing sheet', period: 'Inception to date', days: [day, second], mudReconciliation, mudBalance, milestoneLabel: 'Side track on date / time' }}/>))
let sheet = document.querySelector('.afe-print-sheet')
assert.ok(sheet, 'print sheet is a body portal')
assert.equal(sheet.parentElement, document.body)
assert.ok(sheet.classList.contains('daily-cost-print-sheet'), 'daily costing opts into the landscape report page')
assert.ok(sheet.querySelector('.daily-report-cover'), 'the model-report summary is page one')
assert.ok(sheet.querySelector('.daily-report-details'), 'cumulative schedules follow the cover')
const coverPanels = sheet.querySelectorAll('.daily-report-cover .dcr-cost-panel')
const serviceNames = [...coverPanels[0].querySelectorAll('tbody tr')].map(row => row.cells[0].textContent)
assert.deepEqual(serviceNames, ['Mud logging', 'Directional drilling'], 'services follow hidden natural service-code order')
const consumableRows = [...coverPanels[1].querySelectorAll('tbody tr')]
const consumableNames = consumableRows.map(row => row.cells[0].textContent)
assert.deepEqual(consumableNames, ['Mud Chemicals', 'Cement Additives', 'Fuel', 'Drill Bits'], 'consumables print the four fixed category totals only')
assert.equal(consumableNames.filter(name => name === 'Drill Bits').length, 1, 'drill bits print as one cumulative row')
const drillBitsRow = consumableRows.find(row => row.cells[0].textContent === 'Drill Bits')
assert.ok(drillBitsRow.textContent.includes('EUR 5,500.00') && drillBitsRow.textContent.includes('EUR 1,500.00'), 'drill bit AFE and actual values are cumulative')
for (const hidden of ['SVC-03', 'SVC-20', 'Bit Alpha', 'Bit Beta', 'Mud Chemicals allowance', 'Cement Additives allowance']) {
  assert.ok(!sheet.querySelector('.daily-report-cover').textContent.includes(hidden), `${hidden} is hidden from the summary`)
}
for (const heading of [
  'Reporting milestone', 'Section-wise planned depth & current depth', 'Services cost · AFE vs cumulative actual',
  'Consumables cost · AFE vs cumulative actual', 'Tangibles cost · AFE vs actual', 'AFE vs actual summary',
  'Mud chemical cost · section-wise', 'Consumption / losses · cumulative', 'Mud cost analysis · section / mud type',
  'NPT summary', 'UPA summary',
]) assert.ok(sheet.textContent.includes(heading), `cover prints ${heading}`)
assert.ok(sheet.textContent.includes('Side track on date / time'), 'the report prints the user-edited milestone label')
assert.ok(!sheet.textContent.includes('Row 119 notes'), 'daily service-line breakdowns are omitted from cumulative reports')
for (const heading of ['Service-wise cumulative cost', 'Consumables cumulative cost · four categories', 'Tangibles cumulative cost · item-wise']) {
  assert.ok(sheet.textContent.includes(heading), `cumulative pages print ${heading}`)
}
const matrix = sheet.querySelector('.dcr-mud-analysis')
for (const text of ['Surface hole', 'OBM', 'Opening Stock', 'Receipt', 'Additions', 'Total Mud', 'Losses', 'Closing Stock', 'Meterage (current depth)', 'Cost / BBL', 'Reconciled Cost', '20.00', '30.00', '60.00', '90.00', '15.00', '95.00', '1,234.57 m', 'EUR 12.50', 'EUR 187.50']) {
  assert.ok(matrix.textContent.includes(text), `mud matrix prints ${text}`)
}
for (const code of ['DC-1', 'DC-2', 'AFE-1', 'AFE-2', 'WELL-1', 'RIG-1', 'SVC', 'SURFACE', 'DRL', 'DRILL', 'SA1', 'V1', 'T1', 'BAR']) {
  assert.ok(!sheet.textContent.includes(code), `${code} is omitted in favour of its name`)
}
assert.ok(sheet.textContent.includes('1,234.57 m'), 'printed depth rounds to two decimals')
assert.ok(sheet.textContent.includes('Casing') && sheet.textContent.includes('EUR 900.00'), 'tangible items and cumulative prices print')
assert.equal(sheet.querySelector('script'), null, 'remarks remain escaped')
let trigger
function PrintHarness() { const hook = useCostPrint(); trigger = hook.print; return hook.printSheet }
await act(async () => root.render(<PrintHarness/>))
let printCalled = false
window.print = () => {
  printCalled = true
  const printed = document.querySelector('.afe-print-sheet')
  assert.ok(printed.textContent.includes('Well one'), 'portal is mounted before window.print with the well name')
  const timePosition = printed.querySelector('.dcr-time').textContent
  for (const text of ['Planned', '10.13 days', 'Actual from spud', '8.13 days', 'Actual against planned activities', '6.13 days', 'NPT', '2.00 days', 'UPA', '0.00 days']) {
    assert.ok(timePosition.includes(text), `time position prints ${text}`)
  }
  assert.ok(!timePosition.includes('Variance') && !timePosition.includes('Sheets / status'), 'time position omits variance and sheet status')
}
await act(async () => trigger({ title: 'Daily sheet', period: 'Today', days: [day], milestoneLabel: 'Side track on date / time' }))
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
for (const retained of ["'other_expenses'", 'Less other expenses', 'Other Expenses', 'Assign scope / depth / quantity', 'Milestone label in report', 'MudCostMaterialBalance']) {
  assert.ok(sheetPage.includes(retained), `day sheet retains ${retained}`)
}
const bulkDialog = readFileSync('../frontend/src/components/daily-cost/DailyCostBulkScopeDialog.tsx', 'utf8')
for (const retained of ['Set one depth for all', 'Actual depth', 'Depth unit', 'Set one quantity and unit for all', 'Charged quantity', 'Quantity unit']) {
  assert.ok(bulkDialog.includes(retained), `bulk service editor exposes ${retained}`)
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
console.log('Daily cost checks passed: bulk depth/quantity/unit controls, editable milestone label, planned-activity days, transposed mud matrix, code-ordered/name-only services, four cumulative consumable categories, item-wise tangible cumulative costs, cumulative-only continuation pages, two-decimal presentation, landscape model-report cover, escaped remarks, synchronous print portal, cleanup and register wiring.')

dom.window.close()
process.exit(0)

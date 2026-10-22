// Print regression check. Run after make ui-check (which installs jsdom):
// cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
// ../.agent/tools/daily-cost-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
// --outfile=node_modules/.cache/daily-cost-check.mjs --external:jsdom && node node_modules/.cache/daily-cost-check.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment', 'ShadowRoot', 'MouseEvent', 'KeyboardEvent', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement']) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { DailyCostPrintSheet, useCostPrint, validLeadLagDays } = await import('../../frontend/src/components/daily-cost/DailyCostPrintSheet')
const { costReportTitle } = await import('../../frontend/src/lib/dailyCost')
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
    upa_to_date: '300', npt_to_date: '3000', groups: [
      { cost_group: 'Services', planned: '7000', actual_to_date: '6000', balance: '1000', actual_planned: '5500', actual_upa: '300', actual_npt: '200' },
      { cost_group: 'Other Expenses', planned: '0', actual_to_date: '3000', balance: '-3000', actual_planned: '0', actual_upa: '0', actual_npt: '3000' }],
    budget_lines: [
      { budget_key: 'service:1', item_code: 'SVC', item_name: 'Logging', cost_group: 'Services', planned: '7000', actual_to_date: '6000', balance: '1000', is_planned: true,
        actual_planned: '5500', actual_upa: '300', actual_npt: '200' },
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
    groups: [
      { cost_group: 'Services', planned: '3000', actual_to_date: '700', balance: '2300', actual_planned: '650', actual_upa: '50', actual_npt: '0' },
      { cost_group: 'Consumables', planned: '5000', actual_to_date: '100', balance: '4900', actual_planned: '100', actual_upa: '0', actual_npt: '0' }],
    budget_lines: [
      { budget_key: 'service:20', budget_kind: 'service', item_code: 'SVC-20', item_name: 'Directional drilling', service_group: 'Rig Operations', cost_group: 'Services', planned: '2000', actual_to_date: '400', balance: '1600', is_planned: true,
        actual_planned: '400', actual_upa: '0', actual_npt: '0' },
      { budget_key: 'service:03', budget_kind: 'service', item_code: 'SVC-03', item_name: 'Mud logging', service_group: 'Supervisions', cost_group: 'Services', planned: '1000', actual_to_date: '300', balance: '700', is_planned: true,
        actual_planned: '250', actual_upa: '50', actual_npt: '0' },
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
const mudReconciliation = { currency: 'EUR', sections: [{ section_id: 'section-1', hole_section_id: 'section-1', section_label: 'SURFACE · Surface hole', mud_type: 'OBM', additions: '60', total_mud: '90', consumption_losses: '15', cost_per_bbl: '12.5', reconciled_cost: '187.5', actual_cost: '200',
  verti_g_mud_on_cuttings: '1', centrifuge: '2', by_pass: '3', evaporation: '4', trips: '5', surface_loss_total: '15',
  mud_cleaner: '6', formation_seepage: '7', pit_cleaning_dump: '8', left_in_hole: '9', other_losses: '10', other_loss_total: '40', total_losses: '55' }] }
const mudBalance = { view: 'section', rows: [{ section_id: 'section-1', opening_stock: '20', receipt: '30', additions: '60', consumption_losses: '15', closing_stock: '95' }] }
const root = createRoot(document.getElementById('root'))
await act(async () => root.render(<DailyCostPrintSheet report={{ title: 'Well costing sheet', period: 'Inception to date', days: [day, second], mudReconciliation, mudBalance, milestoneLabel: 'Side track on date / time', leadLagKind: 'LEAD', leadLagDays: '2.75' }}/>))
let sheet = document.querySelector('.afe-print-sheet')
assert.ok(sheet, 'print sheet is a body portal')
assert.equal(sheet.parentElement, document.body)
assert.ok(sheet.classList.contains('daily-cost-print-sheet'), 'daily costing opts into the landscape report page')
assert.ok(sheet.querySelector('.daily-report-cover'), 'the model-report summary is page one')
assert.ok(sheet.querySelector('.daily-report-details'), 'cumulative schedules follow the cover')
const coverPanels = sheet.querySelectorAll('.daily-report-cover .dcr-cost-panel')
const serviceNames = [...coverPanels[0].querySelectorAll('tbody tr')].map(row => row.cells[0].textContent)
assert.deepEqual(serviceNames, ['Rig Operations · Directional drilling', 'Supervisions · Mud logging'],
  'services print in reporting-group order before the hidden service code')
const consumableRows = [...coverPanels[1].querySelectorAll('tbody tr')]
const consumableNames = consumableRows.map(row => row.cells[0].textContent)
assert.deepEqual(consumableNames, ['Mud Chemicals', 'Cement Additives', 'Fuel', 'Drill Bits'], 'consumables print the four fixed category totals only')
assert.equal(consumableNames.filter(name => name === 'Drill Bits').length, 1, 'drill bits print as one cumulative row')

// The services table alone splits the cumulative actual by activity
// classification between the AFE and the total actual.
const servicePanel = coverPanels[0]
assert.ok(servicePanel.classList.contains('dcr-cost-panel--split'), 'only the services table opts into the compacted split layout')
const serviceHeaderRows = servicePanel.querySelectorAll('thead tr')
assert.equal(serviceHeaderRows.length, 2, 'the services table groups its three classification columns')
assert.deepEqual([...serviceHeaderRows[0].cells].map(cell => cell.textContent),
  ['Cost item', 'AFE', 'Actual cost by activity', 'Total actual', 'Balance', 'Used'], 'services print AFE, the activity split and the total actual')
assert.deepEqual([...serviceHeaderRows[1].cells].map(cell => cell.textContent), ['Planned', 'UPA', 'NPT'])
const serviceBodyRows = [...servicePanel.querySelectorAll('tbody tr')]
assert.equal(serviceBodyRows[0].cells.length, 8, 'a service row prints eight compacted cells')
const mudLoggingSplit = serviceBodyRows.find(row => row.cells[0].textContent === 'Supervisions · Mud logging')
assert.deepEqual([...mudLoggingSplit.cells].map(cell => cell.textContent),
  ['Supervisions · Mud logging', 'EUR 1,000.00', 'EUR 250.00', 'EUR 50.00', 'EUR 0.00', 'EUR 300.00', 'EUR 700.00', '30.00%'],
  'a service row prints planned, UPA and NPT actuals before the total actual')
const serviceFooter = [...servicePanel.querySelectorAll('tfoot tr:last-child th')].map(cell => cell.textContent)
assert.deepEqual(serviceFooter,
  ['Group total', 'EUR 3,000.00', 'EUR 650.00', 'EUR 50.00', 'EUR 0.00', 'EUR 700.00', 'EUR 2,300.00', '23.33%'],
  'the services footer totals each classification and the total actual')
for (const otherPanel of [...coverPanels].slice(1)) {
  assert.ok(!otherPanel.classList.contains('dcr-cost-panel--split'), 'other cost tables keep their five columns')
}
assert.equal(coverPanels[1].querySelectorAll('thead th').length, 5, 'consumables keep five columns')

// The report title names the well scope it costs.
assert.equal(costReportTitle('well', ['drilling'], 'WELL-1'), 'Well Cost Report - Drilling · WELL-1')
assert.equal(costReportTitle('daily', ['completion'], 'WELL-1'), 'Daily Cost Report - Completions · WELL-1')
assert.equal(costReportTitle('well', ['completion', 'drilling'], 'WELL-1'), 'Well Cost Report - Drilling & Completions · WELL-1')
assert.equal(costReportTitle('daily', [], 'WELL-1'), 'Daily Cost Report · WELL-1', 'no scope keeps the plain title')
const drillBitsRow = consumableRows.find(row => row.cells[0].textContent === 'Drill Bits')
assert.ok(drillBitsRow.textContent.includes('EUR 5,500.00') && drillBitsRow.textContent.includes('EUR 1,500.00'), 'drill bit AFE and actual values are cumulative')
for (const hidden of ['SVC-03', 'SVC-20', 'Bit Alpha', 'Bit Beta', 'Mud Chemicals allowance', 'Cement Additives allowance']) {
  assert.ok(!sheet.querySelector('.daily-report-cover').textContent.includes(hidden), `${hidden} is hidden from the summary`)
}
for (const heading of [
  'Reporting milestone', 'Section-wise planned depth & current depth', 'Services cost · AFE vs cumulative actual by activity',
  'Consumables cost · AFE vs cumulative actual', 'Tangibles cost · AFE vs actual', 'AFE vs actual summary',
  'Mud chemical cost · section-wise', 'Consumption / losses · cumulative', 'Mud cost analysis · section / mud type',
  'NPT summary', 'UPA summary',
]) assert.ok(sheet.textContent.includes(heading), `cover prints ${heading}`)
assert.ok(sheet.textContent.includes('Side track on date / time'), 'the report prints the user-edited milestone label')
assert.ok(sheet.querySelector('.dcr-titlebar h1').textContent.endsWith('(LEAD: 2.75 days)'), 'selected decimal lead days print at the end of the title')
assert.ok(validLeadLagDays('LAG', '0.125') && !validLeadLagDays('LAG', '') && !validLeadLagDays('LEAD', '-1'), 'lead/lag validation accepts non-negative decimals only')
assert.ok(!sheet.textContent.includes('Row 119 notes'), 'daily service-line breakdowns are omitted from cumulative reports')
for (const heading of ['Service-wise cumulative cost', 'Consumables cumulative cost · four categories', 'Tangibles cumulative cost · item-wise']) {
  assert.ok(sheet.textContent.includes(heading), `cumulative pages print ${heading}`)
}
const matrix = sheet.querySelector('.dcr-mud-analysis')
for (const text of ['Surface hole', 'OBM', 'Opening Stock', 'Receipt', 'Additions', 'Total Mud', 'Losses', 'Closing Stock', 'Meterage (current depth)', 'Cost / BBL', 'Reconciled Cost', '20.00', '30.00', '60.00', '90.00', '15.00', '95.00', '1,234.57 m', 'EUR 12.50', 'EUR 187.50']) {
  assert.ok(matrix.textContent.includes(text), `mud matrix prints ${text}`)
}
const lossMatrix = sheet.querySelector('.dcr-loss-matrix')
assert.ok(lossMatrix, 'consumption and losses print as a matrix')
for (const text of ['Surface hole', 'OBM', 'Surface losses', 'Verti-G/Mud on Cuttings', 'Centrifuge', 'By-Pass', 'Evaporation', 'Trips', 'Surface losses total', 'Other losses', 'Mud Cleaner', 'Formation/Seepage', 'Pit Cleaning/Dump', 'Left-In-Hole', '10.00', 'Other losses total', 'Total losses', '15.00', '40.00', '55.00']) {
  assert.ok(lossMatrix.textContent.includes(text), `loss matrix prints ${text}`)
}
assert.equal(lossMatrix.querySelectorAll('thead th').length, 2, 'loss matrix uses sections and mud types as columns')
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
  assert.ok(printed.querySelector('.dcr-titlebar h1').textContent.endsWith('(LEAD/LAG: 0 days)'), 'no selection prints the zero lead/lag fallback')
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

// The shared advanced selector collects many priced items at once, refuses a checked
// item until it has a usage quantity, and can hide everything that is not ticked.
const { ThemeProvider } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const { AdvancedSelectorDialog } = await import('../../frontend/src/components/AdvancedItemSelector')
const catalogueItems = [
  { id: 'chem-1', kind: 'consumable', code: 'BAR', name: 'Barite', description: '', uom: 'MT', rate: '125', currency: 'USD' },
  { id: 'chem-2', kind: 'consumable', code: 'BEN', name: 'Bentonite', description: '', uom: 'Sack', rate: '40', currency: 'USD' },
  { id: 'tangible-1', kind: 'tangible', code: 'CSG', name: 'Casing', description: '', uom: 'Joint', rate: '900', currency: 'USD' },
]
const itemRows = items => items.map(item => ({
  id: item.id, code: item.code, name: item.name, description: item.description,
  uom: item.uom, rate: item.rate, currency: item.currency,
}))
let selectedRows = null
let selectorKind = 'consumable'
let selectorRender = 0
const selectorRoot = createRoot(document.getElementById('root'))
async function showSelector(kind, items) {
  selectorKind = kind
  selectedRows = null
  selectorRender += 1
  const rows = itemRows(items)
  await act(async () => selectorRoot.render(<ThemeProvider theme={buildTheme('light')}>
    <AdvancedSelectorDialog
      key={selectorRender}
      open
      title={`Advanced selector — ${kind === 'consumable' ? 'Mud chemicals' : 'Tangibles'}`}
      itemNoun={kind === 'consumable' ? 'mud chemical' : 'tangible'}
      items={rows}
      rateText={item => `${item.currency} ${Number(item.rate).toFixed(2)}`}
      onClose={() => {}}
      onAdd={rowsSelected => { selectedRows = rowsSelected; return null }}
    />
  </ThemeProvider>))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
async function click(element, message) {
  assert.ok(element, message)
  await act(async () => element.dispatchEvent(new w.MouseEvent('click', { bubbles: true })))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
async function enterUsage(itemName, value, prefix = 'Usage quantity') {
  const label = [...document.querySelectorAll('label')].find(label => label.textContent?.startsWith(`${prefix} for ${itemName}`))
  const input = label?.control
  assert.ok(input, `usage input exists for ${itemName}`)
  await act(async () => {
    Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, 'value').set.call(input, value)
    input.dispatchEvent(new w.Event('input', { bubbles: true }))
    input.dispatchEvent(new w.Event('change', { bubbles: true }))
  })
}
function selectorButton(label) {
  return [...document.querySelectorAll('button')].find(button => button.textContent?.trim().startsWith(label))
}
function selectorSubmit() { return [...document.querySelectorAll('button')].find(button => button.textContent?.startsWith('Add selected items')) }
const itemNamesShown = () => [...document.querySelectorAll('table tbody tr')].map(row => row.textContent || '').join('|')

await showSelector('consumable', catalogueItems.slice(0, 2))
assert.ok(document.body.textContent.includes('USD 125.00') && document.body.textContent.includes('USD 40.00'), 'mud chemical selector displays locked unit prices')
assert.ok(selectorButton('Show selected only'), 'selector offers the show-selected-only button')
assert.ok(document.body.textContent.includes('2 available') && document.body.textContent.includes('0 selected'), 'selector reports how many items are available and selected')
await click(document.querySelector('input[aria-label="Select BAR · Barite"]'), 'Barite checkbox exists')
await click(selectorSubmit(), 'bulk add button exists')
assert.ok(document.body.textContent.includes('Enter the usage quantity for BAR · Barite.'), 'checked mud chemical prompts for missing usage')
// A rejected submit switches to the selected-only review so the missing row is visible.
assert.ok(selectorButton('Show all items'), 'a missing usage switches the selector to selected-only review')
assert.ok(itemNamesShown().includes('Barite') && !itemNamesShown().includes('Bentonite'), 'show selected only hides unticked items')
assert.ok(document.body.textContent.includes('1 selected') && document.body.textContent.includes('1 shown'), 'show selected only reports the hidden rows')
await enterUsage('Barite', '2.5')
await click(selectorButton('Show all items'), 'show all items restores the list')
assert.ok(itemNamesShown().includes('Barite') && itemNamesShown().includes('Bentonite'), 'show all items restores the unticked rows')

// The toggle also works manually and keeps selections when it is flipped back.
await click(selectorButton('Show selected only'), 'show selected only can be turned on')
assert.ok(!itemNamesShown().includes('Bentonite'), 'show selected only hides unticked items again')
await click(selectorButton('Show all items'), 'show all items restores the list again')

await click(document.querySelector('input[aria-label="Select BEN · Bentonite"]'), 'Bentonite checkbox exists')
await enterUsage('Bentonite', '4')
await click(selectorSubmit(), 'bulk add button remains available')
assert.deepEqual(selectedRows?.map(row => [row.item.id, row.quantity]), [['chem-1', '2.5'], ['chem-2', '4']], 'selected mud chemicals are returned as separate bulk rows')

await showSelector('tangible', catalogueItems.slice(2))
assert.ok(document.body.textContent.includes('Advanced selector — Tangibles') && document.body.textContent.includes('USD 900.00'), 'tangible selector lists item and locked unit price')
await click(document.querySelector('input[aria-label="Select CSG · Casing"]'), 'Casing checkbox exists')
await click(selectorSubmit(), 'tangible bulk add button exists')
assert.ok(document.body.textContent.includes('Enter the usage quantity for CSG · Casing.'), 'checked tangible prompts for missing usage')
await enterUsage('Casing', '3')
await click(selectorSubmit(), 'tangible add button remains available')
assert.deepEqual(selectedRows?.map(row => [row.item.id, row.quantity]), [['tangible-1', '3']], 'selected tangible is returned as a bulk row')
assert.equal(selectorKind, 'tangible')
await act(async () => selectorRoot.unmount())

// The AFE cost estimate reuses the same selector when adding tangibles.
const { TangibleLineDialog } = await import('../../frontend/src/components/afe/TangibleLineDialog')
const afeReference = {
  tangibles: [
    { id: 'tangible-afe-1', tangible_code: 'CSG', tangible_name: 'Casing', scope: 'Drilling', category_name: 'Tubular', subcategory_name: 'Casing', manufacturer_name: 'Acme', description: '9 5/8 in casing', uom: 'Joint', captured_rate: '900', currency: 'USD', display_name: 'CSG · Casing' },
    { id: 'tangible-afe-2', tangible_code: 'WHP', tangible_name: 'Wellhead', scope: 'Completion', category_name: 'Wellhead', subcategory_name: '', manufacturer_name: 'Acme', description: 'Surface wellhead', uom: 'unit', captured_rate: '5000', currency: 'USD', display_name: 'WHP · Wellhead' },
  ],
}
let afeSaved = null
const tangibleRoot = createRoot(document.createElement('div'))
await act(async () => tangibleRoot.render(<ThemeProvider theme={buildTheme('light')}>
  <TangibleLineDialog open initial={null} reference={afeReference} onClose={() => {}} onSave={lines => { afeSaved = lines }}/>
</ThemeProvider>))
await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
await click(selectorButton('Advanced selector'), 'the AFE tangible dialog offers the advanced selector')
assert.ok(document.body.textContent.includes('Advanced selector — Tangibles'), 'the AFE selector opens for tangibles')
await click(document.querySelector('input[aria-label="Select CSG · Casing"]'), 'AFE selector lists the master tangible')
await click(selectorSubmit(), 'AFE selector add button exists')
assert.ok(document.body.textContent.includes('Enter the quantity for CSG · Casing.'), 'the AFE selector requires a quantity')
await enterUsage('Casing', '4', 'Quantity')
await click(selectorSubmit(), 'the AFE selector accepts the quantity')
// MUI keeps a closing dialog in the DOM until its exit transition ends.
await act(async () => { await new Promise(resolve => setTimeout(resolve, 350)) })
assert.equal(document.querySelectorAll('[role="dialog"]').length, 1, 'the AFE selector closes after adding the items')
assert.ok(document.body.textContent.includes('1 tangible added'), 'added tangibles are reported in the AFE dialog')
assert.ok(document.body.textContent.includes('Tangible item #1'), 'the added tangible appears as a line to review')
const afeSubmit = [...document.querySelectorAll('.MuiDialogActions-root button')]
  .find(button => button.textContent?.trim() === 'Add tangible')
await click(afeSubmit, 'the AFE tangible dialog keeps its save action')
assert.deepEqual(afeSaved?.map(line => [line.tangible_id, line.quantity]), [['tangible-afe-1', '4']], 'the AFE estimate receives the selected tangibles as separate lines')
await act(async () => tangibleRoot.unmount())
const register = readFileSync('../frontend/src/pages/DailyCostManagement.tsx', 'utf8')
for (const forbidden of ['daily-cost/overview', 'StatCard', 'ReactECharts', 'cumulativeById', 'ACTUAL TO DATE']) {
  assert.ok(!register.includes(forbidden), `register does not contain ${forbidden}`)
}
for (const retained of ['New daily sheet', 'Well cost analysis', 'Filter by well', 'Filter by AFE', '<DataTable', 'Print well costing sheet', 'exportAudit', 'Deleted entries']) {
  assert.ok(register.includes(retained), `register retains ${retained}`)
}
const sheetPage = readFileSync('../frontend/src/pages/DailyCostSheet.tsx', 'utf8')
for (const retained of ["'other_expenses'", 'Less other expenses', 'Other Expenses', 'Assign scope / depth / quantity', 'Milestone label in report', 'Lead / Lag days', 'validLeadLagDays', 'MudCostMaterialBalance']) {
  assert.ok(sheetPage.includes(retained), `day sheet retains ${retained}`)
}
const wellPrintDialog = readFileSync('../frontend/src/components/daily-cost/WellCostPrintDialog.tsx', 'utf8')
for (const retained of ['Lead / Lag', 'Lead / Lag days', 'LEAD/LAG: 0 days', 'validLeadLagDays']) {
  assert.ok(wellPrintDialog.includes(retained), `well print dialog retains ${retained}`)
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
console.log('Daily cost checks passed: advanced consumable/tangible bulk selection with required usage, locked prices and show-selected-only review, the same selector reused by the AFE tangible estimate, bulk depth/quantity/unit controls, editable milestone and lead/lag title suffix, planned-activity days, scope-aware report titles, service-wise Planned/UPA/NPT actual columns with an unchanged five-column layout elsewhere, transposed mud and loss matrices, group-ordered/name-only services, four cumulative consumable categories, item-wise tangible cumulative costs, cumulative-only continuation pages, two-decimal presentation, landscape model-report cover, escaped remarks, synchronous print portal, cleanup and register wiring.')

dom.window.close()
process.exit(0)

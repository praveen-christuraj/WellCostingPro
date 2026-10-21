// AFE print regression check. Run after installing jsdom in frontend with --no-save:
// cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
// ../.agent/tools/afe-print-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
// --outfile=node_modules/.cache/afe-print-check.mjs --external:jsdom && \
// node node_modules/.cache/afe-print-check.mjs
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
const { AfePrintSheet } = await import('../../frontend/src/components/afe/AfePrintSheet')

const estimate = {
  afe: {
    id: 'afe1', rig_id: 'rig1', rig_code: 'RIG-1', rig_name: 'Rig one', well_id: 'well1', well_code: 'WELL-1', well_name: 'Well one',
    well_status: 'active', afe_code: 'AFE-1', afe_name: 'Drilling estimate', afe_type: 'Drilling', configuration_scope: 'drilling', remarks: 'AFE notes',
    status: 'approval', status_remarks: 'Approved', status_changed_at: '2026-10-14T09:00:00Z', status_changed_by: 'Approver',
    estimate_saved_at: '2026-10-14T08:00:00Z', estimate_saved_by: 'Estimator', service_count: 1, consumable_count: 1, tangible_count: 1,
    services_total: '100', consumables_total: '20', tangibles_total: '30', total_cost: '150', standard_currency: 'USD', conversion_pending: false,
    totals_by_currency: [], warning_count: 0, is_deleted: false, deleted_at: null, created_at: '2026-10-14T07:00:00Z', updated_at: '2026-10-14T09:00:00Z',
  },
  well: {
    scope: 'drilling', well_id: 'well1', well_code: 'WELL-1', well_name: 'Well one', well_location: 'Field', block: 'Block A', objective: 'Production',
    rig_code: 'RIG-1', rig_name: 'Rig one', depth_unit: 'm', status: 'active', config_status: 'configured', total_depth: '1000.126', total_days: '10.126',
    sections: [{ hole_section_id: 'section1', section_code: 'SEC-1', section_name: 'Surface', from_depth: '0.125', to_depth: '1000.126', total_days: '10.126',
      phases: [{ phase_id: 'phase1', phase_code: 'DRILL', phase_name: 'Drilling', days: '10.126' }] }],
  },
  services: [{
    id: 'service-line1', client_key: null, service_id: 'service1', service_code: 'SVC-HIDE-ME', service_name: 'Mud logging', service_category: 'Drilling Services',
    provider_type: 'Third Party Services', vendor_name: 'Vendor one', charging_basis: 'Per Service Rate', hole_section_id: null, section_label: '', phase_id: null,
    phase_label: '', currency: 'USD', service_amount: '100', remarks: 'Service notes', rates: [], charges: [], section_rates: [], amount: '100', warnings: [], components: [],
  }],
  consumables: [{
    id: 'consumable1', client_key: null, category: 'Mud Chemicals', hole_section_id: 'section1', section_label: 'SEC-1 · Surface', phase_id: null, phase_label: '',
    drill_bit_id: null, bit_code: '', bit_name: '', bit_type: '', manufacturer: '', model_no: '', size: '', iadc_code: '', serial_number: '', bit_description: '',
    quantity: '1', captured_rate: '20', override_rate: null, effective_rate: '20', estimated_amount: '20', currency: 'USD', remarks: '', amount: '20', warnings: [], components: [],
  }],
  tangibles: [{
    id: 'tangible-line1', client_key: null, tangible_id: 'tangible1', tangible_code: 'TANG-KEEP', tangible_name: 'Casing', tangible_scope: 'Drilling',
    category_name: 'Tubulars', subcategory_name: 'Casing', manufacturer_name: 'Maker', tangible_description: '', uom: 'm', quantity: '1.126', captured_rate: '30',
    override_rate: null, effective_rate: '30', currency: 'USD', remarks: '', amount: '30', warnings: [], components: [],
  }],
  summary: {
    services_total: '100', consumables_total: '20', tangibles_total: '30', total: '150', totals_by_currency: [{ currency: 'USD', amount: '150' }],
    currency: { standard_currency: 'USD', currencies: ['USD'], multi_currency: false, converted: true, standard_missing: false, missing_rates: [], exchange_rates: [] },
    by_section: [], warnings: [],
  },
  status_history: [], persisted: true, saved_at: '2026-10-14T08:00:00Z', saved_by: 'Estimator',
}

const root = createRoot(document.getElementById('root'))
await act(async () => root.render(<AfePrintSheet estimate={estimate}/>))
const sheet = document.querySelector('.afe-cost-print-sheet')
assert.ok(sheet, 'AFE print sheet has its report-specific class')
const pages = sheet.querySelectorAll(':scope > .ps-page')
assert.equal(pages.length, 2, 'report keeps its two explicit page groups')
assert.ok(pages[0].textContent.includes('Mud logging'), 'service name prints on page one')
assert.ok(!sheet.textContent.includes('SVC-HIDE-ME'), 'service code is omitted from the entire AFE report')
for (const code of ['RIG-1', 'WELL-1', 'AFE-1', 'SEC-1', 'DRILL', 'TANG-KEEP']) {
  assert.ok(!sheet.textContent.includes(code), `${code} is omitted in favour of its name`)
}
assert.ok(pages[0].textContent.includes('Consumables lump sum') && pages[0].textContent.includes('Tangibles lump sum'), 'page one prints only group lump sums')
assert.ok(!pages[0].textContent.includes('Sections and depths') && pages[1].textContent.includes('Sections and depths'), 'section detail starts on page two')
assert.ok(pages[1].textContent.includes('Casing'), 'tangible name remains visible without its code')
assert.ok(pages[1].textContent.includes('1,000.13 m') && pages[1].textContent.includes('10.13 d') && pages[1].textContent.includes('1.13'), 'depths, days and quantities round to two decimals')
assert.ok(!pages[0].textContent.includes('Authorisation') && pages[1].textContent.includes('Authorisation'), 'sign-off is kept with supporting detail')

const sectionEstimate = structuredClone(estimate)
sectionEstimate.services = [
  { ...estimate.services[0], charging_basis: 'Per Section Rate', currency: 'EUR', service_amount: '0', amount: '175',
    section_rates: [
      { hole_section_id: 'section1', section_label: 'SEC-1 · Surface', phase_id: 'phase1', phase_label: 'DRILL · Drilling', amount: '75' },
      { hole_section_id: 'section2', section_label: 'SEC-2 · Intermediate', phase_id: null, phase_label: '', amount: '100' },
    ] },
  { ...estimate.services[0], id: 'day-rate', charging_basis: 'Day Rate', hole_section_id: 'section1', section_label: 'SEC-1 · Surface',
    phase_id: 'phase1', phase_label: 'DRILL · Drilling', currency: 'USD', amount: '80',
    rates: [{ category: 'Operation', unit_rate: '40' }], charges: [{ category: 'Operation', quantity: '2.126', quantity_unit: 'days' }] },
  { ...estimate.services[0], id: 'fixed-rate', section_label: 'SEC-1 · Surface', phase_label: 'DRILL · Drilling' },
]
await act(async () => root.render(<AfePrintSheet estimate={sectionEstimate}/>))
const servicesTable = document.querySelector('.ps-afe-summary .ps-table')
assert.deepEqual([...servicesTable.querySelectorAll('thead th')].map(cell => cell.textContent),
  ['#', 'Service', 'Basis / entered rates', 'Amount', 'Remarks'], 'the first-page schedule has five columns without Scope or Currency')
assert.equal(servicesTable.querySelectorAll('colgroup col').length, 5, 'column widths match the five headers')
const serviceRows = servicesTable.querySelectorAll('tbody tr.ps-line')
assert.equal(serviceRows[0].cells.length, 5, 'section-rate row has no extra scope or currency cells')
assert.ok(serviceRows[0].cells[2].textContent.includes('Surface · Drilling: EUR 75.00'), 'first section and phase names show their entered rate')
assert.ok(serviceRows[0].cells[2].textContent.includes('Intermediate: EUR 100.00'), 'second section name and rate show separately')
assert.equal(serviceRows[0].cells[3].textContent, 'EUR 175.00', 'service amount still identifies its entered currency')
assert.ok(serviceRows[1].cells[2].textContent.includes('Operation USD 40.00 × 2.13 days'), 'day rates retain currency and two-decimal quantity')
assert.ok(serviceRows[1].cells[2].textContent.includes('Surface · Drilling'), 'scoped day rates retain section and phase names in Basis')
assert.ok(serviceRows[2].cells[2].textContent.includes('Fixed USD 100.00'), 'fixed rates retain their currency')
assert.equal(servicesTable.querySelector('tr.ps-subtotal').cells[0].colSpan, 3, 'services total spans the remaining label columns')

const longSchedule = structuredClone(sectionEstimate)
longSchedule.services = Array.from({ length: 8 }, (_, index) => ({ ...sectionEstimate.services[0], id: `section-line-${index}` }))
await act(async () => root.render(<AfePrintSheet estimate={longSchedule}/>))
assert.ok(document.querySelector('.ps-afe-summary.ps-afe-dense'), 'multiple section rates trigger compact layout before service count alone would')

const styles = readFileSync('../frontend/src/styles.css', 'utf8')
assert.ok(styles.includes('.afe-cost-print-sheet th,') && styles.includes('overflow-wrap: anywhere'), 'AFE cells have scoped wrapping rules')
assert.ok(styles.includes('.afe-cost-print-sheet .ps-afe-dense'), 'large service schedules receive the compact density step')

await act(async () => root.unmount())
dom.window.close()
console.log('AFE print checks passed: name-only entities, two-decimal measurements, five-column service schedule, entered section rates, currency labels and compact two-page grouping.')
process.exit(0)

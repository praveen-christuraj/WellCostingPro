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
    rig_code: 'RIG-1', rig_name: 'Rig one', depth_unit: 'm', status: 'active', config_status: 'configured', total_depth: '1000', total_days: '10',
    sections: [{ hole_section_id: 'section1', section_code: 'SEC-1', section_name: 'Surface', from_depth: '0', to_depth: '1000', total_days: '10',
      phases: [{ phase_id: 'phase1', phase_code: 'DRILL', phase_name: 'Drilling', days: '10' }] }],
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
    category_name: 'Tubulars', subcategory_name: 'Casing', manufacturer_name: 'Maker', tangible_description: '', uom: 'm', quantity: '1', captured_rate: '30',
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
assert.ok(pages[0].textContent.includes('Consumables lump sum') && pages[0].textContent.includes('Tangibles lump sum'), 'page one prints only group lump sums')
assert.ok(!pages[0].textContent.includes('Sections and depths') && pages[1].textContent.includes('Sections and depths'), 'section detail starts on page two')
assert.ok(pages[1].textContent.includes('TANG-KEEP'), 'tangible code remains visible')
assert.ok(!pages[0].textContent.includes('Authorisation') && pages[1].textContent.includes('Authorisation'), 'sign-off is kept with supporting detail')

const styles = readFileSync('../frontend/src/styles.css', 'utf8')
assert.ok(styles.includes('.afe-cost-print-sheet th,') && styles.includes('overflow-wrap: anywhere'), 'AFE cells have scoped wrapping rules')
assert.ok(styles.includes('.afe-cost-print-sheet .ps-afe-dense'), 'large service schedules receive the compact density step')

await act(async () => root.unmount())
dom.window.close()
console.log('AFE print checks passed: service codes hidden, tangible codes retained, compact page grouping and scoped wrapping present.')
process.exit(0)

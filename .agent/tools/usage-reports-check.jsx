// Reports module check: renders the real theme plus the shared usage-report
// components (matrix, NPT/UPA matrix, filter panel) in jsdom and asserts the
// matrix structure, cost-only behaviour, tangible category bands, NPT/UPA
// measures and filter controls in both light and dark themes.
//
// Contributor tool only — nothing here is imported by the app, and jsdom is
// installed with --no-save so application dependencies stay unchanged.
//
// Run from frontend/:
//   npm install --no-save jsdom && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/usage-reports-check.jsx --bundle --platform=node --format=esm \
//     --jsx=automatic --outfile=node_modules/.cache/usage-reports-check.mjs \
//     --loader:.jsx=jsx --log-level=error --external:jsdom && \
//     node node_modules/.cache/usage-reports-check.mjs
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = w.matchMedia || (q => ({ matches: false, media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false }))
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment', 'ShadowRoot', 'MouseEvent', 'KeyboardEvent', 'CustomEvent', 'DOMRect', 'HTMLInputElement']) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const createCache = (await import('@emotion/cache')).default
const { CacheProvider } = await import('@emotion/react')
const { createRoot } = await import('react-dom/client')
const { ThemeProvider, CssBaseline } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const UsageMatrix = (await import('../../frontend/src/components/reports/UsageMatrix')).default
const NptUpaMatrix = (await import('../../frontend/src/components/reports/NptUpaMatrix')).default
const UsageReportFilters = (await import('../../frontend/src/components/reports/UsageReportFilters')).default

const results = []
const check = (label, pass, detail = '') => results.push({ label, pass: !!pass, detail })

const sectionA = { section_key: 'sec-1', hole_section_id: 'sec-1', section_code: '17-1/2', section_name: 'Surface hole', scope: 'drilling' }
const sectionB = { section_key: 'sec-2', hole_section_id: 'sec-2', section_code: '12-1/4', section_name: 'Intermediate hole', scope: 'drilling' }

const wells = [
  { well_id: 'w1', well_code: 'WELL-01', well_name: 'Well One', rig_id: 'r1', rig_code: 'RIG-01', rig_name: 'Rig One', block_id: 'b1', block_code: 'BLOCK-A', block_name: 'Block A', scopes: ['drilling'], sections: [sectionA, sectionB] },
  { well_id: 'w2', well_code: 'WELL-02', well_name: 'Well Two', rig_id: 'r2', rig_code: 'RIG-02', rig_name: 'Rig Two', block_id: 'b2', block_code: 'BLOCK-B', block_name: 'Block B', scopes: ['drilling'], sections: [sectionA] },
]

const matrixReport = (overrides = {}) => ({
  report: 'mud-chemicals',
  mode: 'usage',
  currency: 'USD',
  date_from: '2026-10-01',
  date_to: '2026-10-31',
  include_draft: true,
  wells,
  rows: [
    {
      item_id: 'i1', item_code: 'BARITE', item_name: 'Barite', uom: 'MT', category: 'Weighting agent',
      subcategory: '', manufacturer: 'Halliburton', detail: 'Part no. BR-25',
      cells: [
        { well_id: 'w1', sections: [
          { section_key: 'sec-1', quantity: '10', amount: '500.00' },
          { section_key: 'sec-2', quantity: '5', amount: '250.00' },
        ], quantity: '15', amount: '750.00' },
        { well_id: 'w2', sections: [{ section_key: 'sec-1', quantity: '3', amount: '150.00' }], quantity: '3', amount: '150.00' },
      ],
      quantity_total: '18', amount_total: '900.00',
    },
  ],
  detail: [],
  well_totals: [
    { well_id: 'w1', sections: [], quantity: '15', amount: '750.00' },
    { well_id: 'w2', sections: [], quantity: '3', amount: '150.00' },
  ],
  grand_quantity: '18',
  grand_amount: '900.00',
  entry_count: 3,
  excluded_entry_count: 0,
  ...overrides,
})

const reference = {
  blocks: [{ id: 'b1', block_code: 'BLOCK-A', block_name: 'Block A' }, { id: 'b2', block_code: 'BLOCK-B', block_name: 'Block B' }],
  rigs: [{ id: 'r1', rig_code: 'RIG-01', rig_name: 'Rig One' }],
  wells: [
    { id: 'w1', rig_id: 'r1', block_id: 'b1', well_code: 'WELL-01', well_name: 'Well One', display_name: 'WELL-01 — Well One', status: 'active', config_status: 'configured', completion_status: 'active', completion_config_status: 'draft', scopes: ['drilling'], has_costs: true },
    { id: 'w2', rig_id: 'r2', block_id: 'b2', well_code: 'WELL-02', well_name: 'Well Two', display_name: 'WELL-02 — Well Two', status: 'completed', config_status: 'configured', completion_status: 'active', completion_config_status: 'draft', scopes: ['drilling'], has_costs: true },
  ],
  currencies: [{ code: 'USD', name: 'US Dollar', symbol: '$', is_default: true }],
  default_currency: 'USD',
}

const filters = {
  blockId: '', rigId: '', wellIds: [], scope: '', lifecycle: '', currency: 'USD',
  dateFrom: '', dateTo: '', includeDraft: true,
}

const nptReport = {
  currency: 'USD', date_from: null, date_to: null, include_draft: true,
  wells: [
    { well_id: 'w1', well_code: 'WELL-01', well_name: 'Well One', rig_code: 'RIG-01', block_code: 'BLOCK-A', planned_days: 1, upa_days: 1, npt_days: 1, planned_amount: '100.00', upa_amount: '650.00', npt_amount: '200.00', total_amount: '950.00' },
    { well_id: 'w2', well_code: 'WELL-02', well_name: 'Well Two', rig_code: 'RIG-02', block_code: 'BLOCK-B', planned_days: 1, upa_days: 0, npt_days: 0, planned_amount: '150.00', upa_amount: '0.00', npt_amount: '0.00', total_amount: '150.00' },
  ],
  detail: [],
  totals: { well_id: '', well_code: '', well_name: 'All wells (USD)', rig_code: '', block_code: '', planned_days: 2, upa_days: 1, npt_days: 1, planned_amount: '250.00', upa_amount: '650.00', npt_amount: '200.00', total_amount: '1100.00' },
  entry_count: 3, excluded_entry_count: 0,
}

const container = w.document.getElementById('root')
const root = createRoot(container)

for (const mode of ['light', 'dark']) {
  const cache = createCache({ key: `reportcheck-${mode}`, speedy: false })
  await act(async () => {
    root.render(
      <CacheProvider value={cache}>
        <ThemeProvider theme={buildTheme(mode)}>
          <CssBaseline />
          <UsageMatrix report={matrixReport()} title="Chemical usage matrix" hint="sections" />
          <NptUpaMatrix report={nptReport} currency="USD" />
          <UsageReportFilters reference={reference} filters={filters} onChange={() => {}} />
        </ThemeProvider>
      </CacheProvider>
    )
  })
  const doc = w.document
  const text = doc.body.textContent || ''

  check(`${mode}: matrix renders both well column headers`, text.includes('WELL-01 — Well One') && text.includes('WELL-02 — Well Two'))
  check(`${mode}: matrix renders section sub headers`, text.includes('Surface hole') && text.includes('Intermediate hole'))
  check(`${mode}: matrix renders item identity with uom and make`, text.includes('Barite') && text.includes('BARITE · MT · Halliburton'))
  check(`${mode}: matrix renders formatted quantities and money`, text.includes('900.00 USD') && text.includes('15') && text.includes('500.00 USD'))
  check(`${mode}: grand total row present`, text.includes('Grand total'))

  // Cost-only matrix hides every quantity column.
  await act(async () => {
    root.render(
      <CacheProvider value={cache}>
        <ThemeProvider theme={buildTheme(mode)}>
          <CssBaseline />
          <UsageMatrix report={matrixReport({
            report: 'services', mode: 'cost',
            rows: [{ ...matrixReport().rows[0], uom: '', quantity_total: '0', cells: [
              { well_id: 'w1', sections: [{ section_key: 'sec-1', quantity: '0', amount: '700.00' }], quantity: '0', amount: '700.00' },
              { well_id: 'w2', sections: [], quantity: '0', amount: '0.00' },
            ] }],
            grand_quantity: '0',
          })} title="Service cost matrix" hint="cost only" />
        </ThemeProvider>
      </CacheProvider>
    )
  })
  const costText = doc.body.textContent || ''
  check(`${mode}: cost-only report shows no QTY sub headers`, !costText.includes('QTY · COST'))
  check(`${mode}: cost-only report still shows costs`, costText.includes('700.00 USD') && costText.includes('Well total'))

  // Tangible category bands.
  await act(async () => {
    const base = matrixReport()
    root.render(
      <CacheProvider value={cache}>
        <ThemeProvider theme={buildTheme(mode)}>
          <CssBaseline />
          <UsageMatrix report={matrixReport({
            report: 'tangibles',
            rows: [
              { ...base.rows[0], item_id: 't1', item_code: 'TNG-01', item_name: 'Centraliser', category: 'Casing Accessories', subcategory: 'Centralisers' },
              { ...base.rows[0], item_id: 't2', item_code: 'TNG-02', item_name: 'Casing hanger', category: 'Wellhead Equipment', subcategory: 'Hangers' },
            ],
          })} title="Tangible matrix" hint="bands" />
        </ThemeProvider>
      </CacheProvider>
    )
  })
  const bandText = doc.body.textContent || ''
  check(`${mode}: tangible category bands render`, bandText.includes('Casing Accessories') && bandText.includes('Wellhead Equipment'))

  // NPT/UPA matrix.
  await act(async () => {
    root.render(
      <CacheProvider value={cache}>
        <ThemeProvider theme={buildTheme(mode)}>
          <CssBaseline />
          <NptUpaMatrix report={nptReport} currency="USD" />
        </ThemeProvider>
      </CacheProvider>
    )
  })
  const nptText = doc.body.textContent || ''
  check(`${mode}: NPT/UPA matrix lists the four measures`, nptText.includes('NPT days') && nptText.includes('NPT cost') && nptText.includes('UPA days') && nptText.includes('UPA cost'))
  check(`${mode}: NPT/UPA totals and per-well days render`, nptText.includes('650.00 USD') && nptText.includes('All wells'))

  // Filter panel.
  await act(async () => {
    root.render(
      <CacheProvider value={cache}>
        <ThemeProvider theme={buildTheme(mode)}>
          <CssBaseline />
          <UsageReportFilters reference={reference} filters={filters} onChange={() => {}} />
        </ThemeProvider>
      </CacheProvider>
    )
  })
  const labels = Array.from(doc.querySelectorAll('label')).map(label => label.textContent || '')
  check(`${mode}: filter panel exposes block, rig, scope, status, wells, currency and dates`,
    labels.some(label => label.includes('Block')) && labels.some(label => label.includes('Rig')) &&
    labels.some(label => label.includes('Scope')) && labels.some(label => label.includes('Well status')) &&
    labels.some(label => label.includes('Wells')) && labels.some(label => label.includes('Currency')) &&
    labels.some(label => label.includes('From date')) && labels.some(label => label.includes('To date')))
  check(`${mode}: filter panel shows all eligible wells by default`, doc.body.textContent.includes('All 2 eligible wells are included.'))

  // Lifecycle narrowing: completed only keeps WELL-02.
  await act(async () => {
    root.render(
      <CacheProvider value={cache}>
        <ThemeProvider theme={buildTheme(mode)}>
          <CssBaseline />
          <UsageReportFilters reference={reference} filters={{ ...filters, lifecycle: 'completed' }} onChange={() => {}} />
        </ThemeProvider>
      </CacheProvider>
    )
  })
  check(`${mode}: completed lifecycle narrows eligible wells to one`, doc.body.textContent.includes('All 1 eligible well is included.'))

  // Empty state.
  await act(async () => {
    root.render(
      <CacheProvider value={cache}>
        <ThemeProvider theme={buildTheme(mode)}>
          <CssBaseline />
          <UsageMatrix report={matrixReport({ wells: [], rows: [] })} title="Empty" hint="none" />
        </ThemeProvider>
      </CacheProvider>
    )
  })
  check(`${mode}: empty matrix shows the no-records alert`, doc.body.textContent.includes('No usage or cost records match the selected filters.'))
}

let failed = 0
for (const result of results) {
  console.log(`${result.pass ? 'PASS' : 'FAIL'}  ${result.label}${result.detail ? ` — ${result.detail}` : ''}`)
  if (!result.pass) failed += 1
}
console.log(failed ? `\n${failed} CHECK(S) FAILED` : `\nALL ${results.length} USAGE REPORT CHECKS PASSED`)
process.exit(failed ? 1 : 0)

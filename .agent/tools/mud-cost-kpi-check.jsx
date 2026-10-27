// Run with `make mud-cost-kpi-check`. Renders the real KPI component and page
// against server-shaped payloads, in both themes, including mutations and races.
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = q => ({ matches: false, media: q, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement', 'HTMLSelectElement',
  'MutationObserver', 'IntersectionObserver', 'localStorage', 'sessionStorage', 'NodeList', 'HTMLCollection',
  'DOMParser', 'SVGElement', 'FocusEvent', 'InputEvent', 'PointerEvent', 'WheelEvent', 'crypto',
]) if (w[key] !== undefined) Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

// AG Grid and MUI emit environment/act warnings under jsdom, not product errors.
for (const method of ['error', 'warn']) {
  const original = console[method]
  console[method] = (...args) => {
    const message = String(args[0] ?? '')
    if (message.startsWith('MUI:') || message.startsWith('An update to')) return
    original(...args)
  }
}

const { act, createElement } = await import('react')
const { createRoot } = await import('react-dom/client')
const { ThemeProvider } = await import('@mui/material')
const { createMemoryRouter, RouterProvider } = await import('react-router-dom')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const { buildTheme } = await import('../../frontend/src/theme')
const { mudQuantity } = await import('../../frontend/src/lib/mudCost')
const { MudCostKpis } = await import('../../frontend/src/components/mud-cost/MudCostKpis')

assert.equal(mudQuantity('0E-10'), '0', 'API decimal zero is not mistaken for missing data')
assert.equal(mudQuantity('1.23E+4'), '12,300')
assert.equal(mudQuantity('1E-3'), '0.001')
assert.equal(mudQuantity('-1.25e2'), '−125')
assert.equal(mudQuantity('999999999999999.1234567890'), '999,999,999,999,999.123', 'large quantities stay exact')
assert.equal(mudQuantity('not a quantity'), '—')

const sections = [
  { id: 's1', hole_section_id: 'h1', section_code: '17-1/2', section_name: 'Surface hole', scope: 'drilling', from_depth: '0', to_depth: '1000', is_current: true, display_name: '17-1/2 · Surface hole · Drilling' },
  { id: 's2', hole_section_id: 'h2', section_code: '12-1/4', section_name: 'Intermediate hole', scope: 'drilling', from_depth: '1000', to_depth: '2000', is_current: true, display_name: '12-1/4 · Intermediate hole · Drilling' },
  { id: 's3', hole_section_id: 'h3', section_code: '8-1/2', section_name: 'Production hole', scope: 'completion', from_depth: '2000', to_depth: '3000', is_current: true, display_name: '8-1/2 · Production hole · Completion' },
]
const sectionB = { id: 's4', hole_section_id: 'h4', section_code: '26', section_name: 'Second well hole', scope: 'drilling', from_depth: '0', to_depth: '500', is_current: true, display_name: '26 · Second well hole · Drilling' }
const makeBalance = (section, values) => ({
  id: `${section.id}:inception`, rig_id: 'r1', well_id: 'w1', section_id: section.id, section_scope: section.scope,
  section_code: section.section_code, section_name: section.section_name, section_label: section.display_name,
  cost_date: '2020-01-01', first_entry_date: '2020-01-01', last_entry_date: '2099-01-01', period_label: 'Inception', entry_count: 2,
  opening_stock: '0E-10', receipt: '0E-10', additions: '0E-10', consumption_losses: '0E-10', others: '0E-10', closing_stock: '0E-10', ...values,
})
const makeRecon = (section, values) => ({
  section_id: section.id, hole_section_id: section.hole_section_id, section_scope: section.scope,
  section_code: section.section_code, section_name: section.section_name, section_label: section.display_name,
  mud_type: null, is_configured: false, is_current: section.is_current, currency: 'USD', total_mud: '0E-10',
  cost_per_bbl: null, reconciled_cost: null, ...values,
})
const balance1 = makeBalance(sections[0], { opening_stock: '100.1250000000', receipt: '23', additions: '14', consumption_losses: '7', others: '3', closing_stock: '127.125' })
const balance2 = makeBalance(sections[1], { additions: '10', closing_stock: '10' })
const recon1 = makeRecon(sections[0], { mud_type: 'OBM', is_configured: true, total_mud: '134.125', cost_per_bbl: '2.6119402985', reconciled_cost: '18.2835820895' })
const recon2 = makeRecon(sections[1], { mud_type: 'WBM', is_configured: true, total_mud: '10', cost_per_bbl: '0E-10', reconciled_cost: '0E-10' })
const snapshot = (balanceRows = [balance1, balance2], reconRows = [recon1, recon2]) => ({
  rigId: 'r1', wellId: 'w1', balance: { view: 'inception', rows: balanceRows, entry_count: balanceRows.length, selected_section_count: balanceRows.length },
  reconciliation: { currency: 'USD', sections: reconRows, rows: [], configured_section_count: reconRows.length, unconfigured_section_count: 0 },
  balanceError: '', reconciliationError: '',
})
const metric = (card, name) => {
  const term = [...card.querySelectorAll('dt')].find(node => node.textContent === name)
  assert.ok(term, `metric ${name} is present in ${card.getAttribute('aria-label')}`)
  return term.nextElementSibling.textContent
}
const sectionValue = (card, name) => {
  const term = [...card.querySelectorAll('dt')].find(node => node.textContent.includes(name))
  assert.ok(term, `${name} is present in ${card.getAttribute('aria-label')}`)
  return term.nextElementSibling.textContent
}
const card = label => {
  const node = document.querySelector(`section[aria-label="${label}"]`)
  assert.ok(node, `card ${label} exists`)
  return node
}
const card1Label = 'Material balance: 17-1/2 · Surface hole · Drilling'
const card2Label = 'Material balance: 12-1/4 · Intermediate hole · Drilling'
const card3Label = 'Material balance: 8-1/2 · Production hole · Completion'
const stockLabel = 'Latest closing stock by section'
const rateLabel = 'Latest cost per barrel by section'
let root = createRoot(document.getElementById('root'))
async function renderKpis(mode, props) {
  await act(async () => root.render(<ThemeProvider theme={buildTheme(mode)}><MudCostKpis {...props}/></ThemeProvider>))
}

for (const mode of ['light', 'dark']) {
  await renderKpis(mode, { sections, settings: [], snapshot: snapshot(), loading: false })
  assert.equal(document.querySelectorAll('section[aria-label^="Material balance:"]').length, 3, 'one card per configured section')
  assert.equal(document.querySelectorAll(`section[aria-label="${stockLabel}"]`).length, 1)
  assert.equal(document.querySelectorAll(`section[aria-label="${rateLabel}"]`).length, 1)
  assert.equal(metric(card(card1Label), 'Opening stock'), '100.125')
  assert.equal(metric(card(card1Label), 'Receipt'), '23')
  assert.equal(metric(card(card1Label), 'Additions'), '14')
  assert.equal(metric(card(card1Label), 'Total mud (pricing)'), '134.125')
  assert.equal(metric(card(card1Label), 'Consumption / losses'), '7')
  assert.equal(metric(card(card1Label), 'Others'), '3')
  assert.equal(metric(card(card1Label), 'Reconciled cost'), 'USD 18.28')
  assert.equal(metric(card(card2Label), 'Opening stock'), '0')
  assert.equal(metric(card(card2Label), 'Receipt'), '0')
  assert.equal(metric(card(card3Label), 'Opening stock'), '—', 'no record is not an artificial zero')
  assert.match(card(card3Label).textContent, /No active entries/)
  assert.equal(sectionValue(card(stockLabel), 'Surface hole'), '127.125')
  assert.equal(sectionValue(card(stockLabel), 'Intermediate hole'), '10')
  assert.equal(sectionValue(card(stockLabel), 'Production hole'), '—')
  assert.equal(sectionValue(card(rateLabel), 'Surface hole'), 'USD 2.61')
  assert.equal(sectionValue(card(rateLabel), 'Intermediate hole'), 'USD 0.00', 'zero is a valid Cost/BBL')
  assert.equal(sectionValue(card(rateLabel), 'Production hole'), '—')
  assert.doesNotMatch(document.querySelector('#mud-kpi-heading').parentElement.textContent, /Sections used|Daily entries|Latest entry date/)
  assert.match(document.querySelector('#mud-kpi-heading').parentElement.textContent, /future-dated entries/)

  // A fourth section is not silently truncated; an empty well is explicit.
  await renderKpis(mode, { sections: [...sections, sectionB], settings: [], snapshot: snapshot(), loading: false })
  assert.equal(document.querySelectorAll('section[aria-label^="Material balance:"]').length, 4)
  await renderKpis(mode, { sections: [], settings: [], snapshot: snapshot([], []), loading: false })
  assert.equal(document.querySelectorAll('section[aria-label^="Material balance:"]').length, 0)
  assert.match(card(stockLabel).textContent, /No sections available/)

  // The two data sources fail independently; do not hide a valid balance/rate
  // or turn a failed request into fabricated zeroes.
  await renderKpis(mode, { sections, settings: [], snapshot: { ...snapshot(), reconciliation: null, reconciliationError: 'Mixed AFE currencies' }, loading: false })
  assert.match(document.querySelector('[role="alert"]').textContent, /Mixed AFE currencies/)
  assert.equal(metric(card(card1Label), 'Receipt'), '23')
  assert.equal(sectionValue(card(rateLabel), 'Surface hole'), '—')
  await renderKpis(mode, { sections, settings: [], snapshot: { ...snapshot(), balance: null, balanceError: 'Balance unavailable' }, loading: false })
  assert.match(document.querySelector('[role="alert"]').textContent, /Balance unavailable/)
  assert.equal(sectionValue(card(stockLabel), 'Surface hole'), '—')
  assert.equal(sectionValue(card(rateLabel), 'Surface hole'), 'USD 2.61')
  assert.doesNotMatch(card(card1Label).textContent, /No active entries/, 'a failed request is not reported as an empty section')

  // Reconciliation groups historical snapshots by scope/hole section; material
  // balances remain separate, and combined totals are not attributed twice.
  const old = { ...sections[0], id: 'old-s1', is_current: false }
  const oldBalance = makeBalance(old, { opening_stock: '25', receipt: '1', closing_stock: '26' })
  await renderKpis(mode, { sections: [sections[0], old], settings: [], snapshot: snapshot([balance1, oldBalance], [recon1]), loading: false })
  const oldCard = card('Material balance: 17-1/2 · Surface hole · Drilling · Historical')
  assert.equal(metric(oldCard, 'Opening stock'), '25')
  assert.equal(metric(card(card1Label), 'Opening stock'), '100.125')
  assert.equal(metric(oldCard, 'Total mud (pricing)'), '—')
  assert.equal(metric(card(card1Label), 'Reconciled cost'), '—')
  assert.match(oldCard.textContent, /Pricing totals are shared across section snapshots/)
  assert.match(document.querySelector('#mud-kpi-heading').parentElement.textContent, /Cost\/BBL is shared/)
  // Even a deleted-only historical snapshot may have Daily Cost charges keyed
  // to the same hole section; their pricing cannot safely be split by snapshot.
  await renderKpis(mode, { sections: [sections[0], old], settings: [], snapshot: snapshot([balance1], [recon1]), loading: false })
  assert.equal(metric(card(card1Label), 'Reconciled cost'), '—')
}

// ---------------------------------------------------------------------------
// Render the real page, checking independent filters, refresh, mutations, and
// out-of-order responses when the selected well changes.
// ---------------------------------------------------------------------------
await act(async () => root.unmount())
document.body.innerHTML = '<div id="root"></div>'
root = createRoot(document.getElementById('root'))
const rig = { id: 'r1', rig_code: 'R-1', rig_name: 'Rig one', display_name: 'R-1 · Rig one', is_deleted: false }
const wells = [
  { id: 'w1', rig_id: 'r1', well_code: 'W-1', well_name: 'Well one', display_name: 'W-1 · Well one', status: 'active', config_status: 'configured', is_deleted: false, sections },
  { id: 'w2', rig_id: 'r1', well_code: 'W-2', well_name: 'Well two', display_name: 'W-2 · Well two', status: 'active', config_status: 'configured', is_deleted: false, sections: [sectionB] },
]
const entry = {
  id: 'e1', rig_id: 'r1', rig_code: 'R-1', rig_name: 'Rig one', well_id: 'w1', well_code: 'W-1', well_name: 'Well one',
  section_id: 's1', hole_section_id: 'h1', section_scope: 'drilling', section_code: '17-1/2', section_name: 'Surface hole', section_label: sections[0].display_name,
  section_from_depth: '0', section_to_depth: '1000', entry_date: '2020-01-01', opening_stock: '100.125', opening_stock_remarks: '',
  receipt: '23', additions: '14', consumption_losses: '7', others: '3', closing_stock: '127.125', lines: [], is_deleted: false,
}
let liveBalance1 = { ...balance1 }
let liveRecon1 = { ...recon1 }
let reconFailure = false
let holdOldKpis = false
let held = []
let createdPayload = null
let correctedOpening = null
let configuredMudType = 'OBM'
const requests = []
const json = data => ({ ok: true, status: 200, json: async () => data })
const bad = detail => ({ ok: false, status: 409, json: async () => ({ detail }) })
const settings = (wellId) => (wellId === 'w1' ? sections : [sectionB]).map((s, i) => ({
  rig_id: 'r1', well_id: wellId, section_id: s.id, hole_section_id: s.hole_section_id,
  section_scope: s.scope, section_code: s.section_code, section_name: s.section_name, section_label: s.display_name, display_name: s.display_name,
  mud_type: i === 0 ? configuredMudType : i === 1 ? 'WBM' : null, mud_type_label: i === 0 ? 'Oil Based Mud' : i === 1 ? 'Water Based Mud' : 'Not configured',
  is_current: true, is_configured: i < 2, currency: 'USD', base_rate: '2', remarks: '',
}))
const copy = data => JSON.parse(JSON.stringify(data))
globalThis.fetch = async (url, init = {}) => {
  const u = new URL(String(url), 'http://localhost')
  const path = u.pathname.replace('/api/v1', '')
  const method = init.method ?? 'GET'
  requests.push({ path, method, query: new URLSearchParams(u.search) })
  if (path === '/auth/refresh') return json({ access_token: 'token' })
  if (path === '/auth/me') return json({ id: 'u1', email: 'owner@example.com', name: 'Owner', is_active: true, is_owner: true, permission_keys: [], organization_slug: 'acme', organization_name: 'Acme' })
  if (path === '/mud-cost/reference') return json({ rigs: [rig], wells })
  const wellId = u.searchParams.get('well_id') || 'w1'
  if (path === '/mud-cost/section-settings' && method === 'PUT') {
    const payload = JSON.parse(init.body)
    configuredMudType = payload.mud_type
    liveRecon1 = { ...liveRecon1, mud_type: payload.mud_type, cost_per_bbl: '5' }
    return json({ ...settings('w1')[0], mud_type: payload.mud_type })
  }
  if (path === '/mud-cost/section-settings') return json(settings(wellId))
  if (path === '/mud-cost/entries/e1/opening-stock' && method === 'PUT') {
    correctedOpening = JSON.parse(init.body)
    entry.opening_stock = correctedOpening.amount
    liveBalance1 = { ...liveBalance1, opening_stock: correctedOpening.amount, closing_stock: '234' }
    liveRecon1 = { ...liveRecon1, cost_per_bbl: '4.25' }
    return json(entry)
  }
  if (path === '/mud-cost/entries' && method === 'POST') {
    createdPayload = JSON.parse(init.body)
    liveBalance1 = { ...liveBalance1, receipt: '30', closing_stock: '134.125' }
    liveRecon1 = { ...liveRecon1, cost_per_bbl: '3.25' }
    return json({ id: 'new-entry' })
  }
  if (path === '/mud-cost/entries/deleted') return json([])
  if (path === '/mud-cost/entries') return json(wellId === 'w1' ? [entry] : [])
  if (path === '/mud-cost/material-balance') {
    const rows = wellId === 'w1' ? [liveBalance1, balance2] : [makeBalance(sectionB, { well_id: 'w2', opening_stock: '700', closing_stock: '700' })]
    const selected = u.searchParams.get('section_id')
    const result = { view: u.searchParams.get('view'), rows: selected ? rows.filter(row => row.section_id === selected) : rows, entry_count: rows.length, selected_section_count: rows.length }
    if (holdOldKpis && wellId === 'w1' && u.searchParams.get('view') === 'inception') return new Promise(resolve => held.push(() => resolve(json(copy(result)))))
    return json(copy(result))
  }
  if (path === '/mud-cost/reconciliation') {
    if (reconFailure && u.searchParams.get('to') === '9999-12-31') return bad('Mixed AFE currencies')
    const all = wellId === 'w1' ? [liveRecon1, recon2] : [makeRecon(sectionB, { mud_type: 'OBM', cost_per_bbl: '9', reconciled_cost: '0' })]
    const selected = u.searchParams.get('section_id')
    const rows = selected ? all.filter(row => row.section_id === selected) : all
    const result = { currency: 'USD', sections: rows, rows: [], selected_section_count: rows.length, configured_section_count: rows.length, unconfigured_section_count: 0,
      total_actual_cost: '0', total_reconciled_cost: '0', total_adjustment: '0', to_date: u.searchParams.get('to') || '2026-10-27' }
    if (holdOldKpis && wellId === 'w1' && u.searchParams.get('to') === '9999-12-31') return new Promise(resolve => held.push(() => resolve(json(copy(result)))))
    return json(copy(result))
  }
  return json({})
}

const MudCostAnalysis = (await import('../../frontend/src/pages/MudCostAnalysis')).default
const router = createMemoryRouter([{ path: '/daily-cost/mud-cost-analysis', element: createElement(MudCostAnalysis) }], {
  initialEntries: ['/daily-cost/mud-cost-analysis?rig_id=r1&well_id=w1'],
})
const wait = async (ms = 150) => act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) })
const click = async node => { assert.ok(node, 'button exists'); await act(async () => node.click()); await wait() }
const button = label => [...document.querySelectorAll('button')].find(node => node.textContent.trim() === label)
const selectContaining = text => [...document.querySelectorAll('[role="combobox"]')].find(node => node.textContent.includes(text))
async function choose(select, optionText) {
  assert.ok(select, `select containing ${optionText} exists`)
  await act(async () => select.dispatchEvent(new w.MouseEvent('mousedown', { bubbles: true, cancelable: true })))
  await wait(50)
  const option = [...document.querySelectorAll('[role="option"]')].find(node => node.textContent.includes(optionText))
  assert.ok(option, `option ${optionText} exists`)
  await act(async () => option.dispatchEvent(new w.MouseEvent('click', { bubbles: true })))
  await wait()
}
const setInput = async (el, value) => {
  assert.ok(el, 'input exists')
  await act(async () => {
    Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, 'value').set.call(el, value)
    el.dispatchEvent(new w.Event('input', { bubbles: true }))
    el.dispatchEvent(new w.Event('change', { bubbles: true }))
  })
}
await act(async () => root.render(<ThemeProvider theme={buildTheme('light')}><AuthProvider><RouterProvider router={router}/></AuthProvider></ThemeProvider>))
await wait(400)
assert.equal(metric(card(card1Label), 'Receipt'), '23')
assert.equal(sectionValue(card(rateLabel), 'Intermediate hole'), 'USD 0.00')
const inceptionQueries = () => requests.filter(req => req.path === '/mud-cost/material-balance' && req.query.get('view') === 'inception')
const allRateQueries = () => requests.filter(req => req.path === '/mud-cost/reconciliation' && req.query.get('to') === '9999-12-31')
assert.ok(inceptionQueries().length && allRateQueries().length)
assert.equal(inceptionQueries().at(-1).query.has('section_id'), false)
assert.equal(inceptionQueries().at(-1).query.has('from'), false)
assert.equal(allRateQueries().at(-1).query.get('include_draft'), 'true')
assert.equal(allRateQueries().at(-1).query.has('section_id'), false)

// Entry-section and reconciliation filters change their tables, not the well KPI.
const initialKpiRequests = inceptionQueries().length
await choose(selectContaining('17-1/2 · Surface hole'), '12-1/4 · Intermediate hole')
assert.equal(inceptionQueries().length, initialKpiRequests)
assert.equal(metric(card(card1Label), 'Receipt'), '23')
await click(button('Reconciliation'))
await choose(selectContaining('All sections (shown separately)'), '12-1/4 · Intermediate hole')
assert.equal(inceptionQueries().length, initialKpiRequests)
assert.equal(sectionValue(card(stockLabel), 'Surface hole'), '127.125')
const tabRate = card('Selected reconciliation cost per barrel by section')
assert.equal(sectionValue(tabRate, 'Intermediate hole'), 'USD 0.00')
assert.doesNotMatch(tabRate.textContent, /Surface hole/, 'the tab card follows its selected section')
assert.equal(sectionValue(card(rateLabel), 'Surface hole'), 'USD 2.61', 'the well-wide card stays unfiltered')

// Save a real entry dialog and ensure the well-wide sources reload immediately.
await click(button('Daily Entries'))
await choose(selectContaining('12-1/4 · Intermediate hole'), '17-1/2 · Surface hole')
await click(button('New daily entry'))
await setInput(document.querySelector('input[aria-label="Extra OBM Received quantity"]'), '7')
await click(button('Create entry'))
assert.equal(createdPayload.lines.find(line => line.line_code === 'extra_obm_received').amount, '7')
assert.ok(inceptionQueries().length > initialKpiRequests, 'save reloads the inception KPI source')
assert.equal(metric(card(card1Label), 'Receipt'), '30')
assert.equal(sectionValue(card(stockLabel), 'Surface hole'), '134.125')
assert.equal(sectionValue(card(rateLabel), 'Surface hole'), 'USD 3.25')

// Correcting initial stock and changing the section's mud type both reload the
// summary instead of leaving pre-save stock or pricing on screen.
const editStock = button('Edit opening stock')
assert.ok(editStock, 'the first active grid row exposes opening stock correction')
await click(editStock)
await setInput(document.querySelector('[role="dialog"] input[type="number"]'), '200')
await click(button('Save opening stock'))
assert.equal(correctedOpening.amount, '200')
assert.equal(metric(card(card1Label), 'Opening stock'), '200')
assert.equal(sectionValue(card(stockLabel), 'Surface hole'), '234')
assert.equal(sectionValue(card(rateLabel), 'Surface hole'), 'USD 4.25')
const firstSettingsRow = [...document.querySelectorAll('tbody tr')].find(row => row.textContent.includes('Surface hole') && row.textContent.includes('OBM'))
assert.ok(firstSettingsRow, 'section configuration row is visible')
await click([...firstSettingsRow.querySelectorAll('button')].find(node => node.textContent.trim() === 'Edit'))
await choose(selectContaining('Oil Based Mud'), 'Water Based Mud')
await click(button('Save mud type'))
assert.equal(configuredMudType, 'WBM')
assert.equal(sectionValue(card(rateLabel), 'Surface hole'), 'USD 5.00')
assert.match(card(card1Label).textContent, /WBM/)

// A reconciliation failure leaves balance values visible and explains the rate.
reconFailure = true
await click(button('Refresh'))
assert.match(document.querySelector('#mud-kpi-heading').parentElement.textContent, /Mixed AFE currencies/)
assert.equal(metric(card(card1Label), 'Receipt'), '30')
assert.equal(sectionValue(card(stockLabel), 'Surface hole'), '234')
assert.equal(sectionValue(card(rateLabel), 'Surface hole'), '—')
reconFailure = false

// A slow old-well snapshot cannot leak into the new scope, even after it resolves.
holdOldKpis = true
await click(button('Refresh'))
assert.equal(held.length, 2, 'both old-well KPI calls were delayed')
await choose(selectContaining('W-1 · Well one'), 'W-2 · Well two')
assert.equal(sectionValue(card(stockLabel), 'Second well hole'), '700')
assert.equal(sectionValue(card(rateLabel), 'Second well hole'), 'USD 9.00')
await act(async () => held.forEach(resolve => resolve()))
await wait()
assert.equal(sectionValue(card(stockLabel), 'Second well hole'), '700')
assert.doesNotMatch(card(stockLabel).textContent, /Surface hole/)

await act(async () => root.unmount())
dom.window.close()
console.log('Mud Cost KPI checks passed: section balances, all-section stock/rates, zero and empty states, history, errors, filters, entry/stock/configuration saves, future dates and scope races in light/dark themes.')
process.exit(0)

// Daily Cost shortcut scope regression check.
//
// The daily cost register keeps shortcuts to Mud Cost Analysis, the LIH Cost
// Register and the NDT Inspection Register, and loads with the rig and well the
// user is currently costing. Each shortcut opens its register with that rig and
// well already selected, and every register still lets the user change them.
//
// Run (jsdom is installed by this target):
//   cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/daily-cost-scope-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/daily-cost-scope-check.mjs --external:jsdom && \
//     node node_modules/.cache/daily-cost-scope-check.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement', 'HTMLSelectElement',
]) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
// AG Grid (the shared DataTable) needs these browser observers, and the scope is
// remembered in localStorage, which jsdom provides.
for (const key of ['MutationObserver', 'IntersectionObserver', 'localStorage', 'sessionStorage', 'NodeList', 'HTMLCollection', 'DOMParser', 'SVGElement', 'FocusEvent', 'InputEvent', 'PointerEvent', 'WheelEvent', 'crypto']) {
  if (w[key] !== undefined) Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const {
  readActiveScope, writeActiveScope, requestedScope, resolveRequestedScope, resolveWorkingScope, scopeLink,
} = await import('../../frontend/src/lib/activeScope')

// ---------------------------------------------------------------------------
// 1. The remembered scope is per workspace, trimmed, and never fatal.
// ---------------------------------------------------------------------------
assert.deepEqual(readActiveScope('unit-a'), { rigId: '', wellId: '' }, 'nothing is remembered before the first visit')
writeActiveScope({ rigId: ' rig-1 ', wellId: 'well-1' }, 'unit-a')
assert.deepEqual(readActiveScope('unit-a'), { rigId: 'rig-1', wellId: 'well-1' }, 'the chosen rig and well are remembered')
assert.deepEqual(readActiveScope('unit-b'), { rigId: '', wellId: '' }, "a second workspace never inherits another workspace's scope")
writeActiveScope({ rigId: '', wellId: '' }, 'unit-a')
assert.deepEqual(readActiveScope('unit-a'), { rigId: 'rig-1', wellId: 'well-1' }, 'an empty scope never clears the remembered one')
w.localStorage.setItem('wcp.active-scope:unit-a', '{not json')
assert.deepEqual(readActiveScope('unit-a'), { rigId: '', wellId: '' }, 'a corrupt stored value falls back to no scope')

// ---------------------------------------------------------------------------
// 2. Shortcut links carry the scope; malformed query strings are ignored.
// ---------------------------------------------------------------------------
assert.equal(scopeLink('/daily-cost/mud-cost-analysis', { rigId: 'rig-1', wellId: 'well-1' }),
  '/daily-cost/mud-cost-analysis?rig_id=rig-1&well_id=well-1')
assert.equal(scopeLink('/daily-cost/lih-register?tab=final', { rigId: 'rig-1', wellId: 'well-1' }),
  '/daily-cost/lih-register?tab=final&rig_id=rig-1&well_id=well-1', 'an existing query string is extended, not replaced')
assert.equal(scopeLink('/daily-cost/ndt-inspections', { rigId: '', wellId: '' }), '/daily-cost/ndt-inspections',
  'an empty scope leaves the link untouched')
assert.deepEqual(requestedScope('?rig_id=rig-1&well_id=well-1'), { rigId: 'rig-1', wellId: 'well-1' })
assert.deepEqual(requestedScope('?well_id=%20well-1%20'), { rigId: '', wellId: 'well-1' }, 'ids are trimmed')
assert.deepEqual(requestedScope(''), { rigId: '', wellId: '' }, 'a plain visit requests no scope')

// ---------------------------------------------------------------------------
// 3. A register adopts only a scope it can actually use, and defaults to the
//    current rig and well when its own reference data is available.
// ---------------------------------------------------------------------------
const rigs = [{ id: 'rig-1' }, { id: 'rig-2' }]
const wells = [{ id: 'well-1', rig_id: 'rig-1' }, { id: 'well-2', rig_id: 'rig-2' }]
assert.deepEqual(resolveRequestedScope({ rigId: 'rig-2', wellId: 'well-1' }, wells, rigs), { rigId: 'rig-1', wellId: 'well-1' },
  'the well wins, so a register never opens on a rig that does not own the well')
assert.deepEqual(resolveRequestedScope({ rigId: 'rig-2', wellId: '' }, wells, rigs), { rigId: 'rig-2', wellId: '' },
  'a rig-only link selects the rig and lets the page pick its well')
assert.deepEqual(resolveRequestedScope({ rigId: 'gone', wellId: 'gone' }, wells, rigs), { rigId: '', wellId: '' },
  'a scope that no longer exists is ignored instead of pointing at deleted data')
assert.deepEqual(resolveWorkingScope({ rigId: 'rig-1', wellId: 'well-1' }, wells, rigs, ['well-2']),
  { rigId: 'rig-1', wellId: 'well-1' }, 'the current rig and well load as the register default')
assert.deepEqual(resolveWorkingScope({ rigId: '', wellId: 'deleted-well' }, wells, rigs, ['well-2']),
  { rigId: 'rig-2', wellId: 'well-2' }, 'a well that no longer exists falls back to the preferred well')
assert.deepEqual(resolveWorkingScope({ rigId: 'gone', wellId: '' }, wells, rigs, []),
  { rigId: 'rig-1', wellId: 'well-1' }, 'without a preference the first available well starts the register')
assert.deepEqual(resolveWorkingScope({ rigId: 'rig-2', wellId: '' }, [], rigs, []), { rigId: 'rig-2', wellId: '' },
  'with no wells at all the rig is still kept')
assert.deepEqual(resolveWorkingScope({ rigId: 'gone', wellId: '' }, [], [], []), { rigId: '', wellId: '' },
  'an empty workspace resolves to no scope')

// ---------------------------------------------------------------------------
// 4. Render the real pages against a stubbed API.
// ---------------------------------------------------------------------------
const apiRigs = [
  { id: 'rig-1', rig_code: 'RIG-1', rig_name: 'Rig one', display_name: 'RIG-1 · Rig one', is_deleted: false },
  { id: 'rig-2', rig_code: 'RIG-2', rig_name: 'Rig two', display_name: 'RIG-2 · Rig two', is_deleted: false },
]
const apiWells = [
  { id: 'well-1', rig_id: 'rig-1', well_code: 'W-1', well_name: 'Well one', display_name: 'W-1 · Well one', status: 'active', config_status: 'configured', completion_status: 'active', completion_config_status: 'configured', is_deleted: false, drilling_available: true, completion_available: true, sections: [] },
  { id: 'well-2', rig_id: 'rig-2', well_code: 'W-2', well_name: 'Well two', display_name: 'W-2 · Well two', status: 'active', config_status: 'configured', completion_status: 'active', completion_config_status: 'configured', is_deleted: false, drilling_available: true, completion_available: true, sections: [] },
]
const apiAfes = [{ id: 'afe-1', well_id: 'well-1', afe_code: 'AFE-1', afe_name: 'Drilling', afe_type: 'drilling', status: 'approved', configuration_scope: 'drilling', standard_currency: 'USD', total_cost: '1000', estimate_saved_at: '2026-10-01', display_name: 'AFE-1 — Drilling' }]
const dailyReference = {
  rigs: apiRigs, wells: apiWells, afes: apiAfes, activities: [], sub_activities: [], services: [], catalogue_items: [],
  vendors: [], currencies: ['USD'], charge_categories: [], charge_bases: [], quantity_units: [], classifications: [],
  consumable_categories: [], other_expense_types: [],
}
const requests = []
globalThis.fetch = async (url, init = {}) => {
  const path = String(url)
  requests.push(`${init.method ?? 'GET'} ${path.replace('/api/v1', '')}`)
  const json = body => ({ ok: true, status: 200, json: async () => body })
  if (path.endsWith('/auth/refresh')) return json({ access_token: 'token' })
  if (path.endsWith('/auth/me')) {
    return json({ id: 'u1', email: 'owner@example.com', name: 'Owner', is_active: true, is_owner: true, permission_keys: [], organization_slug: 'acme', organization_name: 'Acme' })
  }
  if (path.endsWith('/mud-cost/reference')) return json({ rigs: apiRigs, wells: apiWells })
  if (path.includes('/mud-cost/material-balance')) return json({ view: 'section', rows: [] })
  if (path.includes('/mud-cost/section-settings')) return json([])
  if (path.includes('/mud-cost/reconciliation')) return json({ currency: 'USD', sections: [] })
  if (path.includes('/mud-cost/entries')) return json([])
  if (path.endsWith('/lih-cost/reference')) return json({ rigs: apiRigs, wells: apiWells, afes: apiAfes, uoms: [], default_currency: 'USD', previous_items: [] })
  if (path.includes('/lih-cost/day')) return json(null)
  if (path.includes('/lih-cost/entries')) return json([])
  if (path.endsWith('/ndt-inspections/reference')) return json({ rigs: apiRigs, wells: apiWells })
  if (path.includes('/ndt-inspections/entries')) return json([])
  if (path.includes('/daily-cost/entries')) return json([])
  if (path.includes('/daily-cost/reference')) return json(dailyReference)
  return json({})
}

// The registers render their selects before their reference data arrives and the
// AG Grid inside DataTable updates outside React's act() scope; both only add
// development warnings to an otherwise passing check.
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
const { createMemoryRouter, RouterProvider } = await import('react-router-dom')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')

let root = null
async function renderAt(path, Page) {
  if (root) { await act(async () => root.unmount()); root = null }
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root'))
  const router = createMemoryRouter([{ path: path.split('?')[0], element: createElement(Page) }], { initialEntries: [path] })
  await act(async () => { root.render(createElement(AuthProvider, null, createElement(RouterProvider, { router }))) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 300)) })
}
const selectText = scope => [...scope.querySelectorAll('.MuiSelect-select')].map(element => element.textContent)
const buttonWith = (text, scope = document) => [...scope.querySelectorAll('button')].find(button => button.textContent.includes(text))

/** Open a MUI select and pick an option by its visible text, like a user would. */
async function chooseOption(select, optionText) {
  await act(async () => { select.dispatchEvent(new w.MouseEvent('mousedown', { bubbles: true, cancelable: true })) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 60)) })
  const option = [...document.querySelectorAll('[role="option"]')].find(item => item.textContent.includes(optionText))
  assert.ok(option, `the selector offers ${optionText}`)
  await act(async () => { option.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 120)) })
}
const shortcutHrefs = () => [...document.querySelector('[data-testid="daily-cost-working-scope"]').querySelectorAll('a')]
  .map(anchor => anchor.getAttribute('href'))

// 4a. The daily cost register loads the current rig and well and offers the shortcuts.
w.localStorage.setItem('wcp.active-scope:acme', JSON.stringify({ rigId: 'rig-2', wellId: 'well-2' }))
const DailyCostManagement = (await import('../../frontend/src/pages/DailyCostManagement')).default
await renderAt('/daily-cost', DailyCostManagement)
const scopeBar = document.querySelector('[data-testid="daily-cost-working-scope"]')
assert.ok(scopeBar, 'the register shows a working scope strip')
assert.deepEqual(selectText(scopeBar), ['RIG-2 · Rig two', 'W-2 · Well two'],
  'the register loads defaults with the current rig and well')
const shortcuts = [...scopeBar.querySelectorAll('a')].map(anchor => anchor.getAttribute('href'))
assert.deepEqual(shortcuts, [
  '/daily-cost/mud-cost-analysis?rig_id=rig-2&well_id=well-2',
  '/daily-cost/lih-register?rig_id=rig-2&well_id=well-2',
  '/daily-cost/ndt-inspections?rig_id=rig-2&well_id=well-2',
], 'the Mud cost, LIH and NDT shortcuts open on the current rig and well')
assert.deepEqual([...scopeBar.querySelectorAll('a')].map(anchor => anchor.textContent),
  ['Mud cost analysis', 'LIH Cost Register', 'NDT Inspection Register'], 'all three shortcuts stay on the register')
assert.ok(scopeBar.textContent.includes('Open on RIG-2 · Rig two · W-2 · Well two'),
  'the register states the scope the shortcuts will use')

// The shortcuts follow a change made in the register itself.
await chooseOption(scopeBar.querySelectorAll('.MuiSelect-select')[0], 'RIG-1 · Rig one')
assert.deepEqual(shortcutHrefs(), [
  '/daily-cost/mud-cost-analysis?rig_id=rig-1&well_id=well-1',
  '/daily-cost/lih-register?rig_id=rig-1&well_id=well-1',
  '/daily-cost/ndt-inspections?rig_id=rig-1&well_id=well-1',
], 'changing the rig moves the well and re-points every shortcut at the new scope')
assert.deepEqual(readActiveScope('acme'), { rigId: 'rig-1', wellId: 'well-1' },
  'the register remembers the changed scope for the next visit')

// A new daily sheet starts on the current well.
const newSheet = buttonWith('New daily sheet')
assert.ok(newSheet, 'the register offers a new daily sheet')
await act(async () => { newSheet.click() })
await act(async () => { await new Promise(resolve => setTimeout(resolve, 200)) })
const dialog = document.querySelector('[role="dialog"]')
assert.ok(dialog, 'the new daily sheet dialog opens')
assert.equal(selectText(dialog)[0], 'W-1 · Well one — RIG-1', 'a new daily sheet defaults to the current well')

// 4b. Mud Cost Analysis opens on the scope its shortcut carried.
const MudCostAnalysis = (await import('../../frontend/src/pages/MudCostAnalysis')).default
requests.length = 0
await renderAt('/daily-cost/mud-cost-analysis?rig_id=rig-2&well_id=well-2', MudCostAnalysis)
assert.deepEqual(selectText(document).slice(0, 2), ['RIG-2 · Rig two', 'W-2 · Well two'],
  'Mud Cost Analysis loads with the shortcut rig and well selected')
assert.ok(requests.some(request => request === 'GET /mud-cost/entries?rig_id=rig-2&well_id=well-2'),
  'Mud Cost Analysis loads the carried well, not its own first well')
assert.ok(requests.some(request => request.startsWith('GET /mud-cost/reconciliation?rig_id=rig-2&well_id=well-2')),
  'Mud Cost Analysis reconciles the carried well')
assert.deepEqual(readActiveScope('acme'), { rigId: 'rig-2', wellId: 'well-2' },
  'opening Mud Cost Analysis makes its rig and well the current scope')

// 4c. The LIH Cost Register opens on the scope its shortcut carried.
const LihCostRegister = (await import('../../frontend/src/pages/LihCostRegister')).default
requests.length = 0
await renderAt('/daily-cost/lih-register?rig_id=rig-1&well_id=well-1', LihCostRegister)
assert.deepEqual(selectText(document).slice(0, 2), ['RIG-1 · Rig one', 'W-1 · Well one'],
  'the LIH register loads with the shortcut rig and well selected')
assert.ok(requests.some(request => request.startsWith('GET /lih-cost/day?well_id=well-1')),
  'the LIH register loads that well’s day instead of asking for a rig and well')
assert.ok(buttonWith('Add items'), 'the LIH register can still start a worksheet for the selected day')

// 4d. The NDT Inspection Register opens on the scope its shortcut carried.
const NdtInspectionRegister = (await import('../../frontend/src/pages/NdtInspectionRegister')).default
requests.length = 0
await renderAt('/daily-cost/ndt-inspections?rig_id=rig-2&well_id=well-2', NdtInspectionRegister)
assert.deepEqual(selectText(document).slice(0, 2), ['RIG-2 · Rig two', 'W-2 · Well two'],
  'the NDT register filters to the shortcut rig and well')
assert.ok(requests.some(request => request === 'GET /ndt-inspections/entries?rig_id=rig-2&well_id=well-2'),
  'the NDT register lists the carried well’s inspections')
requests.length = 0
await chooseOption([...document.querySelectorAll('.MuiSelect-select')][0], 'RIG-1 · Rig one')
assert.ok(requests.some(request => request === 'GET /ndt-inspections/entries?rig_id=rig-1'),
  'the NDT register still lets the user change the rig and re-queries the register')
assert.equal(readActiveScope('acme').rigId, 'rig-1',
  'changing the NDT rig makes it the current scope for the rest of the module')

await act(async () => root.unmount())
root = null

// ---------------------------------------------------------------------------
// 5. Source wiring: the register keeps the three shortcut targets and its row
//    opens hand their well back to the scope; the daily sheet links its own well.
// ---------------------------------------------------------------------------
const read = path => readFileSync(`../frontend/src/pages/${path}`, 'utf8')
const register = read('DailyCostManagement.tsx')
for (const path of ['/daily-cost/mud-cost-analysis', '/daily-cost/lih-register', '/daily-cost/ndt-inspections']) {
  assert.ok(register.includes(`path: '${path}'`), `the daily cost register keeps a shortcut to ${path}`)
}
assert.ok(register.includes('onClick={() => rememberRowScope(record)}'), 'opening a sheet makes its well the current scope')
assert.ok(read('DailyCostSheet.tsx').includes("scopeLink('/daily-cost/lih-register', { rigId: entry.rig_id, wellId: entry.well_id })"),
  'the daily sheet opens the LIH register on its own rig and well')

w.close()
console.log('Daily cost shortcut scope check: all assertions passed')
// jsdom's visual mode keeps a frame loop alive; a check script should still exit.
process.exit(0)

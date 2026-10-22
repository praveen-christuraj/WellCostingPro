// Run from frontend with jsdom installed (--no-save):
// NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/mud-cost-check.jsx \
//   --bundle --platform=node --format=esm --jsx=automatic --external:jsdom \
//   --outfile=node_modules/.cache/mud-cost-check.mjs && node node_modules/.cache/mud-cost-check.mjs
import { JSDOM } from 'jsdom'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = q => ({ matches: false, media: q, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment', 'ShadowRoot', 'MouseEvent', 'KeyboardEvent', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement']) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { ThemeProvider } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const { MudCostEntryDialog } = await import('../../frontend/src/components/mud-cost/MudCostEntryDialog')
const { MudCostPrintSheet } = await import('../../frontend/src/components/mud-cost/MudCostPrintSheet')
const { MUD_COST_IMPORT_OPTIONAL_HEADERS } = await import('../../frontend/src/lib/mudCost')
const root = createRoot(document.getElementById('root'))
const rig = { id: 'rig', display_name: 'Rig' }
const well = { id: 'well', display_name: 'Well' }
const section = { id: 'section', display_name: 'Section', is_current: true }
const first = {
  id: 'first', rig_id: rig.id, well_id: well.id, section_id: section.id,
  entry_date: '2026-10-15', opening_stock: '100', opening_stock_remarks: '', closing_stock: '125',
  lines: [{ line_code: 'opening_stock', amount: '100', remarks: '' }, { line_code: 'extra_obm_received', amount: '25', remarks: '' }],
}
let saved
const base = { open: true, onClose() {}, onSave: async payload => { saved = payload }, rig, well, section, entry: null, entries: [], existingRows: [], saving: false, error: '' }
let renderKey = 0
async function show(mode, props) {
  await act(async () => root.render(<ThemeProvider theme={buildTheme(mode)}><MudCostEntryDialog key={++renderKey} {...base} {...props}/></ThemeProvider>))
}
function input(label) { return document.querySelector(`input[aria-label="${label}"]`) }
async function setValue(element, value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, 'value').set.call(element, value)
    element.dispatchEvent(new w.Event('input', { bubbles: true }))
    element.dispatchEvent(new w.Event('change', { bubbles: true }))
  })
}
async function save(label) {
  const button = [...document.querySelectorAll('button')].find(b => b.textContent === label)
  assert.ok(button && !button.disabled)
  await act(async () => button.click())
}
for (const mode of ['light', 'dark']) {
  await show(mode, {})
  assert.equal(input('Opening Stock quantity').disabled, false)
  assert.equal(input('Actual Closing Stock quantity'), null)
  assert.ok(!document.body.textContent.includes('Variance'))
  await setValue(document.querySelector('input[type="date"]'), '2026-10-15')
  await setValue(input('Opening Stock quantity'), '100')
  await setValue(input('Extra OBM Received quantity'), '25')
  await save('Create entry')
  assert.equal(saved.lines.find(line => line.line_code === 'opening_stock').amount, '100')
  assert.equal(saved.lines.find(line => line.line_code === 'extra_obm_received').amount, '25')
  assert.ok(saved.lines.every(line => line.remarks === ''))
  assert.ok(saved.lines.every(line => line.line_code !== 'actual_closing_stock'))

  await show(mode, { entries: [first], existingRows: [first] })
  await setValue(document.querySelector('input[type="date"]'), '2026-10-17')
  assert.equal(input('Opening Stock quantity'), null, 'later days do not expose opening-stock data entry')
  assert.equal(input('Opening Stock remarks'), null, 'later days do not expose opening-stock remarks')
  assert.match(document.body.textContent, /carried forward from the calculated closing stock/)
  assert.match(document.body.textContent, /125/)
  await save('Create entry')
  assert.equal(saved.lines.find(line => line.line_code === 'opening_stock').amount, null)
  await setValue(document.querySelector('input[type="date"]'), '2026-10-14')
  assert.equal(input('Opening Stock quantity'), null, 'backdated days cannot seed another opening stock')
  assert.match(document.body.textContent, /already has its initial opening stock/)

  await show(mode, { entry: first, entries: [first], existingRows: [first] })
  assert.equal(input('Opening Stock quantity'), null, 'the ordinary editor cannot overwrite initial stock')
  assert.match(document.body.textContent, /use Edit opening stock on the first active entry/)
  await save('Save entry')

  await show(mode, { section: { ...section, id: 'other' }, entries: [first] })
  assert.equal(input('Opening Stock quantity').disabled, false)
  console.log(`PASS ${mode}: one-time opening entry, optional remarks, hidden later-date inputs, carry-forward, backdating lock and section isolation`)
}
assert.ok(!MUD_COST_IMPORT_OPTIONAL_HEADERS.some(h => /closing|variance/.test(h)))
await act(async () => root.render(<MudCostPrintSheet report={{ rig: 'Rig', well: 'Well', section: 'Section', view: 'Daily', period: 'October', entryCount: 1, sectionCount: 1, rows: [{ ...first, period_label: '2026-10-15', receipt: '25', additions: '0', consumption_losses: '0', others: '0' }] }}/>))
assert.match(document.body.textContent, /Closing stock/)
assert.ok(!/Book closing|Actual closing|Variance/.test(document.body.textContent))
const layout = readFileSync('../frontend/src/components/Layout.tsx', 'utf8')
const analysis = readFileSync('../frontend/src/pages/MudCostAnalysis.tsx', 'utf8')
assert.ok(analysis.includes('initialEntryIds.has(record.id)') && analysis.includes('Edit opening stock'), 'only the first active section row exposes the correction action')
assert.ok(layout.indexOf("label: 'Daily cost register'") < layout.indexOf("label: 'Mud Cost Analysis'"))
assert.ok(layout.indexOf("label: 'Mud Cost Analysis'") < layout.indexOf("label: 'Well cost analysis'"))
await act(async () => root.unmount())
console.log('PASS import template, print output and navigation order')
dom.window.close()
process.exit(0)

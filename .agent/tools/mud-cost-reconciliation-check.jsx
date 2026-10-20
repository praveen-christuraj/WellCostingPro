// Run from frontend with jsdom installed (--no-save):
// NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/mud-cost-reconciliation-check.jsx \
//   --bundle --platform=node --format=esm --jsx=automatic --external:jsdom \
//   --outfile=node_modules/.cache/mud-cost-reconciliation-check.mjs && node node_modules/.cache/mud-cost-reconciliation-check.mjs
import { JSDOM } from 'jsdom'
import assert from 'node:assert/strict'

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
const { MudCostSectionSettingsDialog } = await import('../../frontend/src/components/mud-cost/MudCostSectionSettingsDialog')

const root = createRoot(document.getElementById('root'))
let saved = null
let rejectWith = null
let renders = 0
const row = {
  id: 'setting-1', rig_id: 'rig-1', rig_code: 'RIG-01', well_id: 'well-1', well_code: 'WELL-01',
  section_id: 'section-1', hole_section_id: 'hole-1', section_scope: 'drilling',
  section_code: '12-1/4', section_name: 'Intermediate hole',
  section_label: '12-1/4 · Intermediate hole · Drilling · 0–1000',
  display_name: '12-1/4 · Intermediate hole · Drilling · 0–1000',
  mud_type: 'OBM', mud_type_label: 'Oil Based Mud', remarks: 'Synthetic system',
  base_rate: '15.0000000000', currency: 'USD', is_configured: true, is_current: true,
  created_by: '', updated_by: '', created_at: null, updated_at: null,
}

async function show(mode, props) {
  renders += 1
  await act(async () => root.render(<ThemeProvider theme={buildTheme(mode)}>
    <MudCostSectionSettingsDialog key={renders} onClose={() => {}} {...props}/>
  </ThemeProvider>))
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
function textField(label) {
  return [...document.querySelectorAll('label')].find(node => node.textContent?.startsWith(label))?.htmlFor
}
function field(label) {
  const id = textField(label)
  return id ? document.getElementById(id) : null
}
function combo() { return document.querySelector('[role="combobox"]') }
function option(value) { return document.querySelector(`li[data-value="${value}"]`) }
async function chooseMudType(value) {
  const select = combo()
  assert.ok(select, 'mud type select exists')
  await act(async () => {
    select.dispatchEvent(new w.MouseEvent('mousedown', { bubbles: true }))
    select.dispatchEvent(new w.MouseEvent('mouseup', { bubbles: true }))
  })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
  const item = option(value)
  assert.ok(item, `mud type option ${value} rendered`)
  await act(async () => { item.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
async function setValue(element, value) {
  assert.ok(element, 'field to type into exists')
  const prototype = element.tagName === 'TEXTAREA' ? w.HTMLTextAreaElement.prototype : w.HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value)
    element.dispatchEvent(new w.Event('input', { bubbles: true }))
    element.dispatchEvent(new w.Event('change', { bubbles: true }))
  })
}
async function save() {
  const button = [...document.querySelectorAll('button')].find(node => node.textContent === 'Save mud type')
  assert.ok(button && !button.disabled, 'Save mud type is available')
  await act(async () => button.click())
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
}
function text() { return document.body.textContent ?? '' }
const onSave = async payload => {
  if (rejectWith) throw rejectWith
  saved = payload
}

for (const mode of ['light', 'dark']) {
  saved = null
  rejectWith = null
  await show(mode, { row, onSave })

  // An existing configuration opens with its saved values.
  assert.match(combo().textContent ?? '', /Oil Based Mud/)
  assert.equal(document.querySelector('input[type="number"]').value, '15.0000000000')
  assert.equal(document.querySelector('textarea').value, 'Synthetic system')
  assert.match(text(), /Saved in USD/)

  // WBM needs no rate: the field is disabled and cleared, then saved as null.
  await chooseMudType('WBM')
  assert.equal(document.querySelector('input[type="number"]').disabled, true)
  assert.equal(document.querySelector('input[type="number"]').value, '')
  await save()
  assert.equal(saved.mud_type, 'WBM')
  assert.equal(saved.base_rate, null)
  assert.equal(saved.section_id, 'section-1')
  assert.equal(saved.well_id, 'well-1')

  // OTHERS refuses to save without remarks and says why, next to the fields.
  saved = null
  await show(mode, { row, onSave })
  await chooseMudType('OTHERS')
  await setValue(document.querySelector('textarea'), '')
  await setValue(document.querySelector('input[type="number"]'), '22.5')
  await save()
  assert.equal(saved, null, 'OTHERS without remarks never reaches the API')
  assert.match(text(), /Remarks are mandatory when the mud type is OTHERS/)

  // Once the remark is entered, the trimmed payload is saved.
  await setValue(document.querySelector('textarea'), '  Calcium chloride polymer system  ')
  await save()
  assert.equal(saved.mud_type, 'OTHERS')
  assert.equal(saved.remarks, 'Calcium chloride polymer system')
  assert.equal(saved.base_rate, '22.5')

  // A non-WBM type needs a positive Cost/BBL base rate.
  saved = null
  await show(mode, { row, onSave })
  await setValue(document.querySelector('input[type="number"]'), '0')
  await save()
  assert.equal(saved, null, 'a zero base rate never reaches the API')
  assert.match(text(), /Enter a positive Cost\/BBL base rate/)

  // API failures stay in the dialog instead of closing it.
  rejectWith = new Error('This well has daily cost sheets in different standard currencies.')
  await setValue(document.querySelector('input[type="number"]'), '9')
  await save()
  assert.match(text(), /different standard currencies/)
  assert.ok(document.querySelector('[role="dialog"]'), 'dialog stays open after a failed save')
  rejectWith = null
}

console.log('Mud cost reconciliation checks passed: WBM rate lock, OTHERS remark rule, positive rate rule, trimmed payload and in-dialog API errors.')
dom.window.close()
process.exit(0)

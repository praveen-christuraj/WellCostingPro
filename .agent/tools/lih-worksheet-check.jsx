// LIH worksheet regression check: bulk multi-row entry, duplicate, paste,
// keyboard movement, suggestions, validation and the single-save payload.
//
// Run (jsdom is installed by `make ui-check`, or by this target):
//   cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/lih-worksheet-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/lih-worksheet-check.mjs --external:jsdom && \
//     node node_modules/.cache/lih-worksheet-check.mjs
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLInputElement', 'HTMLSelectElement',
]) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { act, useState, createElement } = await import('react')
const { createRoot } = await import('react-dom/client')
const { LihWorksheet } = await import('../../frontend/src/components/lih-cost/LihWorksheet')
const {
  blankDraftRow, draftRowFromSavedLine, lihDayPayloadLines, lihLineTotal, rowHasChanged, rowIsBlank, rowState, validateDraft,
} = await import('../../frontend/src/lib/lihCost')

const UOMS = [{ code: 'EA', name: 'Each', symbol: 'ea', display_name: 'EA · Each (ea)' }]
const SUGGESTIONS = [{
  item_description: '6 5/8 in drill collar', od_size: '6.6250000000', id_size: '2.8125000000',
  fish_neck_od: '4.5000000000', fish_neck_length: '24.0000000000', connection: 'NC50',
  length: '9.5000000000', unit: 'EA', unit_cost: '1250.5000000000',
}]
const SAVED_LINE = {
  id: 'line-1', item_description: 'Drill collar', od_size: '6.625', id_size: null, fish_neck_od: null,
  fish_neck_length: null, serial_number: 'DC-1', connection: 'NC50', length: '9.5', no_of_units: '2.0000000000',
  unit: 'EA', unit_cost: '1000.0000000000', total_cost: '2000.00', remarks: '', source: 'manual',
  sort_order: 0, created_at: '2026-10-20T10:00:00Z', updated_at: '2026-10-20T10:00:00Z',
}

const rootElement = document.getElementById('root')
const root = createRoot(rootElement)
let savedCalls = 0

function Harness({ initial, canEdit = true, removedCount = 0, savedCount = 0 }) {
  const [rows, setRows] = useState(initial)
  const dirty = rows.some(rowHasChanged)
  return createElement(LihWorksheet, {
    rows,
    onRowsChange: setRows,
    currency: 'USD',
    uoms: UOMS,
    suggestions: SUGGESTIONS,
    removedCount,
    canEdit,
    canImport: true,
    canExport: true,
    saving: false,
    dirty,
    saveError: '',
    onSave: () => { savedCalls += 1 },
    onDiscard: () => setRows([blankDraftRow()]),
    onImport: () => {},
    onExportSheet: () => {},
    savedCount,
    autoFocus: false,
  })
}

const render = async element => { await act(async () => { root.render(element) }) }
const fields = () => [...rootElement.querySelectorAll('.lih-sheet tbody [data-row-key]')]
const rowsInDom = () => [...rootElement.querySelectorAll('.lih-sheet tbody tr.lih-row')]
const cell = (rowIndex, columnIndex) => rootElement.querySelector(
  `.lih-sheet tbody tr.lih-row:nth-child(${rowIndex + 1}) [data-col-index="${columnIndex}"]`,
)
const type = async (input, value) => {
  const setter = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, 'value').set
  await act(async () => {
    setter.call(input, value)
    input.dispatchEvent(new w.Event('input', { bubbles: true }))
  })
}
const key = async (input, keyValue, options = {}) => {
  await act(async () => {
    input.dispatchEvent(new w.KeyboardEvent('keydown', { key: keyValue, bubbles: true, cancelable: true, ...options }))
  })
}
const paste = async (input, text) => {
  await act(async () => {
    const event = new w.Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { getData: () => text } })
    input.dispatchEvent(event)
  })
}

// ---------------------------------------------------------------------------
// 1. The sheet is the entry surface: many columns, one row to start, one save.
// ---------------------------------------------------------------------------
await render(createElement(Harness, { initial: [blankDraftRow()] }))
assert.ok(rootElement.querySelector('.lih-sheet table'), 'worksheet table renders')
assert.equal(fields().length, 12, 'twelve editable item fields per row')
assert.equal(rowsInDom().length, 1, 'a new LIH day starts with one blank row')
assert.equal(rootElement.querySelectorAll('.lih-sheet thead th').length, 16, 'checkbox, row number, twelve fields and total/actions')
const saveButton = [...rootElement.querySelectorAll('button')].find(button => button.textContent.includes('Save all items'))
assert.ok(saveButton, 'one save action for the whole sheet')
const exportButton = [...rootElement.querySelectorAll('button')].find(button => button.textContent.includes('Export sheet'))
assert.ok(exportButton && exportButton.getAttribute('aria-haspopup') === 'menu', 'the sheet keeps standard CSV/XLSX/PDF export access')
const importButton = [...rootElement.querySelectorAll('button')].find(button => button.textContent.includes('Import items'))
assert.ok(importButton, 'the sheet keeps the bulk import action beside it')
assert.equal(saveButton.disabled, true, 'saving is only possible when the sheet is dirty')

// ---------------------------------------------------------------------------
// 2. Typing fills the row; the line and sheet totals are computed live.
// ---------------------------------------------------------------------------
await type(cell(0, 0), '6 5/8 in drill collar')
await type(cell(0, 8), '2')
await type(cell(0, 10), '1250.50')
const totalCell = rowsInDom()[0].querySelector('.lih-sheet__total')
assert.match(totalCell.textContent, /2,501\.00/, 'line total is units × unit cost')
assert.match(rootElement.querySelector('.lih-sheet tfoot').textContent, /2,501\.00/, 'sheet total follows the rows')
assert.equal(saveButton.disabled, false, 'the save action enables as soon as an item is entered')

// ---------------------------------------------------------------------------
// 3. Add row / duplicate / Enter-at-the-end: many items before one save.
// ---------------------------------------------------------------------------
const addRowButton = [...rootElement.querySelectorAll('.lih-worksheet__tools button')].find(button => button.textContent.includes('Add row'))
await act(async () => { addRowButton.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
assert.equal(rowsInDom().length, 2, 'Add row appends an item to the same sheet')
assert.equal(w.document.activeElement, cell(1, 0), 'the new row focuses its first field')

await type(cell(1, 0), 'Stabilizer')
await type(cell(1, 8), '3')
await type(cell(1, 10), '99.99')
const duplicateButton = [...rootElement.querySelectorAll('button')].find(button => button.textContent.includes('Duplicate row'))
await act(async () => { duplicateButton.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
assert.equal(rowsInDom().length, 3, 'Duplicate row adds a similar item in one click')
assert.equal(cell(2, 0).value, 'Stabilizer', 'the duplicate keeps the item values for editing only what differs')
assert.equal(cell(2, 10).value, '99.99')
assert.match(rowsInDom()[2].textContent, /NEW/, 'the duplicate is marked as a new, unsaved item')

// Enter on the last row adds the next item and keeps the keyboard flow.
await key(cell(2, 10), 'Enter')
assert.equal(rowsInDom().length, 4, 'Enter on the last row starts the next item')
await key(cell(3, 0), 'Enter', { ctrlKey: true })
assert.equal(rowsInDom().length, 5, 'Ctrl+Enter adds an item from anywhere on the sheet')
await key(cell(4, 0), 'd', { ctrlKey: true })
assert.equal(rowsInDom().length, 6, 'Ctrl+D duplicates the current row')

// Tab and Alt+arrows move between cells instead of leaving the grid.
await key(cell(0, 0), 'Tab')
assert.equal(w.document.activeElement, cell(0, 1), 'Tab moves to the next field')
await key(cell(0, 1), 'ArrowDown', { altKey: true })
assert.equal(w.document.activeElement, cell(1, 1), 'Alt+Arrow moves down a row')

// ---------------------------------------------------------------------------
// 4. A block copied from Excel pastes straight into the grid.
// ---------------------------------------------------------------------------
await render(createElement(Harness, { key: 'paste', initial: [blankDraftRow()] }))
await paste(cell(0, 0), [
  'Jar\t8\t3\t\t\tNC50\t9.5\tJ-1\t1\tEA\t700\tLeft in hole',
  'Bit sub\t4\t2\t\t\t\t3\tBS-2\t2\tEA\t450\tSpare',
].join('\n') + '\n')
assert.equal(rowsInDom().length, 2, 'a pasted two-row block creates two items')
assert.equal(cell(0, 0).value, 'Jar')
assert.equal(cell(0, 1).value, '8', 'pasted columns land in the matching fields')
assert.equal(cell(0, 5).value, 'NC50')
assert.equal(cell(0, 9).value, 'EA')
assert.equal(cell(1, 0).value, 'Bit sub', 'the second pasted row lands on a new item row')
assert.equal(cell(1, 10).value, '450')
assert.equal(rowsInDom()[1].querySelector('.lih-sheet__total').textContent.includes('900.00'), true)

// ---------------------------------------------------------------------------
// 5. A previously used item fills the equipment details on blur.
// ---------------------------------------------------------------------------
await render(createElement(Harness, { key: 'suggestion', initial: [blankDraftRow()] }))
await type(cell(0, 0), '6 5/8 in drill collar')
await act(async () => {
  cell(0, 0).dispatchEvent(new w.FocusEvent('focusout', { bubbles: true }))
})
assert.equal(cell(0, 1).value, '6.625', 'OD comes from the previously used item')
assert.equal(cell(0, 10).value, '1250.5', 'unit cost comes from the previously used item')
assert.equal(cell(0, 9).value, 'EA', 'UOM comes from the previously used item')
assert.equal(cell(0, 7).value === 'DC-1', false, 'a serial number is never copied from another item')

// ---------------------------------------------------------------------------
// 6. Validation is row-level and complete before the single save.
// ---------------------------------------------------------------------------
const incomplete = [blankDraftRow(), draftRowFromSavedLine(SAVED_LINE)]
incomplete[0].values.item_description = 'Drill pipe'
incomplete[0].values.no_of_units = ''
incomplete[0].values.unit_cost = ''
const problems = validateDraft(incomplete)
assert.equal(problems.length, 1, 'blank rows are ignored, incomplete rows are reported')
assert.equal(problems[0].row, 1)
assert.match(problems[0].message, /No of units/, 'the first problem names the responsible field')
assert.ok(validateDraft([blankDraftRow()]).length === 0, 'a pristine blank row never blocks a save')
assert.equal(rowIsBlank(blankDraftRow().values), true)

// ---------------------------------------------------------------------------
// 7. One save carries the whole sheet; only changed rows are re-sent.
// ---------------------------------------------------------------------------
const draftRows = [
  draftRowFromSavedLine(SAVED_LINE),
  blankDraftRow(),
  blankDraftRow(),
]
draftRows[0].values.unit_cost = '1100'
draftRows[1].values.item_description = 'Jar'
draftRows[1].values.no_of_units = '1'
draftRows[1].values.unit_cost = '700'
const payload = lihDayPayloadLines(draftRows)
assert.equal(payload.length, 2, 'the save payload holds every filled row in one request')
assert.equal(payload[0].id, 'line-1', 'an edited saved row keeps its id, so the server updates only it')
assert.equal(payload[0].unit_cost, '1100')
assert.equal(payload[1].id, undefined, 'a new row is created in the same save')
assert.equal(payload[1].source, 'manual')
assert.equal(rowState(draftRows[0]), 'edited', 'a saved row with one changed field is marked edited')
assert.equal(rowState(draftRowFromSavedLine(SAVED_LINE)), 'saved', 'untouched saved rows stay saved')
assert.equal(lihLineTotal({ no_of_units: '2', unit_cost: '1100' }), 2200)

// ---------------------------------------------------------------------------
// 8. Read-only users get the sheet without any editing affordance.
// ---------------------------------------------------------------------------
await render(createElement(Harness, { key: 'readonly', initial: [draftRowFromSavedLine(SAVED_LINE)], canEdit: false, savedCount: 1 }))
assert.equal(fields().every(field => field.disabled), true, 'read-only users cannot type into the sheet')
assert.equal([...rootElement.querySelectorAll('button')].some(button => button.textContent.includes('Save all items')), false,
  'read-only users get no save action')
assert.match(rootElement.textContent, /read-only with your current permissions/)

await act(async () => { root.unmount() })
w.close()
console.log('LIH worksheet check: all assertions passed')
// jsdom's visual mode keeps a frame loop alive; a check script should still exit.
process.exit(0)

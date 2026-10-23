// Fuel Cost Register regression check: the compact consumption dialog, live material
// balance, Rig Saving (litres) separation from AGO, opening-stock lock/override rules,
// fast Worksheet + Quick-fill grid company entry (including 250-company scaling),
// Excel paste, monthly roll-ups, 5-day recent register and 5-tab page architecture.
//
// Run:
//   cd frontend && npm install --no-save jsdom && NODE_PATH="$PWD/node_modules" \
//     ./node_modules/.bin/esbuild ../.agent/tools/fuel-cost-check.jsx --bundle --platform=node \
//     --format=esm --jsx=automatic --outfile=node_modules/.cache/fuel-cost-check.mjs --external:jsdom && \
//     node node_modules/.cache/fuel-cost-check.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
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

const { act, createElement } = await import('react')
const { createRoot } = await import('react-dom/client')
const { ThemeProvider, CssBaseline } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const { FuelConsumptionDialog } = await import('../../frontend/src/components/fuel-cost/FuelConsumptionDialog')
const {
  buildMonthlyMaterialBalance,
  FUEL_IMPORT_OPTIONAL_HEADERS,
  FUEL_IMPORT_REQUIRED_HEADERS,
  FUEL_IMPORT_SAMPLE,
  fuelBalancePreview,
  fuelDraftFromDay,
  fuelImportRow,
  fuelLitres,
  fuelSavePayload,
  parseFuelCompanyPaste,
  shiftIsoDate,
  validateFuelDraft,
} = await import('../../frontend/src/lib/fuelCost')

const ZERO_BALANCE = {
  is_first_entry: true, opening_overridden: false, carried_opening: '0', previous_date: null,
  opening_stock: '0', opening_adjustment: '0', receipt: '0', rig_engine_consumption: '0',
  company_consumption: '0', total_consumption: '0', book_closing_stock: '0', actual_closing_stock: '0',
  closing_adjustment: '0', adjustments: '0', gas_consumption: '0', rig_saving_litres: '0',
}
const CARRIED_BALANCE = {
  ...ZERO_BALANCE, is_first_entry: false, carried_opening: '1800', previous_date: '2026-10-01',
  opening_stock: '1800', book_closing_stock: '1800', actual_closing_stock: '1800',
}
const COMPANIES = [
  {
    id: 'acme', company_name: 'Acme Fuel Services', vendor_id: 'v1', vendor_code: 'VEN-01', is_default: true,
    source: 'vendor', remarks: '', is_deleted: false, deleted_at: null, display_name: 'Acme Fuel Services',
    created_at: '', updated_at: '',
    categories: [
      { id: 'camp', company_id: 'acme', category_name: 'Camp', remarks: '', is_deleted: false, deleted_at: null, created_at: '', updated_at: '' },
      { id: 'crew', company_id: 'acme', category_name: 'Rig crew', remarks: '', is_deleted: false, deleted_at: null, created_at: '', updated_at: '' },
    ],
  },
  {
    id: 'beta', company_name: 'Beta Logistics', vendor_id: null, vendor_code: '', is_default: false,
    source: 'manual', remarks: '', is_deleted: false, deleted_at: null, display_name: 'Beta Logistics',
    created_at: '', updated_at: '', categories: [],
  },
]
const RIG = { id: 'rig-1', rig_code: 'RIG-01', rig_name: 'Rig One', display_name: 'RIG-01 · Rig One' }
const VENDORS = [
  { id: 'v1', vendor_code: 'VEN-01', vendor_name: 'Acme Fuel Services', vendor_type: 'Third party', status: 'active', registered: true, display_name: 'VEN-01 · Acme Fuel Services' },
]
const firstDay = {
  rig_id: 'rig-1', rig_code: 'RIG-01', rig_name: 'Rig One', cost_date: '2026-10-01',
  entry: null, lines: [], previous_lines: [], balance: { ...ZERO_BALANCE },
}
const secondDay = {
  rig_id: 'rig-1', rig_code: 'RIG-01', rig_name: 'Rig One', cost_date: '2026-10-02',
  entry: null, lines: [],
  previous_lines: [
    { company_id: 'beta', company_name: 'Beta Logistics', category_id: null, category_name: '', litres: '95' },
  ],
  balance: { ...CARRIED_BALANCE },
}
function savedDay({ override = false, opening = null, lines = [] } = {}) {
  const balance = override
    ? { ...CARRIED_BALANCE, opening_overridden: true, opening_stock: '1750', opening_adjustment: '-50' }
    : { ...CARRIED_BALANCE }
  const entry = {
    id: 'entry-1', rig_id: 'rig-1', rig_code: 'RIG-01', rig_name: 'Rig One', cost_date: '2026-10-02',
    rig_engine_consumption: '100', rig_engine_remarks: 'Engines',
    gas_consumption: '25', gas_remarks: 'Gas log',
    rig_saving_litres: '25', rig_saving_remarks: 'Gas log',
    opening_stock: opening ?? (override ? '1750' : null), opening_overridden: override,
    opening_remarks: override ? 'Tank dip' : '', receipt_quantity: '200', receipt_remarks: '',
    closing_stock: '1700', closing_remarks: '', remarks: 'Saved day', revision: 2, line_count: lines.length,
    company_consumption: '0', total_consumption: '100', balance, display_name: 'RIG-01 · 2026-10-02',
    is_deleted: false, deleted_at: null, created_by: '', updated_by: '', created_at: '', updated_at: '',
  }
  return {
    rig_id: 'rig-1', rig_code: 'RIG-01', rig_name: 'Rig One', cost_date: '2026-10-02',
    entry, lines, previous_lines: [], balance,
  }
}

const html = dom.window.document.getElementById('root')
const root = createRoot(html)
const doc = w.document
const dialog = () => doc.querySelector('[role="dialog"]')
const byText = (selector, text) => [...doc.querySelectorAll(selector)].find(node => node.textContent.trim() === text)
const byPrefix = (selector, prefix) => [...doc.querySelectorAll(selector)].find(node => node.textContent.trim().startsWith(prefix))
const click = async node => {
  assert.ok(node, `clickable element exists; buttons: ${[...doc.querySelectorAll('button')].map(b => b.textContent.trim()).filter(Boolean).join(' | ')}`)
  await act(async () => { node.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
}
const inputByLabel = label => {
  const match = [...doc.querySelectorAll('label')].find(node => node.textContent.trim() === label)
  return match ? doc.getElementById(match.getAttribute('for')) : null
}
const inputByAriaLabel = label => doc.querySelector(`input[aria-label="${label}"]`)
const type = async (input, value) => {
  assert.ok(input, `input exists for value ${value}`)
  const setter = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, 'value').set
  await act(async () => {
    setter.call(input, value)
    input.dispatchEvent(new w.Event('input', { bubbles: true }))
  })
}
const dialogText = () => dialog()?.textContent ?? ''
let renderSequence = 0
const renderDialog = async (props = {}) => {
  const key = `dialog-${++renderSequence}`
  await act(async () => {
    root.render(createElement(ThemeProvider, { theme: buildTheme('light') },
      createElement(CssBaseline),
      createElement(FuelConsumptionDialog, {
        key,
        open: true, day: firstDay, loading: false, loadError: '', rig: RIG, costDate: '2026-10-01',
        companies: COMPANIES, vendors: VENDORS, canEdit: true, canManageCompanies: true,
        canOverrideOpening: true, saving: false, saveError: '', onClose: () => {},
        onSave: async () => true, onCompaniesChanged: () => {}, ...props,
      }),
    ))
  })
}

let savedPayload = null

// ---------------------------------------------------------------------------
// 1. The first day captures the opening stock and separates Rig Saving (litres) from AGO.
// ---------------------------------------------------------------------------
await renderDialog({ onSave: async payload => { savedPayload = payload; return true } })
assert.ok(dialog(), 'the consumption pop-up opens in the standard dialog')
assert.match(dialogText(), /Rig engines/, 'rig engines section is present')
assert.match(dialogText(), /Stock and receipts/, 'stock and receipts section is present')
assert.match(dialogText(), /Company consumption \(AGO\)/, 'company consumption section is present')
assert.match(dialogText(), /Material balance/, 'material balance panel is present')
assert.match(dialogText(), /First fuel entry — opening stock required/, 'the first day is called out')
const openingField = inputByLabel('Opening stock (litres)')
assert.ok(openingField && !openingField.disabled, 'the first day’s opening stock is editable')
assert.equal(byText('button', 'Override').disabled, true, 'the first day cannot be overridden — it is the anchor')

await type(inputByLabel('Rig engine consumption (litres)'), '100')
await type(inputByLabel('Rig saving (litres)'), '25')
await type(inputByLabel('Receipt (litres)'), '500')
await type(inputByLabel('Actual closing stock (litres)'), '1290')
await type(openingField, '1000')
assert.match(dialogText(), /1,400\.00/, 'book closing = opening + receipts − AGO')
assert.match(dialogText(), /1,290\.00/, 'actual closing is the entered count')
assert.match(dialogText(), /-110\.00/, 'the closing adjustment is actual − book closing')
assert.match(dialogText(), /Rig saving recorded separately: 25\.00 L/, 'Rig saving litres is reported beside the balance')

// AGO total stays at the engine figure: Rig saving (gas) is never mixed into it.
const agoTile = [...doc.querySelectorAll('div')].find(node => node.textContent.startsWith('TOTAL AGO CONSUMPTION'))
assert.ok(agoTile, 'total AGO tile renders')
assert.equal(agoTile.textContent.includes('25.00'), false, 'Rig saving litres is excluded from total AGO consumption')

// The daily set pre-lists the default companies in the compact worksheet.
await click(byPrefix('button', 'Add daily set'))
const litresInput = inputByLabel('Litres (AGO)')
assert.ok(litresInput, 'a company row was added from the daily set')
await type(litresInput, '80')
assert.match(dialogText(), /Company AGO total: 80\.00 L/, 'company consumption is totalled separately')
assert.match(dialogText(), /1,320\.00/, 'the book closing follows the company consumption as it is typed')
assert.match(dialogText(), /-30\.00/, 'adjustments include the company consumption')

// Save builds the authoritative payload — never a balance figure.
await click(byText('button', 'Add fuel day'))
assert.ok(savedPayload, 'the save action sends the payload')
assert.equal(savedPayload.opening_stock, '1000')
assert.equal(savedPayload.opening_overridden, false)
assert.equal(savedPayload.clear_opening_override, false)
assert.equal(savedPayload.rig_engine_consumption, '100')
assert.equal(savedPayload.gas_consumption, '25')
assert.equal(savedPayload.receipt_quantity, '500')
assert.equal(savedPayload.closing_stock, '1290')
assert.equal(savedPayload.lines.length, 1)
assert.equal(savedPayload.lines[0].company_id, 'acme')
assert.equal(savedPayload.lines[0].litres, '80')
assert.equal('balance' in savedPayload, false, 'the client never submits a balance')
assert.equal('book_closing_stock' in savedPayload, false)

// ---------------------------------------------------------------------------
// 2. Quick-fill 3-column grid + Copy previous + large-scale (250 companies) render cap.
// ---------------------------------------------------------------------------
savedPayload = null
await renderDialog({
  day: secondDay,
  costDate: '2026-10-02',
  onSave: async payload => { savedPayload = payload; return true },
})
// Copy previous day brings in Beta Logistics with blank litres ready to fill.
await click(byPrefix('button', 'Copy previous'))
assert.ok(inputByLabel('Litres (AGO)'), 'previous day company row added immediately')

// Switch to Quick-fill grid and enter litres directly on both companies without dropdown clicks!
await click(byPrefix('button', 'Quick-fill'))
const acmeGridInput = inputByAriaLabel('Acme Fuel Services litres (AGO)')
const betaGridInput = inputByAriaLabel('Beta Logistics litres (AGO)')
assert.ok(acmeGridInput && betaGridInput, 'Quick-fill grid renders direct litres inputs per company')
await type(acmeGridInput, '120')
await type(betaGridInput, '45')
assert.match(dialogText(), /Company AGO total: 165\.00 L/, 'Quick-fill grid updates live company AGO total')
await click(byText('button', 'Add fuel day'))
assert.equal(savedPayload.lines.length, 2, 'Quick-fill grid submits entered company lines cleanly')

// Large-scale test: 250 companies render capped at 90 in Quick-fill grid with Show more / Show all.
const MANY_COMPANIES = Array.from({ length: 250 }, (_, idx) => ({
  id: `comp-${idx + 1}`,
  company_name: `Contractor ${String(idx + 1).padStart(3, '0')}`,
  vendor_id: null,
  vendor_code: `V-${idx + 1}`,
  is_default: idx < 30,
  source: 'manual',
  remarks: '',
  is_deleted: false,
  deleted_at: null,
  display_name: `Contractor ${String(idx + 1).padStart(3, '0')}`,
  created_at: '',
  updated_at: '',
  categories: [],
}))
await renderDialog({ day: secondDay, costDate: '2026-10-02', companies: MANY_COMPANIES })
await click(byPrefix('button', 'Quick-fill'))
assert.match(dialogText(), /Showing 90 of 250 companies/, 'large company sets cap initial DOM nodes to 90')
await click(byPrefix('button', 'Daily set (30)'))
assert.equal(doc.querySelectorAll('input[aria-label$="litres (AGO)"]').length, 30, 'Daily set filter narrows 250 companies to 30 immediately')

// ---------------------------------------------------------------------------
// 3. A missing first-day opening blocks the save with the message by the field.
// ---------------------------------------------------------------------------
savedPayload = null
await renderDialog({ onSave: async payload => { savedPayload = payload; return true } })
await type(inputByLabel('Rig engine consumption (litres)'), '10')
await click(byText('button', 'Add fuel day'))
assert.equal(savedPayload, null, 'the save is refused while the first opening stock is blank')
assert.match(dialogText(), /Opening stock is mandatory on the first day of this rig/, 'the error sits next to the opening field')

// ---------------------------------------------------------------------------
// 4. A later day locks the opening at the carried closing until it is overridden.
// ---------------------------------------------------------------------------
savedPayload = null
await renderDialog({ day: secondDay, costDate: '2026-10-02', onSave: async payload => { savedPayload = payload; return true } })
const carriedField = inputByLabel('Opening stock (litres)')
assert.equal(carriedField.value, '1800', 'the carried closing stock is shown')
assert.equal(carriedField.readOnly, true, 'the carried opening is read-only')
assert.match(dialogText(), /Carried from the closing stock/, 'the source of the opening is explained')
await click(byText('button', 'Override'))
const overriddenField = inputByLabel('Opening stock (litres)')
assert.equal(overriddenField.readOnly, false, 'the override unlocks the opening field')
assert.equal(overriddenField.value, '1800', 'the override starts from the carried stock')
await type(overriddenField, '1750')
await type(inputByLabel('Rig engine consumption (litres)'), '100')
await type(inputByLabel('Actual closing stock (litres)'), '1700')
assert.match(dialogText(), /Opening stock overridden/, 'the override is flagged')
assert.match(dialogText(), /-50\.00/, 'the opening override is an adjustment')
await click(byText('button', 'Add fuel day'))
assert.equal(savedPayload.opening_stock, '1750')
assert.equal(savedPayload.opening_overridden, true)
assert.equal(savedPayload.clear_opening_override, false)

// ---------------------------------------------------------------------------
// 5. Clearing a saved override returns to the carried opening in the same save.
// ---------------------------------------------------------------------------
savedPayload = null
await renderDialog({
  day: savedDay({ override: true }),
  costDate: '2026-10-02',
  onSave: async payload => { savedPayload = payload; return true },
})
assert.equal(inputByLabel('Opening stock (litres)').value, '1750', 'the stored override is shown')
await click(byText('button', 'Use carried'))
await click(byText('button', 'Save fuel day'))
assert.equal(savedPayload.clear_opening_override, true, 'clearing is expressed in the save payload')
assert.equal(savedPayload.opening_stock, null)
assert.equal(savedPayload.opening_overridden, false)

// ---------------------------------------------------------------------------
// 6. Without the override capability the opening stays locked, and read-only users cannot save.
// ---------------------------------------------------------------------------
await renderDialog({ day: secondDay, costDate: '2026-10-02', canOverrideOpening: false })
assert.equal(inputByLabel('Opening stock (litres)').readOnly, true)
assert.equal(byText('button', 'Override').disabled, true, 'no permission, no override')

await renderDialog({ day: savedDay(), costDate: '2026-10-02', canEdit: false })
assert.equal(inputByLabel('Rig engine consumption (litres)').disabled, true)
assert.equal(byText('button', 'Save fuel day').disabled, true, 'read-only users get no save action')
assert.match(dialogText(), /Read only/)

// Dark theme parity check on FuelConsumptionDialog
await act(async () => {
  root.render(createElement(ThemeProvider, { theme: buildTheme('dark') },
    createElement(CssBaseline),
    createElement(FuelConsumptionDialog, {
      key: 'dark-check',
      open: true, day: savedDay(), loading: false, loadError: '', rig: RIG, costDate: '2026-10-02',
      companies: COMPANIES, vendors: VENDORS, canEdit: true, canManageCompanies: true,
      canOverrideOpening: true, saving: false, saveError: '', onClose: () => {},
      onSave: async () => true, onCompaniesChanged: () => {},
    }),
  ))
})
assert.match(dialogText(), /Rig saving \(litres\)/, 'dark mode renders cleanly')

// ---------------------------------------------------------------------------
// 7. Arithmetic, validation, Excel paste, monthly balance & Rig Saving import helpers.
// ---------------------------------------------------------------------------
const overrideDraft = fuelDraftFromDay(secondDay)
overrideDraft.openingOverride = true
overrideDraft.opening = '1750'
overrideDraft.rigEngine = '100'
overrideDraft.receipt = '200'
overrideDraft.closing = '1700'
overrideDraft.gas = '25'
const preview = fuelBalancePreview(secondDay, overrideDraft)
assert.equal(preview.opening, 1750)
assert.equal(preview.carried, 1800)
assert.equal(preview.openingAdjustment, -50)
assert.equal(preview.bookClosing, 1850) // 1750 + 200 − 100
assert.equal(preview.closingAdjustment, -150) // 1700 − 1850
assert.equal(preview.adjustments, -200)
assert.equal(preview.totalConsumption, 100, 'Rig saving litres never joins AGO consumption')
assert.equal(preview.gas, 25)
assert.equal(preview.rigSaving, 25)

const blankClosing = { ...overrideDraft, closing: '' }
assert.equal(fuelBalancePreview(secondDay, blankClosing).actualClosing, 1850, 'blank closing accepts the book closing')
assert.equal(fuelBalancePreview(secondDay, blankClosing).closingAdjustment, 0)

const duplicateDraft = fuelDraftFromDay(secondDay)
duplicateDraft.rigEngine = '10'
duplicateDraft.lines = [
  { key: 'a', company_id: 'acme', category_id: 'camp', litres: '10', remarks: '', source: 'manual' },
  { key: 'b', company_id: 'acme', category_id: 'camp', litres: '5', remarks: '', source: 'manual' },
]
const problems = validateFuelDraft(duplicateDraft, secondDay)
assert.ok(problems.lines.b, 'a repeated company/category row is rejected on the second row')
assert.match(problems.lines.b, /already on row 1/)
assert.equal(validateFuelDraft(fuelDraftFromDay(secondDay), secondDay).summary.length, 1,
  'an empty day is refused before saving')

// Excel paste helper parses tab-separated company + category + litres + remarks.
const pasted = parseFuelCompanyPaste(
  'Company\tCategory\tLitres\nAcme Fuel Services\tRig crew\t215.5\tCrew bus\nBeta Logistics\t90\nUnknown Co\t40',
  COMPANIES,
)
assert.equal(pasted.matched.length, 2)
assert.equal(pasted.matched[0].company_id, 'acme')
assert.equal(pasted.matched[0].category_id, 'crew')
assert.equal(pasted.matched[0].litres, '215.5')
assert.equal(pasted.matched[1].company_id, 'beta')
assert.equal(pasted.matched[1].litres, '90')
assert.deepEqual(pasted.unmatched, ['Unknown Co'])

// Calendar date stepper and monthly material-balance roll-up.
assert.equal(shiftIsoDate('2026-10-01', -1), '2026-09-30')
assert.equal(shiftIsoDate('2026-10-31', 1), '2026-11-01')
const monthly = buildMonthlyMaterialBalance([
  {
    ...savedDay().entry,
    id: 'm1', cost_date: '2026-10-01', rig_saving_litres: '30',
    balance: { ...ZERO_BALANCE, is_first_entry: true, opening_stock: '5000', receipt: '1000', rig_engine_consumption: '200', company_consumption: '100', total_consumption: '300', book_closing_stock: '5700', actual_closing_stock: '5700', gas_consumption: '30' },
  },
  {
    ...savedDay().entry,
    id: 'm2', cost_date: '2026-10-02', rig_saving_litres: '40',
    balance: { ...ZERO_BALANCE, is_first_entry: false, carried_opening: '5700', opening_stock: '5700', receipt: '0', rig_engine_consumption: '150', company_consumption: '50', total_consumption: '200', book_closing_stock: '5500', actual_closing_stock: '5490', closing_adjustment: '-10', adjustments: '-10', gas_consumption: '40' },
  },
])
assert.equal(monthly.length, 1)
assert.equal(monthly[0].day_count, 2)
assert.equal(monthly[0].opening_stock, 5000)
assert.equal(monthly[0].total_consumption, 500)
assert.equal(monthly[0].actual_closing_stock, 5490)
assert.equal(monthly[0].rig_saving_litres, 70)

// Import headers & backward-compatible mapping for Rig Saving (litres) + legacy Gas header.
assert.equal(fuelLitres('1250.5'), '1,250.50')
assert.equal(FUEL_IMPORT_REQUIRED_HEADERS.includes('DATE'), true)
assert.ok(FUEL_IMPORT_OPTIONAL_HEADERS.includes('COMPANY'))
assert.ok(FUEL_IMPORT_OPTIONAL_HEADERS.includes('RIG SAVING (LITRES)'))
const imported = fuelImportRow(FUEL_IMPORT_SAMPLE)
assert.equal(imported.cost_date, '2026-10-01')
assert.equal(imported.rig_code, 'RIG-01')
assert.equal(imported.rig_saving_litres, '60')
assert.equal(imported.gas_consumption, '60')
assert.equal(imported.opening_stock, '12000')
assert.equal(imported.company_name, 'Acme Fuel Services')
assert.equal(imported.category_name, 'Rig crew')
assert.equal(imported.litres, '200')
assert.equal(imported.closing_stock, '17000')
const legacyImported = fuelImportRow({ DATE: '2026-10-02', 'GAS CONSUMPTION (LITRES)': '45', 'GAS REMARKS': 'Legacy sheet' })
assert.equal(legacyImported.rig_saving_litres, '45')
assert.equal(legacyImported.rig_saving_remarks, 'Legacy sheet')

const savedPayloadFull = fuelSavePayload({
  rigId: 'rig-1', costDate: '2026-10-02', draft: overrideDraft, day: savedDay(), expectedRevision: 2,
})
assert.equal(savedPayloadFull.expected_revision, 2, 'a stale revision is detected by the server')
assert.equal(savedPayloadFull.lines.length, 0)

// 8. Page architecture: 5-day landing query (`limit: 5`) + 5 ARIA-wired tabs on the same page.
const pageSource = readFileSync('../frontend/src/pages/FuelCostRegister.tsx', 'utf8')
const appSource = readFileSync('../frontend/src/App.tsx', 'utf8')
const layoutSource = readFileSync('../frontend/src/components/Layout.tsx', 'utf8')
assert.ok(pageSource.includes('Add consumption') && pageSource.includes('Companies & categories'),
  'the rig-scoped page exposes Add consumption and Companies & categories')
assert.ok(pageSource.includes('limit: 5'), 'landing view fetches only the last 5 entered days')
for (const tabId of ['fuel-tab-entry', 'fuel-tab-register', 'fuel-tab-balance', 'fuel-tab-companies', 'fuel-tab-categories']) {
  assert.ok(pageSource.includes(`id="${tabId}"`), `ARIA tab ${tabId} is wired on the same page`)
}
assert.ok(pageSource.includes('company-consumption') && pageSource.includes('FuelLinesLedger'),
  'the page wires company/category summaries and server-paginated line ledgers')
assert.ok(appSource.includes('daily-cost/fuel-cost-register'), 'the route exists')
assert.ok(layoutSource.includes("label: 'Fuel Cost Register'"), 'the navigation item exists')
assert.ok(pageSource.includes('FuelConsumptionDialog') && pageSource.includes('ImportDialog'),
  'the page wires the consumption pop-up and bulk import')

await act(async () => { root.unmount() })
w.close()
console.log('Fuel cost register check: all assertions passed')
process.exit(0)

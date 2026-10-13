// Design-layer check: renders the real theme and shared dialog/chip components in a DOM and
// asserts the rules the design system promises (focus rings, dialog semantics and naming,
// destructive-action colour, CSS-variable status chips) in light and dark.
//
// It is a contributor tool, not part of the application build: nothing here is imported by the
// app, and jsdom is installed with --no-save, so the app's own dependencies stay unchanged.
//
// Run from frontend/ (writes its bundle inside node_modules, so Node resolves jsdom):
//   npm install --no-save jsdom && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/ui-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/ui-check.mjs --loader:.jsx=jsx --log-level=error \
//     --external:jsdom && node node_modules/.cache/ui-check.mjs
//
// Exits non-zero when a rule fails, so it can gate a UI change.
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = w.matchMedia || (q => ({ matches: false, media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false }))
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment', 'ShadowRoot', 'MouseEvent', 'KeyboardEvent', 'CustomEvent', 'DOMRect', 'HTMLIFrameElement', 'HTMLInputElement']) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { act } = await import('react')
const createCache = (await import('@emotion/cache')).default
const { CacheProvider } = await import('@emotion/react')
const { createRoot } = await import('react-dom/client')
const { ThemeProvider, CssBaseline } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const { FormDialog, PanelDialog, Tag, ErrorMessage } = await import('../../frontend/src/components/Common')

const results = []
const check = (label, pass, detail = '') => results.push({ label, pass, detail })

const container = w.document.getElementById('root')
const root = createRoot(container)

for (const mode of ['light', 'dark']) {
  const cache = createCache({ key: 'csscheck', speedy: false }) // text nodes, so the CSS is readable
  await act(async () => {
    root.render(
      <CacheProvider value={cache}>
        <ThemeProvider theme={buildTheme(mode)}>
          <CssBaseline/>
          <Tag tone="warning">Pending</Tag>
          <ErrorMessage message="Row 3 failed"/>
          <FormDialog open danger title="Permanently delete entries?" subtitle="This cannot be undone." onClose={() => {}} onSubmit={() => {}} submitLabel="Permanently delete">
            <p>body</p>
          </FormDialog>
        </ThemeProvider>
      </CacheProvider>
    )
  })
  const doc = w.document
  const dialog = doc.querySelector('[role="dialog"]')
  const labelledBy = dialog?.getAttribute('aria-labelledby')
  const describedBy = dialog?.getAttribute('aria-describedby')
  const titleEl = labelledBy ? doc.getElementById(labelledBy) : null
  const subEl = describedBy ? doc.getElementById(describedBy) : null
  check(`${mode}: dialog exposes aria-labelledby`, Boolean(labelledBy) && Boolean(titleEl), `${labelledBy}`)
  check(`${mode}: accessible name is the title only`, titleEl?.textContent === 'Permanently delete entries?', JSON.stringify(titleEl?.textContent))
  check(`${mode}: aria-describedby points at the subtitle`, subEl?.textContent === 'This cannot be undone.', JSON.stringify(subEl?.textContent))
  const ids = [...doc.querySelectorAll('[id]')].map(e => e.id)
  check(`${mode}: no duplicate ids`, new Set(ids).size === ids.length, ids.join(','))
  const buttons = [...doc.querySelectorAll('[role="dialog"] button')]
  check(`${mode}: Cancel button present`, buttons.some(b => b.textContent === 'Cancel'), buttons.map(b => b.textContent).join('|'))
  const submit = buttons.find(b => b.textContent === 'Permanently delete')
  check(`${mode}: destructive submit uses the error colour`, Boolean(submit?.className.includes('MuiButton-containedError')), submit?.className.split(' ').filter(c => c.startsWith('MuiButton-contained')).join(','))
  check(`${mode}: dialog has no close icon`, doc.querySelectorAll('[role="dialog"] svg[data-testid="CloseIcon"]').length === 0)
  check(`${mode}: no nested heading in the dialog title`, doc.querySelectorAll('[role="dialog"] h2 h1, [role="dialog"] h2 h2, [role="dialog"] h2 h3, [role="dialog"] h2 h4, [role="dialog"] h2 h5, [role="dialog"] h2 h6').length === 0)
  check(`${mode}: dialog title element exists`, doc.querySelectorAll('[role="dialog"] h2').length === 1)
  const css = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n')
  check(`${mode}: focus ring injected into the document`, css.includes(':focus-visible{outline:2px solid'))
  check(`${mode}: chip colours resolve from CSS variables`, css.includes('var(--wcp-tone-warning-bg)'))
  check(`${mode}: error message announced`, Boolean(doc.querySelector('[role="alert"]')))
  check(`${mode}: dialog footer separated`, Boolean(doc.querySelector('.MuiDialogActions-root')))
}

// PanelDialog: same rules, footer button instead of a submit action.
const cache2 = createCache({ key: 'csscheck2', speedy: false })
await act(async () => {
  root.render(
    <CacheProvider value={cache2}>
      <ThemeProvider theme={buildTheme('light')}>
        <PanelDialog open title="Attachments" onClose={() => {}}>files</PanelDialog>
      </ThemeProvider>
    </CacheProvider>
  )
})
{
  const doc = w.document
  const dialog = doc.querySelector('[role="dialog"]')
  check('panel dialog labelled', Boolean(dialog?.getAttribute('aria-labelledby')))
  check('panel dialog has a close button', [...doc.querySelectorAll('[role="dialog"] button')].some(b => b.textContent === 'Close'))
}

let failed = 0
for (const r of results) { if (!r.pass) failed++; console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.label}${r.detail ? `  [${r.detail}]` : ''}`) }
console.log(failed === 0 ? `\nALL ${results.length} UI CHECKS PASSED` : `\n${failed} of ${results.length} CHECKS FAILED`)
process.exit(failed ? 1 : 0)

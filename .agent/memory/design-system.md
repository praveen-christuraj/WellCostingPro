# Design system — WellCosting Pro UI

Read this before writing or reviewing any interface code. It is the committed record of the
design decisions, in the spirit of the `docs/UI_skills` cheatsheet (frontend-design, UI/UX Pro
Max, taste-skill, impeccable, interface-design, Vercel web-design-guidelines). It does not
replace the **Standing product conventions** in `project.md`; where they conflict, the standing
conventions win.

**Rollback:** the whole layer is reversible with `make ui-rollback`. See `project.md` →
*UI design layer (roll back if disliked)*.

## 1. Direction

An **enterprise navy instrument panel**: dense, quiet, data-first. Navy on white, one accent,
hairline rules instead of heavy shadows, and hierarchy carried by size/weight rather than by
colour. It must look like a costing system used for eight hours a day, not a marketing site.

Consequences that follow automatically:

- No centred hero, no three-card row, no gradient, no glass, no emoji, no decorative motion.
- One accent colour (navy). Status colours appear only to say something about data.
- Whitespace is generous around groups of controls, tight inside tables.
- Anything the user must read twice is a layout bug, not a user problem.

## 2. Where the tokens live

| Layer | File | Purpose |
| --- | --- | --- |
| JS tokens | `frontend/src/designSystem.ts` | single source of truth: navy ramp, surfaces, semantics, type scale, spacing, radii, shadows, motion, AG Grid skin |
| MUI theme | `frontend/src/theme.ts` | composes the tokens into `createTheme` + component overrides |
| CSS tokens | `frontend/src/styles.css` | `--wcp-*` mirror of the same values for plain CSS (nav, cards, print, status chips) |

Rules:

1. **Never hardcode a colour, radius, shadow or font stack in a page.** Import a token, use a
   `--wcp-*` variable, or use a palette path (`text.secondary`, `divider`, …).
2. Keep `designSystem.ts` and the `--wcp-*` block in sync. The CSS mirror exists only because
   plain CSS cannot read the MUI theme.
3. Status chips (`Tag`) read `--wcp-tone-<tone>-{bg,fg,border}` **CSS variables**, not the
   theme: chips are rendered inside AG Grid cell renderers, where the React theme context is not
   guaranteed to reach the component.
4. Adding a token means adding it to both layers and using it; do not land an unused token.

## 3. Colour

Navy ramp `navy[50…900]`; `navy[700] = #123A63` is the primary action colour in light mode,
`navy[400] = #8FB8E4` is the accent in dark mode. Backgrounds: canvas `#F4F6F9` / `#0E1B29`,
paper `#FFFFFF` / `#15273B`, raised `#FFFFFF` / `#1B2F48`. Rules: `#E3E9F0` / `#27405C`
(hairline), `#D2DCE7` / `#33506F` (control borders). Text: `#16283F` / `#E6EDF5`,
muted `#5B6B7F` / `#A7B8CB`, disabled `#8293A6` / `#7E93AB`.

- Never green branding; green is a status colour only.
- Never pair one tone's foreground with another tone's background.
- Charts use the navy ramp (`navy[700]`, `navy[600]`, `navy[400]`, `navy[500]`) plus the
  semantic colours, in that order of preference; grid lines are the `divider` colour.

**Contrast (verified, WCAG 2.1):** body text 13.8–14.9:1, muted text 5.0–5.5:1 (light) and
7.5–8.6:1 (dark), primary button label 11.6:1, every status chip 4.8–9.0:1, focus ring 13.5:1
(light) / 8.4:1 (dark). The only pair under 4.5:1 is **disabled** text (3.15:1), which WCAG
exempts for inactive controls. Re-check with a contrast calculator before changing any of these.

## 4. Type

Two families: **Manrope** for headings and KPI values (`fonts.display`), **DM Sans** for
everything else (`fonts.ui`), plus a mono stack for codes, order numbers and CLI snippets.

| Role | Size / line-height | Weight |
| --- | --- | --- |
| h1–h3 | 32 / 26 / 21 | 800, tracking −0.03 → −0.02em |
| h4 (page title) | 18 (pages override to 25–30) | 800 |
| h5 / h6 | 15.5 / 13.5 | 800 |
| subtitle1 / subtitle2 | 14 / 12.5 | 600 / 700 |
| body1 / body2 | 14 / 13 | 400 |
| caption / overline (eyebrow) | 11.5 / 10 | 600 / 800, +1.4px tracking |

Rules: numbers use `font-variant-numeric: tabular-nums` (`.tnum`, `.stat-value`); a page has one
h1-level title; do not go below 11.5px for text a user must read; `text-transform: uppercase` is
reserved for eyebrows, table headers and tiny labels.

## 5. Spacing, radius, elevation, motion

- **4pt rhythm** (`space[1..10]`): gaps and paddings are multiples of 4. Cards 22–24px, card
  gaps 17px, page gutter 16/24/32px.
- **Radii:** 6 controls, 8 inputs, 10 cards/menus, 14 dialogs. Never mix two radii in one
  component.
- **Elevation is quiet:** cards are outlined with `shadows.subtle`; only menus/popovers use
  `raised` and dialogs use `overlay`. Never stack two floating surfaces, never animate elevation.
- **Motion is state feedback only** (`motion.instant/fast/base` = 80/120/160ms,
  `cubic-bezier(0.2, 0, 0, 1)`), limited to `background-color`, `border-color`, `color`,
  `box-shadow`, `opacity`. No transform-based movement, no springs, no loops, nothing over 220ms.
  `prefers-reduced-motion` disables all of it in `styles.css` — do not add `!important`
  transitions that would survive that.

## 6. Density

`#root { zoom: 0.875 }` (in `styles.css`) renders the app 12.5% smaller. **Never zoom `html` or
`body`** — MUI measures menu/dialog anchors in viewport pixels and zooming the document host
displaces every popover. Design at 100% numbers and let the zoom fit the screen; keep
`html, body { overflow-x: clip }` so wide content scrolls inside its own table instead of the page.

Control heights: compact 30, standard 36, comfortable 44; AG Grid rows 55 with a 48 header
(`control.*` in `designSystem.ts`). On touch devices (`@media (pointer: coarse)`) nav items and
menu items grow to a 44px hit area; desktop density is unchanged.

## 7. Patterns

- **Navigation:** top bar only, module dropdowns, active module gets the accent pill
  (`.topnav-item.active` with an inset ring). The page's own `PageHeading` eyebrow carries the
  "MODULE / PAGE" trail, so do not add a second breadcrumb.
- **Page heading:** eyebrow → title → subtitle → actions on the right, `align-items: flex-end`.
- **Lists:** `DataTable` is the only list surface — quick search, advanced filters, a separate
  date/date-range group, 20/50/100 pagination, CSV/XLSX/PDF export, checkbox selection, and the
  AG Grid skin from `gridThemeParams()`. Zebra striping comes from `oddRowBackgroundColor`.
- **Dialogs:** `FormDialog` (submit forms) and `PanelDialog` (everything else) from
  `components/Common.tsx`. They close only via **Cancel**, have no close icon, ignore Escape and
  the backdrop, and expose `aria-labelledby` (the title `<h2>`) plus `aria-describedby` (the
  subtitle paragraph). Destructive, irreversible actions pass `danger` so the primary button is
  the error colour; soft deletes ("Move to Deleted Entries") stay primary.
- **Errors:** inline next to the field or the action (`ErrorMessage`, `Alert`), never a global
  banner; long-running actions show a spinner in the button and a real label
  (`busyLabel`).
- **Status:** `Tag` tones `neutral | info | success | warning | error`. One status per row; do
  not stack chips.

## 8. Accessibility (pre-ship checklist)

- Every interactive element is keyboard reachable with the single focus ring from the theme
  (`:focus-visible` / `.Mui-focusVisible`); never `outline: none` without a replacement.
- `Skip to main content` link → `#main-content` on the layout's `<main>`.
- Icon-only buttons have `aria-label`; disclosure buttons have `aria-expanded`; menus have
  `aria-haspopup`; the record count is `aria-live="polite"`; errors are `role="alert"`.
- Form controls have a real label (MUI `label`, or `component="label" htmlFor` on the login form).
- Do not nest headings (a `<h6>` inside `DialogTitle`'s `<h2>` is invalid; keep one id per node).
- `color-scheme` follows the theme so native widgets (date pickers, scrollbars) do not flash
  white in dark mode; autofill is re-tinted for dark mode.
- No information is carried by colour alone — every status chip also has text.

## 9. Verification

1. `cd frontend && npm run build` — TypeScript + bundle.
2. `bash -c 'cd frontend && npm install --no-save jsdom && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/ui-check.jsx --bundle --platform=node --format=esm --jsx=automatic --outfile=node_modules/.cache/ui-check.mjs --loader:.jsx=jsx --log-level=error --external:jsdom && node node_modules/.cache/ui-check.mjs'`
   — renders the real theme and shared components in a DOM and asserts the rules above (28
   checks, light and dark). The app's own dependencies are untouched.
3. `cd backend && ../.venv/bin/python -m pytest -q` — a UI change must not move the API tests.
4. Look at it: run the API and `npm run dev`, and check the dashboards, one list page, one
   dialog, one AG Grid filter panel, in **both themes**, at 1440 / 1024 / 768px, and once with
   `prefers-reduced-motion` on.

/**
 * Design tokens — the single source of truth for the WellCostIQ interface.
 *
 * Aesthetic direction: an "enterprise navy instrument panel". Dense, quiet and
 * data-first: navy on white, one accent, no decorative motion, generous use of
 * hairline rules instead of heavy shadows, and a type scale that separates
 * heading / body / meta text by weight and size rather than by colour alone.
 *
 * The CSS custom properties in `src/styles.css` (`--wcp-*`) mirror these values so
 * plain CSS (nav, cards, print, scrollbars) stays in sync with the MUI theme.
 * `frontend/src/theme.ts` composes the MUI theme from here; `DataTable` feeds the
 * AG Grid theme from here. Do not hardcode colours in pages — read a token.
 *
 * See `.agent/memory/design-system.md` for the rules that go with these numbers.
 */

export type Mode = 'light' | 'dark'

/** Navy ramp — the brand scale. `700` is the primary action colour. */
export const navy = {
  50: '#F2F6FC',
  100: '#E3EBF7',
  200: '#C9D8ED',
  300: '#93B0DD',
  400: '#6F99D5',
  500: '#2F63B3',
  600: '#255091',
  700: '#1B3F7A',
  800: '#12315F',
  900: '#0B2447',
} as const

export const fonts = {
  /** One bundled variable family keeps forms, tables and headings crisp and consistent. */
  ui: '"Inter Variable", Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
  /** Weight, size and spacing carry hierarchy without mixing typefaces. */
  display: '"Inter Variable", Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
  /** Codes, order numbers, checksums, CLI snippets. */
  mono: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
} as const

/** 4pt rhythm. Every gap/padding in the app is a multiple of 4. */
export const space = { 0: 0, 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 7: 28, 8: 32, 10: 40 } as const

export const radius = { xs: 4, sm: 6, md: 8, lg: 10, xl: 14, pill: 999 } as const

/**
 * Control heights. The app is zoomed to 87.5%, so these are deliberate.
 * Grid rows are compact (42) so a register shows more records per screen: the
 * tallest cell content is a two-line name/email stack (~36px) or a 31px avatar,
 * and row action buttons are ~30px, so 42 keeps everything untouchable-tight
 * without clipping. Do not go below 40 without re-checking those cells.
 */
export const control = { compact: 30, standard: 36, comfortable: 44, gridRow: 42, gridHeader: 40 } as const

/**
 * Motion is limited to state feedback (hover, focus, press, open/close) and is
 * switched off for `prefers-reduced-motion` in `styles.css`. No decorative or
 * looping motion anywhere in the product.
 */
export const motion = {
  instant: '80ms',
  fast: '120ms',
  base: '160ms',
  slow: '220ms',
  /** Fast in, gentle settle — for anything that appears. */
  enter: 'cubic-bezier(0.16, 1, 0.3, 1)',
  /** Standard for small state changes such as hover and focus. */
  standard: 'cubic-bezier(0.2, 0, 0, 1)',
} as const

/** Type scale. Sizes assume the 87.5% app density already applied on `#root`. */
export const typeScale = {
  h1: { fontFamily: fonts.display, fontSize: 32, lineHeight: 1.2, fontWeight: 800, letterSpacing: '-0.03em' },
  h2: { fontFamily: fonts.display, fontSize: 26, lineHeight: 1.22, fontWeight: 800, letterSpacing: '-0.025em' },
  h3: { fontFamily: fonts.display, fontSize: 21, lineHeight: 1.28, fontWeight: 800, letterSpacing: '-0.02em' },
  h4: { fontFamily: fonts.display, fontSize: 18, lineHeight: 1.32, fontWeight: 800, letterSpacing: '-0.015em' },
  h5: { fontFamily: fonts.display, fontSize: 15.5, lineHeight: 1.4, fontWeight: 800, letterSpacing: '-0.01em' },
  h6: { fontFamily: fonts.ui, fontSize: 13.5, lineHeight: 1.45, fontWeight: 800, letterSpacing: 0 },
  subtitle1: { fontFamily: fonts.ui, fontSize: 14, lineHeight: 1.45, fontWeight: 600, letterSpacing: 0 },
  subtitle2: { fontFamily: fonts.ui, fontSize: 12.5, lineHeight: 1.45, fontWeight: 700, letterSpacing: 0 },
  body1: { fontFamily: fonts.ui, fontSize: 14, lineHeight: 1.55, fontWeight: 400, letterSpacing: 0 },
  body2: { fontFamily: fonts.ui, fontSize: 13, lineHeight: 1.5, fontWeight: 400, letterSpacing: 0 },
  caption: { fontFamily: fonts.ui, fontSize: 11.5, lineHeight: 1.4, fontWeight: 600, letterSpacing: 0 },
  overline: { fontFamily: fonts.ui, fontSize: 10, lineHeight: 1.4, fontWeight: 800, letterSpacing: '1.4px' },
} as const

export type SurfaceTokens = {
  /** Page canvas, card surface, and the raised surface above it (menus, dialogs). */
  canvas: string
  paper: string
  raised: string
  hover: string
  selected: string
  /** Hairline rules; `strong` is for control borders that must read on their own. */
  divider: string
  dividerStrong: string
  text: string
  textMuted: string
  textDisabled: string
  /** Keyboard focus ring, drawn outside the control. */
  focus: string
  focusSoft: string
  /** Tinted field used behind KPI/stat icons and the login panel. */
  accentSurface: string
  accentForeground: string
  mutedSurface: string
}

export const surface = (mode: Mode): SurfaceTokens =>
  mode === 'dark'
    ? {
        canvas: '#0B1220',
        paper: '#121B2E',
        raised: '#182339',
        hover: '#1F2B44',
        selected: '#243552',
        divider: '#27354D',
        dividerStrong: '#3A4A66',
        text: '#E7EDF6',
        textMuted: '#A3B2C8',
        textDisabled: '#7B8BA3',
        focus: navy[400],
        focusSoft: 'rgba(143, 184, 228, 0.28)',
        accentSurface: '#192B47',
        accentForeground: navy[400],
        mutedSurface: '#182339',
      }
    : {
        canvas: '#F3F5F9',
        paper: '#FFFFFF',
        raised: '#FFFFFF',
        hover: navy[50],
        selected: navy[100],
        divider: '#D8E0EA',
        dividerStrong: '#B9C6D8',
        text: '#0F1F3D',
        textMuted: '#5B6B85',
        textDisabled: '#8A98AD',
        focus: navy[900],
        focusSoft: 'rgba(18, 58, 99, 0.16)',
        accentSurface: navy[100],
        accentForeground: navy[700],
        mutedSurface: '#F4F6F9',
      }

/**
 * Status colours live as `--wcp-tone-<name>-{bg,fg,border}` custom properties in
 * `styles.css` (neutral / info / success / warning / error). They are CSS variables
 * rather than JS tokens because status chips are also rendered inside AG Grid cell
 * renderers, where the React theme context is not guaranteed to be present.
 * Every tone `fg` on its own `bg` clears WCAG AA for the small label text.
 */

/** Semantic palette for MUI (`error`, `warning`, `success`, `info` all follow it). */
export const semantic = (mode: Mode) =>
  mode === 'dark'
    ? {
        error: { main: '#F2B8B5', dark: '#E79C98', light: '#33201F', contrastText: '#33201F' },
        warning: { main: '#E8C27A', dark: '#D9AC56', light: '#2E2718', contrastText: '#2E2718' },
        success: { main: '#82C7A2', dark: '#5FBF8F', light: '#1B2E24', contrastText: '#1B2E24' },
        info: { main: navy[400], dark: navy[500], light: navy[900], contrastText: navy[900] },
      }
    : {
        error: { main: '#B3261E', dark: '#8E1D17', light: '#FBEAE9', contrastText: '#FFFFFF' },
        warning: { main: '#8A5A00', dark: '#6F4800', light: '#F7F1E4', contrastText: '#FFFFFF' },
        success: { main: '#1E6B45', dark: '#145635', light: '#E7F2EC', contrastText: '#FFFFFF' },
        info: { main: navy[700], dark: navy[800], light: navy[100], contrastText: '#FFFFFF' },
      }

/**
 * Shadows are deliberately shallow: hairline borders carry structure, elevation
 * only says "this floats above the page". Never stack two elevated surfaces.
 */
export const shadow = (mode: Mode) => {
  const dark = mode === 'dark'
  return {
    /** Cards and outlined paper. */
    subtle: dark ? '0 1px 2px rgba(0, 0, 0, 0.34)' : '0 1px 2px rgba(16, 35, 58, 0.06), 0 1px 3px rgba(16, 35, 58, 0.04)',
    /** App bar and sticky toolbars. */
    bar: dark ? '0 1px 0 rgba(0, 0, 0, 0.4)' : '0 1px 2px rgba(16, 35, 58, 0.05)',
    /** Menus, selects, popovers. */
    raised: dark
      ? '0 2px 6px rgba(0, 0, 0, 0.44), 0 14px 34px rgba(0, 0, 0, 0.38)'
      : '0 2px 4px rgba(16, 35, 58, 0.06), 0 10px 26px rgba(16, 35, 58, 0.10)',
    /** Dialogs and the modal backdrop edge. */
    overlay: dark
      ? '0 4px 12px rgba(0, 0, 0, 0.5), 0 28px 64px rgba(0, 0, 0, 0.5)'
      : '0 12px 32px rgba(11, 26, 43, 0.20), 0 2px 6px rgba(11, 26, 43, 0.10)',
  }
}

/** AG Grid theming params, kept here so the grid always matches the MUI surfaces. */
export const gridThemeParams = (mode: Mode) => {
  const s = surface(mode)
  const dark = mode === 'dark'
  return {
    accentColor: dark ? navy[400] : navy[700],
    backgroundColor: s.paper,
    borderColor: s.divider,
    foregroundColor: s.text,
    headerBackgroundColor: dark ? navy[900] : '#F4F6F9',
    headerTextColor: dark ? navy[300] : navy[800],
    headerFontWeight: 700,
    fontFamily: fonts.ui,
    fontSize: 12,
    rowHoverColor: s.hover,
    oddRowBackgroundColor: dark ? '#17293D' : '#FAFBFD',
    chromeBackgroundColor: s.raised,
    // 8 (not the quartz default 10) tightens cell padding and the pagination
    // bar to match the compact row height above.
    spacing: 8,
  }
}

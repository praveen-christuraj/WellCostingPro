import { createTheme, type Theme } from '@mui/material/styles'
import { fonts, motion, navy, radius, semantic, shadow, space, surface, typeScale } from './designSystem'

// Enterprise Navy Blue & White palette (light) and navy-based dark palette.
// No decorative motion: transitions are limited to essential state changes and are
// disabled entirely for `prefers-reduced-motion` (see styles.css).
// Every value comes from src/designSystem.ts so the MUI theme, the CSS variables and
// the AG Grid skin cannot drift apart. This file is part of the UI design layer —
// see `.agent/memory/project.md` → "UI design layer (roll back if disliked)".
export const buildTheme = (mode: 'light' | 'dark'): Theme => {
  const light = mode === 'light'
  const s = surface(mode)
  const sh = shadow(mode)
  const sem = semantic(mode)
  const ring = { outline: `2px solid ${s.focus}`, outlineOffset: '2px' } as const
  const transition = (props: string, duration = motion.fast) => `${props} ${duration} ${motion.standard}`
  // MUI expects exactly 25 elevation slots; the app only ever floats a little.
  const shadows = ['none', ...Array(3).fill(sh.subtle), ...Array(19).fill(sh.raised), sh.overlay, sh.overlay] as unknown as Theme['shadows']

  return createTheme({
    palette: {
      mode,
      primary: light
        ? { main: navy[800], dark: navy[900], light: navy[100], contrastText: '#FFFFFF' }
        : { main: navy[400], dark: navy[500], light: navy[900], contrastText: '#0B1A2B' },
      secondary: light ? { main: navy[600] } : { main: navy[400] },
      background: { default: s.canvas, paper: s.paper },
      text: { primary: s.text, secondary: s.textMuted, disabled: s.textDisabled },
      divider: s.divider,
      error: sem.error,
      warning: sem.warning,
      success: sem.success,
      info: sem.info,
      action: {
        hover: light ? 'rgba(18, 58, 99, 0.045)' : 'rgba(143, 184, 228, 0.08)',
        selected: light ? 'rgba(18, 58, 99, 0.09)' : 'rgba(143, 184, 228, 0.14)',
        disabled: s.textDisabled,
        disabledBackground: light ? '#E2E8EF' : '#1B2C40',
      },
    },
    typography: {
      fontFamily: fonts.ui,
      ...typeScale,
      button: { fontFamily: fonts.ui, fontWeight: 700, textTransform: 'none', letterSpacing: 0 },
    },
    shape: { borderRadius: radius.md },
    spacing: 4,
    shadows,
    components: {
      MuiCssBaseline: {
        // MUI merges this whole object into its global stylesheet, so every key here
        // must be a real selector (a bare `global` key would match nothing).
        styleOverrides: {
          html: {
            // Native widgets (date pickers, scrollbars, form controls) follow the theme.
            colorScheme: mode,
            scrollbarWidth: 'thin',
            scrollbarColor: `${s.dividerStrong} transparent`,
          },
          // One consistent keyboard focus ring; never removed with `outline: none`.
          ':focus-visible': ring,
          '.Mui-focusVisible': ring,
          // A dialog container that takes focus after a keyboard interaction must not draw the
          // ring around the whole panel: its border already separates it, and the FocusTrap puts
          // the visible focus on the first control inside.
          '.MuiDialog-container:focus-visible, [role="dialog"]:focus-visible': { outline: 'none' },
          '::selection': { background: light ? navy[200] : navy[800], color: s.text },
          '::-webkit-scrollbar': { width: 11, height: 11 },
          '::-webkit-scrollbar-track': { background: 'transparent' },
          '::-webkit-scrollbar-thumb': {
            background: s.dividerStrong,
            borderRadius: radius.pill,
            border: '3px solid transparent',
            backgroundClip: 'padding-box',
          },
          '::-webkit-scrollbar-thumb:hover': { background: s.textDisabled, backgroundClip: 'padding-box' },
          '::-webkit-scrollbar-corner': { background: 'transparent' },
          // Autofill must not paint a light box into a dark-mode field.
          'input:-webkit-autofill, input:-webkit-autofill:hover, input:-webkit-autofill:focus, textarea:-webkit-autofill': {
            WebkitTextFillColor: s.text,
            caretColor: s.text,
            WebkitBoxShadow: `0 0 0 1000px ${s.paper} inset`,
          },
          'code, kbd, samp, pre': { fontFamily: fonts.mono, fontSize: '0.94em' },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: {
            borderRadius: 7,
            padding: '7px 14px',
            fontSize: 13,
            transition: transition('background-color, border-color, color'),
            '&.Mui-focusVisible': ring,
            '&.Mui-disabled': { color: s.textDisabled },
          },
          sizeSmall: { padding: '4px 10px', fontSize: 12 },
          sizeLarge: { padding: '10px 20px', fontSize: 14 },
          contained: {
            boxShadow: 'none',
            '&:hover': { boxShadow: 'none' },
            '&.Mui-disabled': { background: light ? '#E2E8EF' : '#1B2C40' },
          },
          containedPrimary: { '&:hover': { backgroundColor: light ? navy[700] : navy[300] } },
          outlined: {
            borderColor: s.dividerStrong,
            '&:hover': { borderColor: light ? navy[800] : navy[400], backgroundColor: s.hover },
            '&.Mui-disabled': { borderColor: s.divider },
          },
          text: { '&:hover': { backgroundColor: s.hover } },
        },
      },
      MuiIconButton: {
        styleOverrides: {
          root: {
            borderRadius: radius.md,
            transition: transition('background-color, color'),
            '&.Mui-focusVisible': ring,
            '&:hover': { backgroundColor: s.hover },
          },
        },
      },
      MuiButtonBase: { styleOverrides: { root: { '&.Mui-focusVisible': ring } } },
      MuiPaper: {
        styleOverrides: {
          root: { backgroundImage: 'none' },
          outlined: { borderColor: s.divider },
        },
      },
      MuiAppBar: { styleOverrides: { root: { backgroundImage: 'none' } } },
      MuiCard: {
        styleOverrides: { root: { backgroundImage: 'none', border: `1px solid ${s.divider}`, boxShadow: sh.subtle } },
      },
      MuiDivider: { styleOverrides: { root: { borderColor: s.divider } } },
      // Inputs
      MuiTextField: { defaultProps: { size: 'small' } },
      MuiInputBase: {
        styleOverrides: {
          root: { fontSize: 13, transition: transition('border-color, box-shadow') },
          input: { '&::placeholder': { color: s.textDisabled, opacity: 1 } },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: radius.md,
            backgroundColor: light ? '#FFFFFF' : 'rgba(255, 255, 255, 0.02)',
            '& .MuiOutlinedInput-notchedOutline': { borderColor: s.dividerStrong },
            '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: navy[500] },
            '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: light ? navy[800] : navy[400] },
            '&.Mui-focused': { boxShadow: `0 0 0 3px ${s.focusSoft}` },
            '&.Mui-disabled .MuiOutlinedInput-notchedOutline': { borderColor: s.divider },
          },
          input: { padding: '8.5px 12px' },
        },
      },
      MuiInputLabel: {
        styleOverrides: {
          root: { fontSize: 13, color: s.textMuted, '&.Mui-focused': { color: light ? navy[800] : navy[400] } },
        },
      },
      MuiFormHelperText: {
        styleOverrides: { root: { fontSize: 11.5, marginTop: 4, color: s.textMuted, '&.Mui-error': { color: sem.error.main } } },
      },
      MuiFormControlLabel: {
        styleOverrides: { root: { gap: space[1], '& .MuiTypography-root': { fontSize: 13 } } },
      },
      MuiInputAdornment: { styleOverrides: { root: { color: s.textMuted } } },
      MuiCheckbox: { styleOverrides: { root: { padding: 6 } } },
      MuiAutocomplete: {
        styleOverrides: {
          paper: { borderRadius: radius.lg, border: `1px solid ${s.divider}`, boxShadow: sh.raised },
          listbox: { padding: 6 },
          option: {
            borderRadius: radius.sm,
            fontSize: 13,
            '&[aria-selected="true"]': { backgroundColor: s.selected },
            '&.Mui-focused': { backgroundColor: s.hover },
          },
        },
      },
      // Floating surfaces: dialogs, menus, tooltips
      MuiBackdrop: {
        styleOverrides: {
          root: { backgroundColor: light ? 'rgba(11, 26, 43, 0.42)' : 'rgba(4, 10, 18, 0.66)' },
          invisible: { backgroundColor: 'transparent' },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: { borderRadius: radius.xl, border: `1px solid ${s.divider}`, boxShadow: sh.overlay },
        },
      },
      MuiMenu: {
        styleOverrides: {
          paper: { borderRadius: radius.lg, border: `1px solid ${s.divider}`, boxShadow: sh.raised, padding: 0 },
          list: { padding: 6 },
        },
      },
      MuiList: { styleOverrides: { root: { padding: 6 } } },
      MuiListItem: { styleOverrides: { root: { borderRadius: radius.sm } } },
      MuiMenuItem: {
        styleOverrides: {
          root: {
            minHeight: 38,
            fontSize: 13,
            fontWeight: 600,
            borderRadius: radius.sm,
            '&.Mui-selected': { backgroundColor: s.selected, '&:hover': { backgroundColor: s.selected } },
          },
        },
      },
      MuiTooltip: {
        defaultProps: { arrow: true },
        styleOverrides: {
          tooltip: {
            backgroundColor: s.raised,
            color: s.text,
            border: `1px solid ${s.divider}`,
            boxShadow: sh.raised,
            borderRadius: radius.sm,
            fontSize: 11.5,
            fontWeight: 600,
            lineHeight: 1.45,
            padding: '6px 9px',
            maxWidth: 280,
          },
          arrow: { color: s.raised },
        },
      },
      // Data surfaces
      MuiTableHead: {
        styleOverrides: { root: { '& .MuiTableCell-root': { borderBottom: `1px solid ${s.divider}` } } },
      },
      MuiTableCell: {
        styleOverrides: {
          // Dense to match the AG Grid row height (`control.gridRow`): on-screen
          // MUI summaries/dialog tables should fit the same number of rows per
          // screen as the registers. Print sheets use their own .ps-* rules.
          root: { borderBottom: `1px solid ${s.divider}`, padding: '7px 12px', fontSize: 12.5 },
          sizeSmall: { padding: '5px 10px' },
          head: { fontWeight: 800, fontSize: 11, letterSpacing: '0.5px', textTransform: 'uppercase', color: s.textMuted },
        },
      },
      MuiTableRow: {
        styleOverrides: { root: { '&:last-child .MuiTableCell-root': { borderBottom: 0 } } },
      },
      MuiTabs: {
        // The sliding indicator is positioned by MUI from getBoundingClientRect()
        // (viewport pixels). Under the app's `#root { zoom: 0.875 }` density those
        // measurements are zoom-scaled while the indicator's style is not, so the
        // underline drifts further from its tab the further right the tab sits —
        // and it is also wrong until web fonts finish loading. The indicator is
        // therefore hidden and the selected tab draws its own underline (below):
        // a CSS pseudo-element on the tab itself is exact at any zoom, font or
        // scroll position, including scrollable tab strips.
        styleOverrides: { root: { minHeight: 46 }, indicator: { display: 'none' } },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            position: 'relative',
            minHeight: 46,
            textTransform: 'none',
            fontSize: 12.5,
            fontWeight: 700,
            color: s.textMuted,
            padding: '8px 14px',
            '&::after': {
              content: '""',
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              height: 2.5,
              borderRadius: '2px 2px 0 0',
              backgroundColor: 'transparent',
              transition: transition('background-color'),
            },
            '&.Mui-selected': {
              color: light ? navy[700] : navy[400],
              '&::after': { backgroundColor: light ? navy[700] : navy[400] },
            },
          },
        },
      },
      MuiToggleButtonGroup: { styleOverrides: { root: { gap: space[1] } } },
      MuiToggleButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontSize: 12.5,
            fontWeight: 700,
            borderRadius: radius.sm,
            borderColor: s.dividerStrong,
            color: s.textMuted,
            '&.Mui-selected': {
              color: light ? navy[700] : navy[400],
              backgroundColor: s.accentSurface,
              '&:hover': { backgroundColor: s.accentSurface },
            },
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { fontWeight: 700, borderRadius: 5 },
          label: { paddingLeft: 8, paddingRight: 8 },
        },
      },
      MuiAlert: {
        styleOverrides: {
          root: { borderRadius: radius.md, fontSize: 12.5, alignItems: 'flex-start', padding: '9px 12px' },
          message: { fontWeight: 600, paddingTop: 1 },
          icon: { paddingTop: 1 },
        },
      },
      MuiAvatar: {
        styleOverrides: { root: { backgroundColor: s.accentSurface, color: s.accentForeground, fontWeight: 800 } },
      },
      MuiCircularProgress: { defaultProps: { thickness: 3.4 } },
    },
  })
}

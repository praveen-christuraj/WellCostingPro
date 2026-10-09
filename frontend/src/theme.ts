import { createTheme, type Theme } from '@mui/material/styles'

// Enterprise Navy Blue & White palette (light) and navy-based dark palette.
// No decorative motion: transitions are limited to essential state changes.
export const buildTheme = (mode: 'light' | 'dark'): Theme => {
  const light = mode === 'light'
  return createTheme({
    palette: {
      mode,
      primary: light
        ? { main: '#123A63', dark: '#0B2A47', light: '#E8EEF6', contrastText: '#FFFFFF' }
        : { main: '#8FB8E4', dark: '#6E9DD0', light: '#1B2F48', contrastText: '#0B1A2B' },
      secondary: light ? { main: '#4A6F96' } : { main: '#8FB8E4' },
      background: light ? { default: '#F4F6F9', paper: '#FFFFFF' } : { default: '#0E1B29', paper: '#15273B' },
      text: light
        ? { primary: '#16283F', secondary: '#5B6B7F' }
        : { primary: '#E6EDF5', secondary: '#A7B8CB' },
      divider: light ? '#E3E9F0' : '#27405C',
      error: light ? { main: '#B3261E' } : { main: '#F2B8B5' },
      warning: light ? { main: '#8A5A00' } : { main: '#E8C27A' },
      success: light ? { main: '#1E6B45' } : { main: '#82C7A2' },
      info: light ? { main: '#123A63' } : { main: '#8FB8E4' },
    },
    typography: {
      fontFamily: '"DM Sans", sans-serif',
      h1: { fontFamily: 'Manrope', fontWeight: 800 },
      h2: { fontFamily: 'Manrope', fontWeight: 800 },
      h3: { fontFamily: 'Manrope', fontWeight: 800 },
      h4: { fontFamily: 'Manrope', fontWeight: 800 },
      h5: { fontFamily: 'Manrope', fontWeight: 800 },
      h6: { fontFamily: 'Manrope', fontWeight: 800 },
      button: { fontWeight: 700, textTransform: 'none' },
    },
    shape: { borderRadius: 8 },
    components: {
      MuiButton: {
        styleOverrides: {
          root: { boxShadow: 'none', borderRadius: 7, padding: '8px 16px' },
          contained: { boxShadow: 'none', '&:hover': { boxShadow: 'none' } },
        },
      },
      MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
      MuiDialog: { styleOverrides: { paper: { borderRadius: 10 } } },
      MuiTextField: { defaultProps: { size: 'small' } },
      MuiChip: { styleOverrides: { root: { fontWeight: 700, borderRadius: 5 } } },
      MuiAppBar: { styleOverrides: { root: { backgroundImage: 'none' } } },
    },
  })
}

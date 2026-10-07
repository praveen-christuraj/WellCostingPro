import { createTheme } from '@mui/material/styles'
export const theme = createTheme({
  palette: { mode: 'light', primary: { main: '#0c756f', dark: '#075b58', light: '#e3f3ef' }, secondary: { main: '#d89548' }, background: { default: '#f5f7f8', paper: '#fff' }, text: { primary: '#172b3a', secondary: '#74838e' }, divider: '#e7edf0' },
  typography: { fontFamily: '"DM Sans", sans-serif', h1: { fontFamily: 'Manrope', fontWeight: 800 }, h2: { fontFamily: 'Manrope', fontWeight: 800 }, h3: { fontFamily: 'Manrope', fontWeight: 800 }, h4: { fontFamily: 'Manrope', fontWeight: 800 }, h5: { fontFamily: 'Manrope', fontWeight: 800 }, h6: { fontFamily: 'Manrope', fontWeight: 800 }, button: { fontWeight: 700, textTransform: 'none' } },
  shape: { borderRadius: 12 },
  components: {
    MuiButton: { styleOverrides: { root: { boxShadow: 'none', borderRadius: 9, padding: '9px 18px' }, contained: { boxShadow: 'none', '&:hover': { boxShadow: 'none' } } } },
    MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
    MuiDialog: { styleOverrides: { paper: { borderRadius: 18 } } },
    MuiTextField: { defaultProps: { size: 'small' } },
    MuiChip: { styleOverrides: { root: { fontWeight: 700, borderRadius: 7 } } }
  }
})

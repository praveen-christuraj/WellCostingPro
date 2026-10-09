import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { CssBaseline, ThemeProvider as MuiThemeProvider } from '@mui/material'
import { buildTheme } from '../theme'

export type ColorMode = 'light' | 'dark'
type ColorModeState = { mode: ColorMode; toggle: () => void }
const ColorModeContext = createContext<ColorModeState>({ mode: 'light', toggle: () => undefined })
const STORAGE_KEY = 'wcp-color-mode'

function initialMode(): ColorMode {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

// Light/dark theme selection, persisted per browser; drives MUI and the CSS variables in styles.css.
export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ColorMode>(initialMode)
  useEffect(() => {
    document.documentElement.dataset.theme = mode
    localStorage.setItem(STORAGE_KEY, mode)
  }, [mode])
  const toggle = useCallback(() => setMode(m => (m === 'light' ? 'dark' : 'light')), [])
  const value = useMemo(() => ({ mode, toggle }), [mode, toggle])
  return <ColorModeContext.Provider value={value}><MuiThemeProvider theme={buildTheme(mode)}><CssBaseline/>{children}</MuiThemeProvider></ColorModeContext.Provider>
}

export function useColorMode() { return useContext(ColorModeContext) }

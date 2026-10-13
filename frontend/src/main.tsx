import React from 'react'
import ReactDOM from 'react-dom/client'
// A data router (instead of plain BrowserRouter) powers the app-wide
// unsaved-changes guard: `useBlocker` in Common.tsx needs it to intercept
// in-app navigation while a page has data that is not saved.
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { ThemeModeProvider } from './context/ThemeContext'
import { AuthProvider } from './context/AuthContext'
import App from './App'
import './styles.css'

const router = createBrowserRouter([{ path: '*', element: <App/> }])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeModeProvider>
      <AuthProvider>
        <RouterProvider router={router}/>
      </AuthProvider>
    </ThemeModeProvider>
  </React.StrictMode>,
)

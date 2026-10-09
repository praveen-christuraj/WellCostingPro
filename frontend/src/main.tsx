import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ThemeModeProvider } from './context/ThemeContext'
import { AuthProvider } from './context/AuthContext'
import App from './App'
import './styles.css'
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ThemeModeProvider><BrowserRouter><AuthProvider><App/></AuthProvider></BrowserRouter></ThemeModeProvider></React.StrictMode>)

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, restoreSession, setAccessToken, body } from '../lib/api'
import type { Me } from '../lib/types'

type AuthState = {
  user: Me | null
  loading: boolean
  login: (organization: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  reload: () => Promise<void>
  can: (permission: string) => boolean
  /** An administrator demanded a new password, or it aged out; the workspace stays closed until it is set. */
  mustChangePassword: boolean
  /** True when the gate is showing because of password age rather than an administrator. */
  passwordExpired: boolean
}
const Context = createContext<AuthState | null>(null)
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const reload = useCallback(async () => { setUser(await api<Me>('/auth/me', { silent: true })) }, [])
  useEffect(() => {
    let mounted = true
    restoreSession().then(async ok => { if (ok) { try { const me = await api<Me>('/auth/me', { silent: true }); if (mounted) setUser(me) } catch { /* invalid session */ } } }).finally(() => { if (mounted) setLoading(false) })
    const expired = () => setUser(null)
    // A security action can force a password change mid-session; re-read the account
    // so the gate appears instead of a wall of permission errors.
    const refresh = () => { reload().catch(() => undefined) }
    window.addEventListener('session-expired', expired)
    window.addEventListener('account-updated', refresh)
    return () => { mounted = false; window.removeEventListener('session-expired', expired); window.removeEventListener('account-updated', refresh) }
  }, [reload])
  const login = async (organization: string, email: string, password: string) => {
    const result = await api<{ access_token: string }>('/auth/login', { method: 'POST', body: body({ organization, email, password }) })
    setAccessToken(result.access_token)
    await reload()
  }
  const logout = async () => { try { await api('/auth/logout', { method: 'POST', silent: true }) } finally { setAccessToken(null); setUser(null) } }
  const can = (permission: string) => !!user && (user.is_owner || user.permission_keys.includes(permission))
  const passwordExpired = !!user?.password_expired
  const mustChangePassword = !!user?.must_change_password || passwordExpired
  return <Context.Provider value={{ user, loading, login, logout, reload, can, mustChangePassword, passwordExpired }}>{children}</Context.Provider>
}
export function useAuth() { const ctx = useContext(Context); if (!ctx) throw new Error('AuthProvider missing'); return ctx }

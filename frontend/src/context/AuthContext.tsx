import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, restoreSession, setAccessToken, body } from '../lib/api'
import type { Me } from '../lib/types'

type AuthState = { user: Me | null; loading: boolean; login: (organization: string, email: string, password: string) => Promise<void>; logout: () => Promise<void>; reload: () => Promise<void>; can: (permission: string) => boolean }
const Context = createContext<AuthState | null>(null)
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const reload = useCallback(async () => { setUser(await api<Me>('/auth/me')) }, [])
  useEffect(() => {
    let mounted = true
    restoreSession().then(async ok => { if (ok) { try { const me = await api<Me>('/auth/me'); if (mounted) setUser(me) } catch { /* invalid session */ } } }).finally(() => { if (mounted) setLoading(false) })
    const expired = () => setUser(null)
    window.addEventListener('session-expired', expired)
    return () => { mounted = false; window.removeEventListener('session-expired', expired) }
  }, [])
  const login = async (organization: string, email: string, password: string) => {
    const result = await api<{ access_token: string }>('/auth/login', { method: 'POST', body: body({ organization, email, password }) })
    setAccessToken(result.access_token)
    await reload()
  }
  const logout = async () => { try { await api('/auth/logout', { method: 'POST' }) } finally { setAccessToken(null); setUser(null) } }
  const can = (permission: string) => !!user && (user.is_owner || user.permission_keys.includes(permission))
  return <Context.Provider value={{ user, loading, login, logout, reload, can }}>{children}</Context.Provider>
}
export function useAuth() { const ctx = useContext(Context); if (!ctx) throw new Error('AuthProvider missing'); return ctx }

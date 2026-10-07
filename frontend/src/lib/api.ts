const ROOT = '/api/v1'
let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null
export const setAccessToken = (value: string | null) => { accessToken = value }

async function renew(): Promise<boolean> {
  if (!refreshing) refreshing = fetch(`${ROOT}/auth/refresh`, { method: 'POST', credentials: 'include' })
    .then(async r => { if (!r.ok) return false; accessToken = (await r.json()).access_token; return true })
    .catch(() => false).finally(() => { refreshing = null })
  return refreshing
}

export async function api<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string> || {}) }
  if (options.body) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  const response = await fetch(`${ROOT}${path}`, { ...options, headers, credentials: 'include' })
  if (response.status === 401 && retry && !path.startsWith('/auth/')) {
    if (await renew()) return api<T>(path, options, false)
    accessToken = null
    window.dispatchEvent(new Event('session-expired'))
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}
export const body = (value: unknown) => JSON.stringify(value)
export const restoreSession = renew

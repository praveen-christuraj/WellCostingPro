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

// File payloads (PO/SO attachments) travel as multipart bodies and blobs, so they
// cannot use the JSON helper above; they still share the token and refresh flow.
async function send(method: string, path: string, payload: BodyInit | null, retry = true): Promise<Response> {
  const headers: Record<string, string> = {}
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  const response = await fetch(`${ROOT}${path}`, { method, headers, body: payload, credentials: 'include' })
  if (response.status === 401 && retry) {
    if (await renew()) return send(method, path, payload, false)
    accessToken = null
    window.dispatchEvent(new Event('session-expired'))
  }
  return response
}

async function failure(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => ({}))
  return new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`)
}

export async function uploadFiles<T>(path: string, files: File[], form: Record<string, string> = {}): Promise<T> {
  const data = new FormData()
  files.forEach(file => data.append('files', file))
  Object.entries(form).forEach(([key, value]) => data.append(key, value))
  const response = await send('POST', path, data)
  if (!response.ok) throw await failure(response)
  return response.json() as Promise<T>
}

export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const response = await send('GET', path, null)
  if (!response.ok) throw await failure(response)
  const disposition = response.headers.get('content-disposition') || ''
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1]
  const plain = /filename="([^"]+)"/i.exec(disposition)?.[1]
  const name = (encoded ? decodeURIComponent(encoded) : plain) || fallbackName
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

export async function previewFile(path: string): Promise<void> {
  const response = await send('GET', path, null)
  if (!response.ok) throw await failure(response)
  const url = URL.createObjectURL(await response.blob())
  const tab = window.open(url, '_blank', 'noopener')
  if (!tab) {
    URL.revokeObjectURL(url)
    throw new Error('The browser blocked the preview tab. Allow pop-ups or use Download.')
  }
}

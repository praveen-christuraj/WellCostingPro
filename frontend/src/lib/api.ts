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
  let response: Response
  try {
    response = await fetch(`${ROOT}${path}`, { ...options, headers, credentials: 'include' })
  } catch {
    const error = new ApiError('Unable to connect to WellCostIQ. Check your network connection and try again.', 0, [])
    notifyError(error)
    throw error
  }
  if (response.status === 401 && retry && !path.startsWith('/auth/')) {
    if (await renew()) return api<T>(path, options, false)
    accessToken = null
    window.dispatchEvent(new Event('session-expired'))
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const error = apiError(payload.detail, response.status)
    notifyError(error)
    throw error
  }
  if (response.status === 204) return undefined as T
  return response.json()
}
// Error raised for failed JSON requests. `details` carries every message the server
// returned (for example one line per invalid estimate row), so pages can list them.
export class ApiError extends Error {
  status: number
  details: string[]
  constructor(message: string, status: number, details: string[]) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

function apiError(detail: unknown, status: number): ApiError {
  if (typeof detail === 'string') return new ApiError(detail, status, [detail])
  if (Array.isArray(detail)) {
    const details = detail
      .map(item => {
        if (typeof item === 'string') return item
        if (typeof item?.msg !== 'string') return ''
        const location = Array.isArray(item.loc)
          ? item.loc.filter((part: unknown) => part !== 'body').map((part: unknown) => String(part).replaceAll('_', ' ')).join(' → ')
          : ''
        return location ? `${location}: ${item.msg}` : item.msg
      })
      .filter(Boolean)
    if (details.length) return new ApiError(details[0], status, details)
  }
  const fallback = status === 401
    ? 'Your session has expired. Sign in again to continue.'
    : status === 403
      ? 'You do not have permission to perform this action.'
      : status === 404
        ? 'The requested record could not be found. It may have been removed or changed.'
        : status === 409
          ? 'This record changed before your update could be saved. Refresh the page and try again.'
          : status >= 500
            ? 'The server could not complete this action. Your data was not changed; please try again.'
            : `The request could not be completed (${status}). Check the entered values and try again.`
  return new ApiError(fallback, status, [fallback])
}

function notifyError(error: ApiError): void {
  window.dispatchEvent(new CustomEvent('api-error', { detail: { message: error.message, status: error.status } }))
}

export const body = (value: unknown) => JSON.stringify(value)
export const restoreSession = renew

// File payloads (PO/SO attachments) travel as multipart bodies and blobs, so they
// cannot use the JSON helper above; they still share the token and refresh flow.
async function send(method: string, path: string, payload: BodyInit | null, retry = true): Promise<Response> {
  const headers: Record<string, string> = {}
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  let response: Response
  try {
    response = await fetch(`${ROOT}${path}`, { method, headers, body: payload, credentials: 'include' })
  } catch {
    const error = new ApiError('Unable to connect to WellCostIQ. Check your network connection and try again.', 0, [])
    notifyError(error)
    throw error
  }
  if (response.status === 401 && retry) {
    if (await renew()) return send(method, path, payload, false)
    accessToken = null
    window.dispatchEvent(new Event('session-expired'))
  }
  return response
}

async function failure(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => ({}))
  const error = apiError(payload.detail, response.status)
  notifyError(error)
  return error
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

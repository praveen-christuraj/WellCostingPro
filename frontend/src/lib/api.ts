const ROOT = '/api/v1'
// Report Builder, Backup & Recovery, workflow summaries and hour-derived
// dashboard durations all belong to this API contract. A lower server version
// means the frontend was deployed before its API and must not disguise missing
// routes or old KPI semantics as a missing business record.
export const REQUIRED_API_VERSION = '0.3.0'
let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null
export const setAccessToken = (value: string | null) => { accessToken = value }

// Requests carry an optional `action` (what the user was doing) and `silent`.
// `action` makes a generic server failure readable; `silent` keeps optional or
// background calls (the notification bell poll, a print companion lookup) from
// raising the global error pop-up, because the page already has a fallback.
export type ApiOptions = RequestInit & { action?: string; silent?: boolean }

async function renew(): Promise<boolean> {
  if (!refreshing) refreshing = fetch(`${ROOT}/auth/refresh`, { method: 'POST', credentials: 'include' })
    .then(async r => { if (!r.ok) return false; accessToken = (await r.json()).access_token; return true })
    .catch(() => false).finally(() => { refreshing = null })
  return refreshing
}

export async function api<T>(path: string, options: ApiOptions = {}, retry = true): Promise<T> {
  const { action, silent, ...request } = options
  const headers: Record<string, string> = { ...(request.headers as Record<string, string> || {}) }
  if (request.body) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  let response: Response
  try {
    response = await fetch(`${ROOT}${path}`, { ...request, headers, credentials: 'include' })
  } catch {
    const error = new ApiError('Unable to connect to WellCostIQ. Check your network connection and try again.', 0, [], action)
    if (!silent) notifyError(error)
    throw error
  }
  if (response.status === 401 && retry && !path.startsWith('/auth/')) {
    if (await renew()) return api<T>(path, options, false)
    accessToken = null
    window.dispatchEvent(new Event('session-expired'))
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const detail = await deploymentAwareDetail(payload.detail, response.status)
    const error = apiError(detail, response.status, action)
    // A security action (or an aged-out password) can close the workspace mid-session.
    // Re-read the account so the password gate appears instead of a wall of 403s.
    if (response.status === 403 && /requires a new password/i.test(error.message)) {
      window.dispatchEvent(new Event('account-updated'))
      throw error
    }
    if (!silent && response.status !== 401) notifyError(error)
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
  action?: string
  constructor(message: string, status: number, details: string[], action?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
    this.action = action
  }
}

// Server details that carry no usable information. Showing one of these verbatim
// is what produced the bare "Not found" pop-up, so they fall back to a sentence
// that names the failed action and says what to do next.
const USELESS_DETAILS = new Set([
  'not found', 'notfound', 'method not allowed', 'internal server error', 'bad request',
  'unauthorized', 'forbidden', 'error', 'http error', 'validation error',
])

function isUselessDetail(detail: unknown): boolean {
  return typeof detail !== 'string' || !detail.trim() || USELESS_DETAILS.has(detail.trim().toLowerCase())
}

function versionParts(value: string): number[] {
  return value.split('.').map(part => Number.parseInt(part, 10) || 0)
}

function versionIsOlder(actual: string, required: string): boolean {
  const left = versionParts(actual)
  const right = versionParts(required)
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    if ((left[index] ?? 0) !== (right[index] ?? 0)) return (left[index] ?? 0) < (right[index] ?? 0)
  }
  return false
}

async function deploymentAwareDetail(detail: unknown, status: number): Promise<unknown> {
  if (status !== 404 || !isUselessDetail(detail)) return detail
  try {
    const response = await fetch('/api/health', { credentials: 'include' })
    if (!response.ok) return detail
    const health = await response.json() as { api_version?: string }
    const actual = String(health.api_version ?? '')
    if (actual && versionIsOlder(actual, REQUIRED_API_VERSION)) {
      return `The web application needs API ${REQUIRED_API_VERSION}, but the server is API ${actual}. The backend deployment is incomplete. Deploy the current main branch and run its database migration, then reload this page.`
    }
  } catch {
    // The original 404 remains the useful fallback when the health probe is unavailable.
  }
  return detail
}

function fallbackMessage(status: number, action?: string): string {
  const base = status === 401
    ? 'Your session has expired. Sign in again to continue.'
    : status === 403
      ? 'You do not have permission to perform this action. Ask an administrator for the matching capability.'
      : status === 404
        ? 'The requested record could not be found. It may have been removed or changed — refresh the page and try again.'
        : status === 409
          ? 'This record changed before your update could be saved. Refresh the page and try again.'
          : status === 429
            ? 'Too many attempts. Wait a moment and try again.'
            : status >= 500
              ? 'The server could not complete this action. Your data was not changed; please try again.'
              : `The request could not be completed (${status}). Check the entered values and try again.`
  return action ? `${action} could not be completed. ${base}` : base
}


// ---------------------------------------------------------------------------
// Validation messages (HTTP 422)
//
// The API answers a rejected form with FastAPI's structured list, whose `msg`
// is written for a developer ("String should match pattern
// '^(low|normal|high|critical)$'"). Shown in a pop-up it reads as a crash. Each
// item is therefore rewritten as one sentence naming the field the user can
// actually see on the screen. Unknown shapes fall back to `msg`, so a new
// server rule never becomes a blank message.
// ---------------------------------------------------------------------------

const FIELD_LABELS: Record<string, string> = {
  id: 'record', ids: 'selection', notes: 'note', reason: 'reason', title: 'title', message: 'message',
  email: 'e-mail address', password: 'password', current_password: 'current password',
  new_password: 'new password', confirm_password: 'confirmation password', reset_code: 'reset code',
  organization: 'workspace', full_name: 'full name', action_path: 'link', severity: 'severity',
  audience: 'audience', page: 'page', page_size: 'page size', due_at: 'due date', task_ids: 'tasks',
  user_ids: 'accounts', assignee_user_id: 'assignee', related_entity_id: 'related record',
}

function fieldLabel(loc: unknown): string {
  const parts = Array.isArray(loc) ? loc.filter((part: unknown) => part !== 'body' && part !== 'query' && part !== 'path') : []
  const last = parts.length ? String(parts[parts.length - 1]) : ''
  if (!last) return 'This value'
  const key = last.replaceAll('_', ' ')
  const known = FIELD_LABELS[last]
  if (known) return known.charAt(0).toUpperCase() + known.slice(1)
  return key.charAt(0).toUpperCase() + key.slice(1)
}

function allowedValues(pattern: unknown): string[] {
  // FastAPI reports a rejected choice as a regular expression such as
  // "^(low|normal|high|critical)$". Splitting it back into the words the user
  // sees on screen keeps the message readable without a second request.
  if (typeof pattern !== 'string') return []
  const body = pattern.startsWith('^(') && pattern.endsWith(')$')
    ? pattern.slice(2, -2)
    : pattern
  if (!body.includes('|')) return []
  return body.split('|').map(value => value.trim()).filter(Boolean)
}

function readableValidation(item: unknown): string {
  if (typeof item === 'string') return item
  const entry = item as { msg?: unknown; type?: unknown; loc?: unknown; ctx?: Record<string, unknown> }
  if (typeof entry?.msg !== 'string') return ''
  const field = fieldLabel(entry.loc)
  const ctx = entry.ctx ?? {}
  const type = typeof entry.type === 'string' ? entry.type : ''
  const lower = field.toLowerCase()
  const tooShort = typeof ctx.min_length === 'number' ? `needs at least ${ctx.min_length} character${ctx.min_length === 1 ? '' : 's'}` : 'is too short'

  if (type === 'missing') return `${field} is required.`
  if (type === 'string_too_short') {
    return ctx.field_type === 'List' ? `${field}: ${tooShort}.` : `${field} ${tooShort}.`
  }
  if (type === 'string_too_long') {
    return typeof ctx.max_length === 'number' ? `${field} must be ${ctx.max_length} characters or fewer.` : `${field} is too long.`
  }
  if (type === 'string_pattern_mismatch') {
    const allowed = allowedValues(ctx.pattern)
    return allowed.length
      ? `${field} must be one of: ${allowed.map(value => value.trim()).join(', ')}.`
      : `${field} is not in the accepted format.`
  }
  if (type === 'too_short') {
    const count = typeof ctx.min_length === 'number' ? ctx.min_length : 1
    return lower.includes('task') || lower.includes('account') || lower.includes('selection') || lower.includes('id')
      ? `Select at least ${count} item${count === 1 ? '' : 's'}.`
      : `Add at least ${count} entr${count === 1 ? 'y' : 'ies'}.`
  }
  if (type === 'too_long') {
    return typeof ctx.max_length === 'number' ? `${field}: at most ${ctx.max_length} entries.` : `${field}: too many entries.`
  }
  if (type === 'greater_than' || type === 'greater_than_equal' || type === 'less_than' || type === 'less_than_equal') {
    const limit = ctx.gt ?? ctx.ge ?? ctx.lt ?? ctx.le
    const direction = type.startsWith('greater') ? 'more than' : 'less than'
    return `${field} must be ${direction} ${limit}.`
  }
  if (type === 'int_parsing' || type === 'float_parsing' || type === 'decimal_parsing' || type === 'int_type' || type === 'float_type' || type === 'decimal_type') {
    return `${field} must be a number.`
  }
  if (type === 'bool_parsing' || type === 'bool_type') return `${field} must be yes or no.`
  if (type === 'string_type') return `${field} must be text.`
  if (type === 'list_type' || type === 'dict_type') return `${field} was not sent in the expected shape.`
  if (type === 'enum' || type === 'literal_error') {
    const expected = ctx.expected
    return typeof expected === 'string' && expected
      ? `${field} must be one of: ${expected.replaceAll(',', ', ')}.`
      : `${field} is not an accepted value.`
  }
  if (type === 'date_from_datetime_parsing' || type === 'date_parsing' || type === 'datetime_parsing' || type === 'datetime_from_date_parsing') {
    return `${field} must be a valid date.`
  }
  if (type === 'json_invalid') return 'The request could not be read. Reload the page and try again.'
  if (type === 'extra_forbidden') return `${field} is not a field this form can set.`
  return `${field}: ${entry.msg.replace(/\.$/, '')}.`
}

function apiError(detail: unknown, status: number, action?: string): ApiError {
  if (typeof detail === 'string') {
    const message = detail.trim()
    if (message && !USELESS_DETAILS.has(message.toLowerCase())) return new ApiError(message, status, [message], action)
    const fallback = fallbackMessage(status, action)
    return new ApiError(fallback, status, [fallback], action)
  }
  if (Array.isArray(detail)) {
    const details = detail.map(readableValidation).filter(Boolean)
    if (details.length) {
      const message = action ? `${action} failed. ${details[0]}` : details[0]
      return new ApiError(message, status, details, action)
    }
  }
  const fallback = fallbackMessage(status, action)
  return new ApiError(fallback, status, [fallback], action)
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
  const detail = await deploymentAwareDetail(payload.detail, response.status)
  const error = apiError(detail, response.status)
  notifyError(error)
  return error
}

export async function uploadFiles<T>(path: string, files: File[], form: Record<string, string> = {}, field = 'files'): Promise<T> {
  // `field` lets a single-file endpoint (backup import) use the name it declares.
  const data = new FormData()
  files.forEach(file => data.append(field, file))
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

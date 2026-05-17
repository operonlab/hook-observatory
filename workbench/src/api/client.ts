import type { ErrorResponse, PaginatedResponse } from '@/types'
import { withRetry } from '@/shared/utils/retry'

const API_BASE = `${__BASE_PATH__}/api`

/** Generate a 12-hex-char request ID matching the backend schema. */
function generateRequestId(): string {
  return crypto.randomUUID().replace(/-/g, '').slice(0, 12)
}

/** Return an existing window-scoped request ID or generate a new one. */
function ensureRequestId(): string {
  const existing = (window as { __workshopRequestId?: string }).__workshopRequestId
  if (typeof existing === 'string' && /^[a-f0-9]{8,64}$/i.test(existing)) {
    return existing
  }
  return generateRequestId()
}

class ApiError extends Error {
  code: string
  status: number

  constructor(status: number, body: ErrorResponse) {
    super(body.detail)
    this.name = 'ApiError'
    this.code = body.code
    this.status = status
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const method = options?.method?.toUpperCase() ?? 'GET'
  const isIdempotent = method === 'GET' || method === 'HEAD'

  const doFetch = async (): Promise<T> => {
    const rid = ensureRequestId()
    // X-Request-ID takes priority; caller may override Content-Type but not the trace header
    const mergedHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string> | undefined),
      'X-Request-ID': rid,
    }
    const res = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      ...options,
      headers: mergedHeaders,
    })

    // Capture server-echoed request ID for subsequent calls in the same action chain
    const respRid = res.headers.get('X-Request-ID')
    if (respRid) {
      ;(window as { __workshopRequestId?: string }).__workshopRequestId = respRid
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({
        detail: `Request failed: ${res.status}`,
        code: 'system.unknown',
        module: null,
      }))
      const err = new ApiError(res.status, body as ErrorResponse)
      // 4xx errors are application-level — do not retry
      if (res.status >= 400 && res.status < 500) {
        Object.assign(err, { _noRetry: true })
      }
      throw err
    }

    if (res.status === 204) return undefined as T
    return res.json()
  }

  if (isIdempotent) {
    return withRetry(doFetch, {
      maxRetries: 2,
      baseDelay: 500,
      isRetryable: (err) => !(err as { _noRetry?: boolean })?._noRetry,
    })
  }
  return doFetch()
}

/** Generic CRUD client factory — one line per module. */
export function createCrudApi<T, C, U>(basePath: string) {
  return {
    list: (page = 1, pageSize = 20) =>
      request<PaginatedResponse<T>>(`${basePath}?page=${page}&page_size=${pageSize}`),

    get: (id: string) => request<T>(`${basePath}/${id}`),

    create: (data: C) =>
      request<T>(basePath, {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    update: (id: string, data: U) =>
      request<T>(`${basePath}/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }),

    delete: (id: string) => request<void>(`${basePath}/${id}`, { method: 'DELETE' }),
  }
}

/** Build URLSearchParams from object, skip undefined/null/empty. Auto-set page defaults. */
export function buildParams(
  obj: Record<string, unknown>,
  defaults?: Record<string, unknown>,
): string {
  const qs = new URLSearchParams()
  const merged = { page: 1, page_size: 20, ...defaults, ...obj }
  for (const [k, v] of Object.entries(merged)) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  return qs.toString() ? `?${qs}` : ''
}

export { request, ApiError }

import type { ErrorResponse, PaginatedResponse } from '@/types'

const API_BASE = `${__BASE_PATH__}/api`

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
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({
      detail: `Request failed: ${res.status}`,
      code: 'system.unknown',
      module: null,
    }))
    throw new ApiError(res.status, body as ErrorResponse)
  }

  if (res.status === 204) return undefined as T
  return res.json()
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
  defaults?: Record<string, unknown>
): string {
  const qs = new URLSearchParams()
  const merged = { page: 1, page_size: 20, ...defaults, ...obj }
  for (const [k, v] of Object.entries(merged)) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  return qs.toString() ? `?${qs}` : ''
}

export { request, ApiError }

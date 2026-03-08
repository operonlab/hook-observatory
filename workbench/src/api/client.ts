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

export { request, ApiError }

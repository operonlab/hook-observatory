import type { LifecycleRun, LifecycleRunList, LifecycleTrends } from '../types'

// Anvil station API goes through Nginx proxy, NOT core API
const ANVIL_API = '/apps/anvil/api/anvil'

async function anvilRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${ANVIL_API}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: `Request failed: ${res.status}` }))
    throw new Error(body.detail || `Anvil API error ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

// ─── Lifecycle Runs API ───

export const lifecycleApi = {
  list: (params?: { status?: string; limit?: number; offset?: number }) => {
    const search = new URLSearchParams()
    if (params?.status) search.set('status', params.status)
    if (params?.limit) search.set('limit', String(params.limit))
    if (params?.offset) search.set('offset', String(params.offset))
    const qs = search.toString()
    return anvilRequest<LifecycleRunList>(`/lifecycle/runs${qs ? `?${qs}` : ''}`)
  },

  get: (runId: string) => anvilRequest<LifecycleRun>(`/lifecycle/runs/${runId}`),

  trends: (days = 30) => anvilRequest<LifecycleTrends>(`/lifecycle/trends?days=${days}`),
}

// ─── Health API ───

export const healthApi = {
  check: () => anvilRequest<{ status: string }>('/health'),
}

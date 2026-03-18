import type {
  CatalogListResponse,
  CatalogSkillDetail,
  DemandStats,
  GlobalStats,
  GraphData,
  LifecycleRun,
  LifecycleRunList,
  LifecycleTrends,
  TimeSavedStats,
} from '../types'

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

// ─── Stats API ───

export const statsApi = {
  global: (category = 'all') =>
    anvilRequest<GlobalStats>(
      `/stats${category !== 'all' ? `?category=${category}` : '?category=all'}`,
    ),

  demand: (params?: { since?: string; until?: string; limit?: number }) => {
    const search = new URLSearchParams()
    if (params?.since) search.set('since', params.since)
    if (params?.until) search.set('until', params.until)
    if (params?.limit) search.set('limit', String(params.limit))
    const qs = search.toString()
    return anvilRequest<DemandStats>(`/stats/demand${qs ? `?${qs}` : ''}`)
  },

  timeSaved: (period = '30d') => anvilRequest<TimeSavedStats>(`/stats/time-saved?period=${period}`),
}

// ─── Catalog API ───

export const catalogApi = {
  list: (params?: {
    q?: string
    domain?: string
    sort?: string
    limit?: number
    offset?: number
  }) => {
    const search = new URLSearchParams()
    if (params?.q) search.set('q', params.q)
    if (params?.domain) search.set('domain', params.domain)
    if (params?.sort) search.set('sort', params.sort)
    if (params?.limit) search.set('limit', String(params.limit))
    if (params?.offset) search.set('offset', String(params.offset))
    const qs = search.toString()
    return anvilRequest<CatalogListResponse>(`/catalog/skills${qs ? `?${qs}` : ''}`)
  },

  get: (name: string) =>
    anvilRequest<CatalogSkillDetail>(`/catalog/skills/${encodeURIComponent(name)}`),

  graph: () => anvilRequest<GraphData>('/catalog/graph'),

  sync: () =>
    anvilRequest<{ synced_skills: number; edges: number; errors: string[] }>('/catalog/sync', {
      method: 'POST',
    }),
}

// ─── Health API ───

export const healthApi = {
  check: () => anvilRequest<{ status: string }>('/health'),
}

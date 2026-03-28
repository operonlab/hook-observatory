import { buildParams } from '@/api/client'
import type { PaginatedResponse, User, UserDetail } from '@/types'

const BASE = ''

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as Record<string, string>).detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

// --- Tier Stats (agent-metrics) ---

export interface TierStat {
  tier: string
  count: number
  pct: number
  avg_duration: number
}

export interface TierStatsResponse {
  stats: TierStat[]
  total: number
  days: number
}

export function fetchTierStats(days = 30): Promise<TierStatsResponse> {
  return request(`/api/agent-metrics/maestro/tier-stats?days=${days}`)
}

export function listUsers(params: {
  page?: number
  page_size?: number
  status_filter?: string
  search?: string
}): Promise<PaginatedResponse<User>> {
  return request(`/auth/admin/users${buildParams(params as Record<string, unknown>)}`)
}

export function getUserDetail(userId: string): Promise<UserDetail> {
  return request(`/auth/admin/users/${userId}`)
}

export function updateUser(
  userId: string,
  data: { display_name?: string; role?: string; status?: string },
): Promise<User> {
  return request(`/auth/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

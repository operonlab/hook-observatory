import { request } from '@/api/client'
import type { PaginatedResponse } from '@/types'

export interface Capture {
  id: string
  space_id: string
  module: string
  entity_type: string
  payload: Record<string, unknown>
  raw_input: string | null
  completeness: number
  status: 'pending' | 'promoted' | 'expired'
  version: number
  group_id: string | null
  promoted_id: string | null
  promoted_at: string | null
  expires_at: string | null
  missing_fields: string[]
  created_at: string
  updated_at: string
}

export interface CapturePromoteResult {
  success: boolean
  capture_id: string
  promoted_id: string | null
  missing_fields: string[]
  error: string | null
}

export interface CaptureStats {
  total: number
  by_module: Record<string, number>
  by_status: Record<string, number>
}

export const captureApi = {
  list: (params?: { module?: string; entity_type?: string; status?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.module) qs.set('module', params.module)
    if (params?.entity_type) qs.set('entity_type', params.entity_type)
    if (params?.status) qs.set('status', params.status)
    if (params?.limit) qs.set('limit', String(params.limit))
    const q = qs.toString()
    return request<PaginatedResponse<Capture>>(`/captures${q ? `?${q}` : ''}`).then(
      (res) => res.items,
    )
  },

  get: (id: string) => request<Capture>(`/captures/${id}`),

  create: (data: {
    module: string
    entity_type: string
    payload: Record<string, unknown>
    raw_input?: string
  }) =>
    request<Capture>('/captures', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: string, data: { payload: Record<string, unknown> }) =>
    request<Capture>(`/captures/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  promote: (id: string) =>
    request<CapturePromoteResult>(`/captures/${id}/promote`, {
      method: 'POST',
    }),

  delete: (id: string) => request<void>(`/captures/${id}`, { method: 'DELETE' }),

  stats: () => request<CaptureStats>('/captures/stats'),

  fillOptions: (module: string, entityType: string) =>
    request<Record<string, { id: string; name: string }[]>>(
      `/captures/fill-options?module=${module}&entity_type=${entityType}`,
    ),
}

import { request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  AttitudeFact,
  CascadeRecallResult,
  Cluster,
  ClusterDetail,
  SkillInvocation,
  SkillProficiency,
  Triple,
  WisdomNode,
} from '../types'

const BASE = '/memvault/kg'

export const kgApi = {
  // ── Triples ──

  listTriples: (
    page = 1,
    pageSize = 20,
    predicate?: string,
    subject?: string,
  ): Promise<PaginatedResponse<Triple>> => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    })
    if (predicate) params.set('predicate', predicate)
    if (subject) params.set('subject', subject)
    return request<PaginatedResponse<Triple>>(`${BASE}/triples?${params}`)
  },

  searchTriples: (q: string, topK = 10): Promise<Triple[]> =>
    request<Triple[]>(`${BASE}/triples/search?q=${encodeURIComponent(q)}&top_k=${topK}`),

  // ── Clusters ──

  listClusters: (): Promise<Cluster[]> => request<Cluster[]>(`${BASE}/clusters`),

  getCluster: (id: string): Promise<ClusterDetail> =>
    request<ClusterDetail>(`${BASE}/clusters/${id}`),

  // ── Wisdom ──

  listWisdom: (confidence?: string, tag?: string): Promise<WisdomNode[]> => {
    const params = new URLSearchParams()
    if (confidence) params.set('confidence', confidence)
    if (tag) params.set('tag', tag)
    const qs = params.toString()
    return request<WisdomNode[]>(`${BASE}/wisdom${qs ? `?${qs}` : ''}`)
  },

  // ── Attitudes ──

  listAttitudes: (category?: string): Promise<AttitudeFact[]> => {
    const params = new URLSearchParams()
    if (category) params.set('category', category)
    const qs = params.toString()
    return request<AttitudeFact[]>(`${BASE}/attitudes${qs ? `?${qs}` : ''}`)
  },

  attitudeHistory: (factId: string): Promise<AttitudeFact[]> =>
    request<AttitudeFact[]>(`${BASE}/attitudes/history/${factId}`),

  // ── Skills ──

  skillProficiency: (): Promise<SkillProficiency[]> =>
    request<SkillProficiency[]>(`${BASE}/skills/proficiency`),

  skillHistory: (name: string, limit = 20): Promise<SkillInvocation[]> =>
    request<SkillInvocation[]>(`${BASE}/skills/${encodeURIComponent(name)}/history?limit=${limit}`),

  // ── CRUD: Triples ──

  deleteTriple: (id: string): Promise<void> =>
    request<void>(`${BASE}/triples/${id}`, { method: 'DELETE' }),

  updateTriple: (
    id: string,
    data: { subject: string; predicate: string; object: string; topic?: string },
  ): Promise<Triple> =>
    request<Triple>(`${BASE}/triples/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // ── CRUD: Attitudes ──

  deleteAttitude: (id: string): Promise<void> =>
    request<void>(`${BASE}/attitudes/${id}`, { method: 'DELETE' }),

  updateAttitude: (
    id: string,
    data: { fact: string; category: string; operation?: string; confidence?: number },
  ): Promise<AttitudeFact> =>
    request<AttitudeFact>(`${BASE}/attitudes/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // ── CRUD: Skill Invocations ──

  deleteSkillInvocation: (id: string): Promise<void> =>
    request<void>(`${BASE}/skills/invocations/${id}`, { method: 'DELETE' }),

  // ── Cascade Recall ──

  cascadeRecall: (q: string, topK = 5): Promise<CascadeRecallResult> =>
    request<CascadeRecallResult>(`${BASE}/recall?q=${encodeURIComponent(q)}&top_k=${topK}`),

  // ── Decay ──

  applyDecay: (): Promise<{ checked: number; updated: number }> =>
    request<{ checked: number; updated: number }>(`${BASE}/decay`, {
      method: 'POST',
    }),
}

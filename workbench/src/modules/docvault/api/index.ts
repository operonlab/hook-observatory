import { createCrudApi, request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  Contradiction,
  DashboardData,
  Document,
  DocumentChunk,
  DocumentCreate,
  DocumentRelation,
  DocumentRelationCreate,
  DocumentUpdate,
  DocumentVersion,
  CoverageGap,
  QALog,
  QARequest,
  QAResponse,
} from '../types'

const documentCrud = createCrudApi<Document, DocumentCreate, DocumentUpdate>('/docvault/documents')

export const docvaultApi = {
  ...documentCrud,

  // Documents — filtered list
  listFiltered: (params: {
    tags?: string
    status?: string
    page?: number
    pageSize?: number
  }) => {
    const q = new URLSearchParams()
    if (params.tags) q.set('tags', params.tags)
    if (params.status) q.set('status', params.status)
    q.set('page', String(params.page ?? 1))
    q.set('page_size', String(params.pageSize ?? 20))
    return request<PaginatedResponse<Document>>(`/docvault/documents?${q.toString()}`)
  },

  // Versions
  listVersions: (documentId: string) =>
    request<PaginatedResponse<DocumentVersion>>(
      `/docvault/documents/${documentId}/versions`,
    ),

  // Chunks
  listChunks: (documentId: string, page = 1, pageSize = 20) =>
    request<PaginatedResponse<DocumentChunk>>(
      `/docvault/documents/${documentId}/chunks?page=${page}&page_size=${pageSize}`,
    ),

  // Relations
  listRelations: (documentId: string) =>
    request<PaginatedResponse<DocumentRelation>>(
      `/docvault/documents/${documentId}/relations`,
    ),
  createRelation: (documentId: string, data: DocumentRelationCreate) =>
    request<DocumentRelation>(`/docvault/documents/${documentId}/relations`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Search
  search: (query: string, topK = 10) =>
    request<{ results: DocumentChunk[] }>('/docvault/search', {
      method: 'POST',
      body: JSON.stringify({ q: query, top_k: topK }),
    }),

  // QA
  qa: (data: QARequest) =>
    request<QAResponse>('/docvault/qa', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // QA Logs
  listQALogs: (page = 1, pageSize = 20) =>
    request<PaginatedResponse<QALog>>(
      `/docvault/qa/logs?page=${page}&page_size=${pageSize}`,
    ),
  qaFeedback: (qaLogId: string, feedback: 'positive' | 'negative') =>
    request<QALog>(`/docvault/qa/logs/${qaLogId}/feedback`, {
      method: 'PATCH',
      body: JSON.stringify({ feedback }),
    }),

  // Coverage Gaps
  listGaps: (status?: string) => {
    const q = new URLSearchParams()
    if (status) q.set('status', status)
    return request<PaginatedResponse<CoverageGap>>(
      `/docvault/gaps?${q.toString()}`,
    )
  },

  // Dashboard
  getDashboard: () => request<DashboardData>('/docvault/dashboard'),
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { docvaultApi } from '../api'
import type { DocumentRelationCreate, QARequest } from '../types'
import { logMutation } from '@/shared/utils/actionJournal'

export const docvaultKeys = {
  all: ['docvault'] as const,
  dashboard: () => [...docvaultKeys.all, 'dashboard'] as const,
  documents: (filters: Record<string, unknown>) =>
    [...docvaultKeys.all, 'documents', filters] as const,
  document: (id: string) => [...docvaultKeys.all, 'document', id] as const,
  versions: (docId: string) => [...docvaultKeys.all, 'versions', docId] as const,
  chunks: (docId: string) => [...docvaultKeys.all, 'chunks', docId] as const,
  relations: (docId: string) => [...docvaultKeys.all, 'relations', docId] as const,
  search: (query: string) => [...docvaultKeys.all, 'search', query] as const,
  qa: (question: string) => [...docvaultKeys.all, 'qa', question] as const,
  qaLogs: (page: number) => [...docvaultKeys.all, 'qaLogs', page] as const,
  gaps: (status: string) => [...docvaultKeys.all, 'gaps', status] as const,
}

const PAGE_SIZE = 20

// ======================== Dashboard ========================

export function useDashboardQuery() {
  return useQuery({
    queryKey: docvaultKeys.dashboard(),
    queryFn: () => docvaultApi.getDashboard(),
    staleTime: 5 * 60 * 1000,
  })
}

// ======================== Documents ========================

export function useDocumentsQuery(filters: {
  page: number
  tags: string | null
  status: string | null
}) {
  return useQuery({
    queryKey: docvaultKeys.documents({
      page: filters.page,
      tags: filters.tags,
      status: filters.status,
    }),
    queryFn: () =>
      docvaultApi.listFiltered({
        page: filters.page,
        pageSize: PAGE_SIZE,
        tags: filters.tags ?? undefined,
        status: filters.status ?? undefined,
      }),
  })
}

export function useDocumentQuery(id: string | undefined) {
  return useQuery({
    queryKey: docvaultKeys.document(id!),
    queryFn: () => docvaultApi.get(id!),
    enabled: !!id,
  })
}

// ======================== Versions ========================

export function useVersionsQuery(documentId: string | undefined) {
  return useQuery({
    queryKey: docvaultKeys.versions(documentId!),
    queryFn: () => docvaultApi.listVersions(documentId!),
    enabled: !!documentId,
  })
}

// ======================== Chunks ========================

export function useChunksQuery(documentId: string | undefined) {
  return useQuery({
    queryKey: docvaultKeys.chunks(documentId!),
    queryFn: () => docvaultApi.listChunks(documentId!),
    enabled: !!documentId,
  })
}

// ======================== Relations ========================

export function useRelationsQuery(documentId: string | undefined) {
  return useQuery({
    queryKey: docvaultKeys.relations(documentId!),
    queryFn: () => docvaultApi.listRelations(documentId!),
    enabled: !!documentId,
  })
}

export function useCreateRelation(documentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: DocumentRelationCreate) =>
      docvaultApi.createRelation(documentId, data),
    onSuccess: () => {
      logMutation('docvault/createRelation', { documentId })
      qc.invalidateQueries({ queryKey: docvaultKeys.relations(documentId) })
    },
  })
}

// ======================== Search ========================

export function useSearchQuery(query: string, topK = 10) {
  return useQuery({
    queryKey: docvaultKeys.search(query),
    queryFn: () => docvaultApi.search(query, topK),
    enabled: query.length > 0,
  })
}

// ======================== QA ========================

export function useQAMutation() {
  return useMutation({
    mutationFn: (data: QARequest) => docvaultApi.qa(data),
    onSuccess: (_, variables) => {
      logMutation('docvault/qa', { question: variables.question })
    },
  })
}

// ======================== QA Logs ========================

export function useQALogsQuery(page: number) {
  return useQuery({
    queryKey: docvaultKeys.qaLogs(page),
    queryFn: () => docvaultApi.listQALogs(page, PAGE_SIZE),
  })
}

export function useQAFeedback() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ qaLogId, feedback }: { qaLogId: string; feedback: 'positive' | 'negative' }) =>
      docvaultApi.qaFeedback(qaLogId, feedback),
    onSuccess: () => {
      logMutation('docvault/qaFeedback', {})
      qc.invalidateQueries({ queryKey: docvaultKeys.all })
    },
  })
}

// ======================== Coverage Gaps ========================

export function useGapsQuery(status: string) {
  return useQuery({
    queryKey: docvaultKeys.gaps(status),
    queryFn: () => docvaultApi.listGaps(status),
  })
}

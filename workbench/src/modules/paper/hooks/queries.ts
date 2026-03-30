import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { paperApi } from '@/modules/paper/api/client'
import type { AnnotationCreate } from '@/modules/paper/types'
import { logMutation } from '@/shared/utils/actionJournal'

export const paperKeys = {
  all: ['paper'] as const,
  dashboard: () => [...paperKeys.all, 'dashboard'] as const,
  articles: (filters: Record<string, unknown>) => [...paperKeys.all, 'articles', filters] as const,
  article: (id: string) => [...paperKeys.all, 'article', id] as const,
  digest: (articleId: string) => [...paperKeys.all, 'digest', articleId] as const,
  annotations: (articleId: string) => [...paperKeys.all, 'annotations', articleId] as const,
  search: (query: string) => [...paperKeys.all, 'search', query] as const,
}

export const ARTICLES_PAGE_SIZE = 20

export function useDashboardQuery() {
  return useQuery({
    queryKey: paperKeys.dashboard(),
    queryFn: () => paperApi.getDashboard(),
    staleTime: 5 * 60 * 1000,
  })
}

export function useArticlesQuery(filters: {
  page: number
  category: string | null
  tag: string | null
  relevance: string | null
}) {
  return useQuery({
    queryKey: paperKeys.articles({
      page: filters.page,
      category: filters.category,
      tag: filters.tag,
      relevance: filters.relevance,
    }),
    queryFn: () =>
      paperApi.listFiltered({
        page: filters.page,
        pageSize: ARTICLES_PAGE_SIZE,
        category: filters.category ?? undefined,
        tag: filters.tag ?? undefined,
        relevance: filters.relevance ?? undefined,
      }),
  })
}

export function useArticleQuery(id: string | undefined) {
  return useQuery({
    queryKey: paperKeys.article(id!),
    queryFn: () => paperApi.get(id!),
    enabled: !!id,
  })
}

export function useDigestQuery(articleId: string | undefined) {
  return useQuery({
    queryKey: paperKeys.digest(articleId!),
    queryFn: async () => {
      try {
        return await paperApi.getDigest(articleId!)
      } catch {
        // 404 is expected when no digest exists yet
        return null
      }
    },
    enabled: !!articleId,
  })
}

export function useAnnotationsQuery(articleId: string | undefined) {
  return useQuery({
    queryKey: paperKeys.annotations(articleId!),
    queryFn: async () => {
      const res = await paperApi.getAnnotations(articleId!)
      return Array.isArray(res) ? res : ((res as any).items ?? [])
    },
    enabled: !!articleId,
  })
}

export function useSearchArticlesQuery(query: string) {
  return useQuery({
    queryKey: paperKeys.search(query),
    queryFn: () => paperApi.search(query, 10, 0.3),
    enabled: query.trim().length > 0,
  })
}

export function useDeleteArticleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => paperApi.delete(id),
    onSuccess: (_, variables) => {
      logMutation('paper/deleteArticle', variables)
      queryClient.invalidateQueries({ queryKey: paperKeys.all })
    },
  })
}

export function useAddAnnotationMutation(articleId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: AnnotationCreate) => paperApi.createAnnotation(articleId, data),
    onSuccess: (_, variables) => {
      logMutation('paper/addAnnotation', variables)
      queryClient.invalidateQueries({ queryKey: paperKeys.annotations(articleId) })
    },
  })
}

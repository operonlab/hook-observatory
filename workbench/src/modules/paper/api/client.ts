import { createCrudApi, request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  Annotation,
  AnnotationCreate,
  Article,
  ArticleCreate,
  ArticleUpdate,
  DashboardData,
  Digest,
  SearchResult,
} from '../types'

const articleCrud = createCrudApi<Article, ArticleCreate, ArticleUpdate>('/paper/articles')

export const paperApi = {
  ...articleCrud,

  listFiltered: (params: {
    category?: string
    tag?: string
    relevance?: string
    page?: number
    pageSize?: number
  }) => {
    const q = new URLSearchParams()
    if (params.category) q.set('category', params.category)
    if (params.tag) q.set('tag', params.tag)
    if (params.relevance) q.set('relevance', params.relevance)
    q.set('page', String(params.page ?? 1))
    q.set('page_size', String(params.pageSize ?? 20))
    return request<PaginatedResponse<Article>>(`/paper/articles?${q.toString()}`)
  },

  search: (query: string, limit = 10, threshold = 0.3) =>
    request<SearchResult[]>('/paper/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit, threshold }),
    }),

  getDigest: (articleId: string) => request<Digest>(`/paper/articles/${articleId}/digest`),

  getAnnotations: (articleId: string) =>
    request<Annotation[]>(`/paper/articles/${articleId}/annotations`),

  createAnnotation: (articleId: string, data: AnnotationCreate) =>
    request<Annotation>(`/paper/articles/${articleId}/annotations`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getDashboard: () => request<DashboardData>('/paper/dashboard'),
}

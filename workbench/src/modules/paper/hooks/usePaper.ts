import { usePaperStore } from '@/modules/paper/stores'
import type { AnnotationCreate } from '@/modules/paper/types'
import {
  ARTICLES_PAGE_SIZE,
  useAddAnnotationMutation,
  useAnnotationsQuery,
  useArticleQuery,
  useArticlesQuery,
  useDashboardQuery,
  useDeleteArticleMutation,
  useDigestQuery,
  useSearchArticlesQuery,
} from './queries'

export function useDashboard() {
  const { data: dashboard, isLoading } = useDashboardQuery()
  return { dashboard: dashboard ?? null, loading: isLoading }
}

export function useArticles() {
  const {
    articlesPage,
    activeCategory,
    activeTag,
    activeRelevance,
    setActiveCategory,
    setActiveTag,
    setActiveRelevance,
    setArticlesPage,
  } = usePaperStore()

  const { data, isLoading } = useArticlesQuery({
    page: articlesPage,
    category: activeCategory,
    tag: activeTag,
    relevance: activeRelevance,
  })

  const deleteMutation = useDeleteArticleMutation()

  const articles = data?.items ?? []
  const total = data?.total ?? 0

  const allCategories = [...new Set(articles.flatMap((a) => a.categories))].sort()
  const allTags = [...new Set(articles.flatMap((a) => a.tags))].sort()

  return {
    articles,
    total,
    page: articlesPage,
    pageSize: ARTICLES_PAGE_SIZE,
    loading: isLoading && articles.length === 0,
    activeCategory,
    activeTag,
    activeRelevance,
    allCategories,
    allTags,
    fetchArticles: setArticlesPage,
    deleteArticle: (id: string) => deleteMutation.mutate(id),
    setActiveCategory,
    setActiveTag,
    setActiveRelevance,
  }
}

export function useArticleDetail(id: string | undefined) {
  const { data: article, isLoading: articleLoading } = useArticleQuery(id)
  const { data: digest, isLoading: digestLoading } = useDigestQuery(id)
  const { data: annotations = [] } = useAnnotationsQuery(id)
  const addMutation = useAddAnnotationMutation(id ?? '')

  return {
    article: article ?? null,
    loading: articleLoading,
    digest: digest ?? null,
    digestLoading,
    annotations,
    addAnnotation: (data: AnnotationCreate) =>
      id ? addMutation.mutateAsync(data) : Promise.resolve(),
  }
}

export function useSearch() {
  const { searchQuery, setSearchQuery, clearSearch } = usePaperStore()
  const { data: results = [], isLoading } = useSearchArticlesQuery(searchQuery)

  return {
    query: searchQuery,
    results,
    loading: isLoading,
    setQuery: setSearchQuery,
    search: setSearchQuery,
    clear: clearSearch,
  }
}

import { useEffect } from 'react'
import { usePaperStore } from '../stores'
import type { AnnotationCreate } from '../types'

const STALE_MS = 5 * 60 * 1000

export function useDashboard() {
  const { dashboard, dashboardLoading, dashboardFetchedAt, fetchDashboard } = usePaperStore()

  useEffect(() => {
    if (!dashboard || Date.now() - dashboardFetchedAt > STALE_MS) fetchDashboard()
  }, [dashboard, dashboardFetchedAt, fetchDashboard])

  return { dashboard, loading: dashboardLoading && !dashboard }
}

export function useArticles() {
  const {
    articles,
    articlesTotal,
    articlesPage,
    articlesPageSize,
    articlesLoading,
    activeCategory,
    activeTag,
    activeRelevance,
    allCategories,
    allTags,
    fetchArticles,
    deleteArticle,
    setActiveCategory,
    setActiveTag,
    setActiveRelevance,
  } = usePaperStore()

  useEffect(() => {
    fetchArticles()
  }, [fetchArticles])

  return {
    articles,
    total: articlesTotal,
    page: articlesPage,
    pageSize: articlesPageSize,
    loading: articlesLoading && articles.length === 0,
    activeCategory,
    activeTag,
    activeRelevance,
    allCategories,
    allTags,
    fetchArticles,
    deleteArticle,
    setActiveCategory,
    setActiveTag,
    setActiveRelevance,
  }
}

export function useArticleDetail(id: string | undefined) {
  const {
    selectedArticle,
    articleDetailLoading,
    fetchArticleById,
    clearSelectedArticle,
    selectedDigest,
    digestLoading,
    fetchDigest,
    annotations,
    annotationsLoading,
    fetchAnnotations,
    addAnnotation,
  } = usePaperStore()

  useEffect(() => {
    if (id) {
      fetchArticleById(id)
      fetchDigest(id)
      fetchAnnotations(id)
    }
    return () => clearSelectedArticle()
  }, [id, fetchArticleById, fetchDigest, fetchAnnotations, clearSelectedArticle])

  return {
    article: selectedArticle,
    loading: articleDetailLoading,
    digest: selectedDigest,
    digestLoading,
    annotations,
    annotationsLoading,
    addAnnotation: (data: AnnotationCreate) => (id ? addAnnotation(id, data) : Promise.resolve()),
  }
}

export function useSearch() {
  const { searchQuery, searchResults, searchLoading, setSearchQuery, searchArticles, clearSearch } =
    usePaperStore()

  return {
    query: searchQuery,
    results: searchResults,
    loading: searchLoading,
    setQuery: setSearchQuery,
    search: searchArticles,
    clear: clearSearch,
  }
}

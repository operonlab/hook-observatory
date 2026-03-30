import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'
import { paperApi } from '../api/client'
import type {
  Annotation,
  AnnotationCreate,
  Article,
  DashboardData,
  Digest,
  SearchResult,
} from '../types'

interface PaperState {
  // Dashboard
  dashboard: DashboardData | null
  dashboardLoading: boolean
  dashboardFetchedAt: number

  // Articles
  articles: Article[]
  articlesTotal: number
  articlesPage: number
  articlesPageSize: number
  articlesLoading: boolean
  articlesFetchedAt: number
  selectedArticle: Article | null
  articleDetailLoading: boolean
  activeCategory: string | null
  activeTag: string | null
  activeRelevance: string | null
  allCategories: string[]
  allTags: string[]

  // Digest
  selectedDigest: Digest | null
  digestLoading: boolean

  // Annotations
  annotations: Annotation[]
  annotationsLoading: boolean

  // Search
  searchQuery: string
  searchResults: SearchResult[]
  searchLoading: boolean

  // Global
  error: string | null

  // Actions — Dashboard
  fetchDashboard: () => Promise<void>

  // Actions — Articles
  fetchArticles: (page?: number) => Promise<void>
  fetchArticleById: (id: string) => Promise<void>
  deleteArticle: (id: string) => Promise<void>
  setActiveCategory: (category: string | null) => void
  setActiveTag: (tag: string | null) => void
  setActiveRelevance: (relevance: string | null) => void
  clearSelectedArticle: () => void

  // Actions — Digest
  fetchDigest: (articleId: string) => Promise<void>

  // Actions — Annotations
  fetchAnnotations: (articleId: string) => Promise<void>
  addAnnotation: (articleId: string, data: AnnotationCreate) => Promise<void>

  // Actions — Search
  setSearchQuery: (query: string) => void
  searchArticles: (query: string) => Promise<void>
  clearSearch: () => void
}

export const usePaperStore = create<PaperState>()(
  devtools(
    persist(
      (set, get) => ({
        // Dashboard
        dashboard: null,
        dashboardLoading: false,
        dashboardFetchedAt: 0,

        // Articles
        articles: [],
        articlesTotal: 0,
        articlesPage: 1,
        articlesPageSize: 20,
        articlesLoading: false,
        articlesFetchedAt: 0,
        selectedArticle: null,
        articleDetailLoading: false,
        activeCategory: null,
        activeTag: null,
        activeRelevance: null,
        allCategories: [],
        allTags: [],

        // Digest
        selectedDigest: null,
        digestLoading: false,

        // Annotations
        annotations: [],
        annotationsLoading: false,

        // Search
        searchQuery: '',
        searchResults: [],
        searchLoading: false,

        // Global
        error: null,

        // ── Dashboard ──

        fetchDashboard: async () => {
          set({ dashboardLoading: true, error: null })
          try {
            const data = await paperApi.getDashboard()
            set({ dashboard: data, dashboardFetchedAt: Date.now() })
          } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to fetch dashboard' })
          } finally {
            set({ dashboardLoading: false })
          }
        },

        // ── Articles ──

        fetchArticles: async (page?: number) => {
          const p = page ?? get().articlesPage
          const { articlesPageSize, activeCategory, activeTag, activeRelevance } = get()
          set({ articlesLoading: true, error: null, articlesPage: p })
          try {
            const res = await paperApi.listFiltered({
              category: activeCategory ?? undefined,
              tag: activeTag ?? undefined,
              relevance: activeRelevance ?? undefined,
              page: p,
              pageSize: articlesPageSize,
            })
            set({ articles: res.items, articlesTotal: res.total, articlesFetchedAt: Date.now() })

            // Extract unique categories and tags
            const cats = new Set<string>()
            const tags = new Set<string>()
            res.items.forEach((a) => {
              a.categories.forEach((c) => cats.add(c))
              a.tags.forEach((t) => tags.add(t))
            })
            set((state) => {
              const mergedCats = new Set([...state.allCategories, ...cats])
              const mergedTags = new Set([...state.allTags, ...tags])
              return {
                allCategories: Array.from(mergedCats).sort(),
                allTags: Array.from(mergedTags).sort(),
              }
            })
          } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to fetch articles' })
          } finally {
            set({ articlesLoading: false })
          }
        },

        fetchArticleById: async (id: string) => {
          set({ articleDetailLoading: true, error: null })
          try {
            const article = await paperApi.get(id)
            set({ selectedArticle: article })
          } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to fetch article' })
          } finally {
            set({ articleDetailLoading: false })
          }
        },

        deleteArticle: async (id: string) => {
          set({ error: null })
          try {
            await paperApi.delete(id)
            set((state) => ({
              articles: state.articles.filter((a) => a.id !== id),
              articlesTotal: state.articlesTotal - 1,
              selectedArticle: state.selectedArticle?.id === id ? null : state.selectedArticle,
            }))
          } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to delete article' })
          }
        },

        setActiveCategory: (category) => {
          set({ activeCategory: category, articlesPage: 1 })
          get().fetchArticles(1)
        },

        setActiveTag: (tag) => {
          set({ activeTag: tag, articlesPage: 1 })
          get().fetchArticles(1)
        },

        setActiveRelevance: (relevance) => {
          set({ activeRelevance: relevance, articlesPage: 1 })
          get().fetchArticles(1)
        },

        clearSelectedArticle: () =>
          set({ selectedArticle: null, selectedDigest: null, annotations: [] }),

        // ── Digest ──

        fetchDigest: async (articleId: string) => {
          set({ digestLoading: true })
          try {
            const digest = await paperApi.getDigest(articleId)
            set({ selectedDigest: digest })
          } catch {
            // 404 is expected when no digest exists yet — silently clear
            set({ selectedDigest: null })
          } finally {
            set({ digestLoading: false })
          }
        },

        // ── Annotations ──

        fetchAnnotations: async (articleId: string) => {
          set({ annotationsLoading: true, error: null })
          try {
            const res = await paperApi.getAnnotations(articleId)
            // Handle both paginated { items: [...] } and plain array responses
            const list = Array.isArray(res) ? res : ((res as any).items ?? [])
            set({ annotations: list })
          } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to fetch annotations' })
          } finally {
            set({ annotationsLoading: false })
          }
        },

        addAnnotation: async (articleId: string, data: AnnotationCreate) => {
          set({ error: null })
          try {
            const annotation = await paperApi.createAnnotation(articleId, data)
            set((state) => ({ annotations: [...state.annotations, annotation] }))
          } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to add annotation' })
          }
        },

        // ── Search ──

        setSearchQuery: (query) => set({ searchQuery: query }),

        searchArticles: async (query: string) => {
          if (!query.trim()) return
          set({ searchLoading: true, searchQuery: query, error: null })
          try {
            const results = await paperApi.search(query, 10, 0.3)
            set({ searchResults: results })
          } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Search failed' })
          } finally {
            set({ searchLoading: false })
          }
        },

        clearSearch: () => set({ searchQuery: '', searchResults: [] }),
      }),
      {
        name: 'paper-cache',
        partialize: (state) => ({
          dashboard: state.dashboard,
          dashboardFetchedAt: state.dashboardFetchedAt,
          articles: state.articles,
          articlesTotal: state.articlesTotal,
          articlesFetchedAt: state.articlesFetchedAt,
          allCategories: state.allCategories,
          allTags: state.allTags,
        }),
      },
    ),
    { name: 'paperStore' },
  ),
)

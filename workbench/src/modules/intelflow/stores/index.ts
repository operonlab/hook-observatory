import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'
import { handleStoreError } from '@/shared/utils/storeHelpers'
import type { PaginatedResponse } from '@/types'
import { intelflowApi } from '../api/client'
import type { DashboardData, Report, SearchResult, TimelineEntry, Topic } from '../types'

type NavPage = 'dashboard' | 'reports' | 'qa' | 'topics'

interface IntelflowState {
  // Navigation
  activePage: NavPage

  // Dashboard
  dashboard: DashboardData | null
  dashboardLoading: boolean
  dashboardFetchedAt: number

  // Timeline
  timeline: TimelineEntry[]
  timelineLoading: boolean
  timelineFetchedAt: number

  // Reports
  reports: Report[]
  reportsTotal: number
  reportsPage: number
  reportsPageSize: number
  reportsLoading: boolean
  reportsFetchedAt: number
  selectedReport: Report | null
  reportDetailLoading: boolean
  activeTag: string | null
  allTags: string[]

  // Topics
  topics: Topic[]
  topicsTotal: number
  topicsLoading: boolean
  topicsFetchedAt: number
  activeTopic: string | null

  // Search / QA
  searchQuery: string
  searchResults: SearchResult[]
  searchLoading: boolean
  qaAnswer: string | null
  qaLoading: boolean

  // Global
  error: string | null

  // Actions — Navigation
  setActivePage: (page: NavPage) => void

  // Actions — Dashboard
  fetchDashboard: () => Promise<void>
  fetchTimeline: (days?: number) => Promise<void>

  // Actions — Reports
  fetchReports: (page?: number) => Promise<void>
  fetchReportById: (id: string) => Promise<void>
  deleteReport: (id: string) => Promise<void>
  setActiveTag: (tag: string | null) => void
  clearSelectedReport: () => void

  // Actions — Topics
  fetchTopics: () => Promise<void>
  setActiveTopic: (topic: string | null) => void

  // Actions — Search / QA
  setSearchQuery: (query: string) => void
  searchReports: (query: string) => Promise<void>
  clearSearch: () => void
}

export const useIntelflowStore = create<IntelflowState>()(
  devtools(
    persist(
      (set, get) => ({
        // Navigation
        activePage: 'dashboard',

        // Dashboard
        dashboard: null,
        dashboardLoading: false,
        dashboardFetchedAt: 0,

        // Timeline
        timeline: [],
        timelineLoading: false,
        timelineFetchedAt: 0,

        // Reports
        reports: [],
        reportsTotal: 0,
        reportsPage: 1,
        reportsPageSize: 20,
        reportsLoading: false,
        reportsFetchedAt: 0,
        selectedReport: null,
        reportDetailLoading: false,
        activeTag: null,
        allTags: [],

        // Topics
        topics: [],
        topicsTotal: 0,
        topicsLoading: false,
        topicsFetchedAt: 0,
        activeTopic: null,

        // Search / QA
        searchQuery: '',
        searchResults: [],
        searchLoading: false,
        qaAnswer: null,
        qaLoading: false,

        // Global
        error: null,

        // ── Navigation ──

        setActivePage: (page) => set({ activePage: page }),

        // ── Dashboard ──

        fetchDashboard: async () => {
          set({ dashboardLoading: true, error: null })
          try {
            const data = await intelflowApi.getDashboard()
            set({ dashboard: data, dashboardFetchedAt: Date.now() })
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch dashboard')
          } finally {
            set({ dashboardLoading: false })
          }
        },

        fetchTimeline: async (days = 30) => {
          set({ timelineLoading: true, error: null })
          try {
            const data = await intelflowApi.getTimeline(days)
            set({ timeline: data.entries, timelineFetchedAt: Date.now() })
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch timeline')
          } finally {
            set({ timelineLoading: false })
          }
        },

        // ── Reports ──

        fetchReports: async (page?: number) => {
          const p = page ?? get().reportsPage
          const { reportsPageSize, activeTag } = get()
          set({ reportsLoading: true, error: null, reportsPage: p })
          try {
            let res: PaginatedResponse<Report>
            if (activeTag) {
              res = await intelflowApi.listByTags([activeTag], p, reportsPageSize)
            } else {
              res = await intelflowApi.list(p, reportsPageSize)
            }
            set({ reports: res.items, reportsTotal: res.total, reportsFetchedAt: Date.now() })

            // Extract unique tags
            const tags = new Set<string>()
            res.items.forEach((r) => r.tags.forEach((t) => tags.add(t)))
            set((state) => {
              const merged = new Set([...state.allTags, ...tags])
              return { allTags: Array.from(merged).sort() }
            })
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch reports')
          } finally {
            set({ reportsLoading: false })
          }
        },

        fetchReportById: async (id: string) => {
          set({ reportDetailLoading: true, error: null })
          try {
            const report = await intelflowApi.get(id)
            set({ selectedReport: report })
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch report')
          } finally {
            set({ reportDetailLoading: false })
          }
        },

        deleteReport: async (id: string) => {
          set({ error: null })
          try {
            await intelflowApi.delete(id)
            set((state) => ({
              reports: state.reports.filter((r) => r.id !== id),
              reportsTotal: state.reportsTotal - 1,
              selectedReport: state.selectedReport?.id === id ? null : state.selectedReport,
            }))
          } catch (err) {
            console.error('deleteReport failed:', err)
            handleStoreError(set, err, 'Failed to delete report')
          }
        },

        setActiveTag: (tag) => {
          set({ activeTag: tag, reportsPage: 1 })
          get().fetchReports(1)
        },

        clearSelectedReport: () => set({ selectedReport: null }),

        // ── Topics ──

        fetchTopics: async () => {
          set({ topicsLoading: true, error: null })
          try {
            const res = await intelflowApi.listTopics(1, 200)
            set({ topics: res.items, topicsTotal: res.total, topicsFetchedAt: Date.now() })
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch topics')
          } finally {
            set({ topicsLoading: false })
          }
        },

        setActiveTopic: (topic) => set({ activeTopic: topic }),

        // ── Search / QA ──

        setSearchQuery: (query) => set({ searchQuery: query }),

        searchReports: async (query: string) => {
          if (!query.trim()) return
          set({ searchLoading: true, searchQuery: query, error: null })
          try {
            const results = await intelflowApi.search(query, 10, 0.3)
            set({ searchResults: results })
          } catch (err) {
            handleStoreError(set, err, 'Search failed')
          } finally {
            set({ searchLoading: false })
          }
        },

        clearSearch: () => set({ searchQuery: '', searchResults: [], qaAnswer: null }),
      }),
      {
        name: 'intelflow-cache',
        partialize: (state) => ({
          dashboard: state.dashboard,
          dashboardFetchedAt: state.dashboardFetchedAt,
          timeline: state.timeline,
          timelineFetchedAt: state.timelineFetchedAt,
          reports: state.reports,
          reportsTotal: state.reportsTotal,
          reportsFetchedAt: state.reportsFetchedAt,
          topics: state.topics,
          topicsTotal: state.topicsTotal,
          topicsFetchedAt: state.topicsFetchedAt,
          allTags: state.allTags,
        }),
      },
    ),
    { name: 'intelflowStore' },
  ),
)

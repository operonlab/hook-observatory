import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { briefingApi } from '../api/client'
import type { Analyst, Briefing, BriefingTopic, DailySummary } from '../types'

type NavPage = 'today' | 'history' | 'config'

interface BriefingState {
  // Navigation
  activePage: NavPage

  // Today / Daily summary
  todaySummary: DailySummary | null
  todayLoading: boolean
  todayFetchedAt: number
  selectedDate: string // YYYY-MM-DD

  // Briefing detail (by date)
  selectedBriefings: Briefing[]
  detailLoading: boolean

  // History
  briefings: Briefing[]
  briefingsTotal: number
  briefingsPage: number
  briefingsLoading: boolean
  briefingsFetchedAt: number

  // Config
  topics: BriefingTopic[]
  topicsLoading: boolean
  topicsFetchedAt: number
  analysts: Analyst[]
  analystsLoading: boolean
  analystsFetchedAt: number

  // Global
  error: string | null

  // Actions
  setActivePage: (page: NavPage) => void
  setSelectedDate: (date: string) => void

  fetchTodaySummary: (date: string) => Promise<void>
  fetchBriefingsByDate: (date: string) => Promise<void>
  clearSelectedBriefings: () => void

  fetchBriefings: (page?: number) => Promise<void>

  fetchTopics: () => Promise<void>
  fetchAnalysts: () => Promise<void>
}

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export const useBriefingStore = create<BriefingState>()(
  persist(
    (set, get) => ({
      activePage: 'today',
      todaySummary: null,
      todayLoading: false,
      todayFetchedAt: 0,
      selectedDate: todayStr(),

      selectedBriefings: [],
      detailLoading: false,

      briefings: [],
      briefingsTotal: 0,
      briefingsPage: 1,
      briefingsLoading: false,
      briefingsFetchedAt: 0,

      topics: [],
      topicsLoading: false,
      topicsFetchedAt: 0,
      analysts: [],
      analystsLoading: false,
      analystsFetchedAt: 0,

      error: null,

      setActivePage: (page) => set({ activePage: page }),
      setSelectedDate: (date) => set({ selectedDate: date }),

      fetchTodaySummary: async (date: string) => {
        set({ todayLoading: true, error: null })
        try {
          const summary = await briefingApi.getDailySummary(date)
          set({ todaySummary: summary, todayFetchedAt: Date.now() })
        } catch (err) {
          set({ error: err instanceof Error ? err.message : 'Failed to fetch summary' })
        } finally {
          set({ todayLoading: false })
        }
      },

      fetchBriefingsByDate: async (date: string) => {
        set({ detailLoading: true, error: null })
        try {
          const result = await briefingApi.getBriefingsByDate(date)
          set({ selectedBriefings: result })
        } catch (err) {
          set({ error: err instanceof Error ? err.message : 'Failed to fetch briefing' })
        } finally {
          set({ detailLoading: false })
        }
      },

      clearSelectedBriefings: () => set({ selectedBriefings: [] }),

      fetchBriefings: async (page?: number) => {
        const p = page ?? get().briefingsPage
        set({ briefingsLoading: true, error: null, briefingsPage: p })
        try {
          const res = await briefingApi.listBriefings(p, 20)
          set({ briefings: res.items, briefingsTotal: res.total, briefingsFetchedAt: Date.now() })
        } catch (err) {
          set({ error: err instanceof Error ? err.message : 'Failed to fetch briefings' })
        } finally {
          set({ briefingsLoading: false })
        }
      },

      fetchTopics: async () => {
        set({ topicsLoading: true, error: null })
        try {
          const res = await briefingApi.listTopics(1, 100)
          set({ topics: res.items, topicsFetchedAt: Date.now() })
        } catch (err) {
          set({ error: err instanceof Error ? err.message : 'Failed to fetch topics' })
        } finally {
          set({ topicsLoading: false })
        }
      },

      fetchAnalysts: async () => {
        set({ analystsLoading: true, error: null })
        try {
          const result = await briefingApi.listAnalysts()
          set({ analysts: result, analystsFetchedAt: Date.now() })
        } catch (err) {
          set({ error: err instanceof Error ? err.message : 'Failed to fetch analysts' })
        } finally {
          set({ analystsLoading: false })
        }
      },
    }),
    {
      name: 'briefing-cache',
      partialize: (state) => ({
        todaySummary: state.todaySummary,
        todayFetchedAt: state.todayFetchedAt,
        selectedDate: state.selectedDate,
        briefings: state.briefings,
        briefingsTotal: state.briefingsTotal,
        briefingsFetchedAt: state.briefingsFetchedAt,
        topics: state.topics,
        topicsFetchedAt: state.topicsFetchedAt,
        analysts: state.analysts,
        analystsFetchedAt: state.analystsFetchedAt,
      }),
    },
  ),
)

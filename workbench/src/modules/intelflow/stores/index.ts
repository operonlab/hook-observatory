import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

interface IntelflowUIState {
  activeTag: string | null
  reportsPage: number
  searchQuery: string
  activeTopic: string | null

  setActiveTag: (tag: string | null) => void
  setReportsPage: (page: number) => void
  setSearchQuery: (query: string) => void
  setActiveTopic: (topic: string | null) => void
  clearSearch: () => void
}

export const useIntelflowStore = create<IntelflowUIState>()(
  devtools(
    (set) => ({
      activeTag: null,
      reportsPage: 1,
      searchQuery: '',
      activeTopic: null,

      setActiveTag: (tag) => set({ activeTag: tag, reportsPage: 1 }),
      setReportsPage: (page) => set({ reportsPage: page }),
      setSearchQuery: (query) => set({ searchQuery: query }),
      setActiveTopic: (topic) => set({ activeTopic: topic }),
      clearSearch: () => set({ searchQuery: '' }),
    }),
    { name: 'intelflowStore' },
  ),
)

import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { withJournal } from '@/shared/utils/journalMiddleware'

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
    withJournal((set) => ({
      activeTag: null,
      reportsPage: 1,
      searchQuery: '',
      activeTopic: null,

      setActiveTag: (tag) =>
        set({ activeTag: tag, reportsPage: 1 }, false, 'intelflow/setActiveTag'),
      setReportsPage: (page) => set({ reportsPage: page }, false, 'intelflow/setReportsPage'),
      setSearchQuery: (query) => set({ searchQuery: query }, false, 'intelflow/setSearchQuery'),
      setActiveTopic: (topic) => set({ activeTopic: topic }, false, 'intelflow/setActiveTopic'),
      clearSearch: () => set({ searchQuery: '' }, false, 'intelflow/clearSearch'),
    })),
    { name: 'intelflowStore' },
  ),
)

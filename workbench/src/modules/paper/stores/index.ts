import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { withJournal } from '@/shared/utils/journalMiddleware'

interface PaperUIState {
  // Article filters
  activeCategory: string | null
  activeTag: string | null
  activeRelevance: string | null
  articlesPage: number

  // Search
  searchQuery: string

  // Actions
  setActiveCategory: (category: string | null) => void
  setActiveTag: (tag: string | null) => void
  setActiveRelevance: (relevance: string | null) => void
  setArticlesPage: (page: number) => void
  setSearchQuery: (query: string) => void
  clearSearch: () => void
}

export const usePaperStore = create<PaperUIState>()(
  devtools(
    withJournal((set) => ({
      activeCategory: null,
      activeTag: null,
      activeRelevance: null,
      articlesPage: 1,
      searchQuery: '',

      setActiveCategory: (category) =>
        set({ activeCategory: category, articlesPage: 1 }, false, 'paper/setActiveCategory'),
      setActiveTag: (tag) =>
        set({ activeTag: tag, articlesPage: 1 }, false, 'paper/setActiveTag'),
      setActiveRelevance: (relevance) =>
        set({ activeRelevance: relevance, articlesPage: 1 }, false, 'paper/setActiveRelevance'),
      setArticlesPage: (page) => set({ articlesPage: page }, false, 'paper/setArticlesPage'),
      setSearchQuery: (query) => set({ searchQuery: query }, false, 'paper/setSearchQuery'),
      clearSearch: () => set({ searchQuery: '' }, false, 'paper/clearSearch'),
    })),
    { name: 'paperStore' },
  ),
)

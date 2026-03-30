import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

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
    (set) => ({
      activeCategory: null,
      activeTag: null,
      activeRelevance: null,
      articlesPage: 1,
      searchQuery: '',

      setActiveCategory: (category) => set({ activeCategory: category, articlesPage: 1 }),
      setActiveTag: (tag) => set({ activeTag: tag, articlesPage: 1 }),
      setActiveRelevance: (relevance) => set({ activeRelevance: relevance, articlesPage: 1 }),
      setArticlesPage: (page) => set({ articlesPage: page }),
      setSearchQuery: (query) => set({ searchQuery: query }),
      clearSearch: () => set({ searchQuery: '' }),
    }),
    { name: 'paperStore' },
  ),
)

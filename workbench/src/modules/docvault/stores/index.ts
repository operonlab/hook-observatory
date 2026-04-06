import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { withJournal } from '@/shared/utils/journalMiddleware'

interface DocvaultUIState {
  // Document filters
  activeTag: string | null
  activeStatus: string | null
  documentsPage: number

  // QA
  qaQuestion: string
  qaMode: 'factual' | 'mixed'
  qaDomain: string

  // Search
  searchQuery: string

  // Gap filters
  gapStatus: string

  // Actions
  setActiveTag: (tag: string | null) => void
  setActiveStatus: (status: string | null) => void
  setDocumentsPage: (page: number) => void
  setQAQuestion: (question: string) => void
  setQAMode: (mode: 'factual' | 'mixed') => void
  setQADomain: (domain: string) => void
  setSearchQuery: (query: string) => void
  setGapStatus: (status: string) => void
  clearSearch: () => void
}

export const useDocvaultStore = create<DocvaultUIState>()(
  devtools(
    withJournal((set) => ({
      activeTag: null,
      activeStatus: null,
      documentsPage: 1,
      qaQuestion: '',
      qaMode: 'factual',
      qaDomain: 'default',
      searchQuery: '',
      gapStatus: 'pending',

      setActiveTag: (tag) =>
        set({ activeTag: tag, documentsPage: 1 }, false, 'docvault/setActiveTag'),
      setActiveStatus: (status) =>
        set({ activeStatus: status, documentsPage: 1 }, false, 'docvault/setActiveStatus'),
      setDocumentsPage: (page) =>
        set({ documentsPage: page }, false, 'docvault/setDocumentsPage'),
      setQAQuestion: (question) =>
        set({ qaQuestion: question }, false, 'docvault/setQAQuestion'),
      setQAMode: (mode) =>
        set({ qaMode: mode }, false, 'docvault/setQAMode'),
      setQADomain: (domain) =>
        set({ qaDomain: domain }, false, 'docvault/setQADomain'),
      setSearchQuery: (query) =>
        set({ searchQuery: query }, false, 'docvault/setSearchQuery'),
      setGapStatus: (status) =>
        set({ gapStatus: status }, false, 'docvault/setGapStatus'),
      clearSearch: () =>
        set({ searchQuery: '' }, false, 'docvault/clearSearch'),
    })),
    { name: 'docvaultStore' },
  ),
)

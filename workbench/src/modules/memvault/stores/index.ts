import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { withJournal } from '@/shared/utils/journalMiddleware'
import type { MemoryBlock } from '@/types'
import type { BlockFilters, GalaxyLayer, Lens, ViewMode } from '../types'

const DEFAULT_FILTERS: BlockFilters = {
  blockType: null,
  tag: null,
  sortField: 'updated_at',
  sortOrder: 'desc',
}

interface MemvaultState {
  viewMode: ViewMode
  filters: BlockFilters
  page: number
  pageSize: number
  selectedBlock: MemoryBlock | null
  searchQuery: string
  kg_galaxyLayers: Set<GalaxyLayer>
  activeLens: Lens
  showAdvancedQuery: boolean

  selectBlock: (block: MemoryBlock | null) => void
  setPage: (page: number) => void
  setFilters: (filters: Partial<BlockFilters>) => void
  setViewMode: (mode: ViewMode) => void
  setSearchQuery: (query: string) => void
  clearSearch: () => void
  setKgGalaxyLayers: (layers: Set<GalaxyLayer>) => void
  setActiveLens: (lens: Lens) => void
  toggleAdvancedQuery: () => void
}

export const useMemvaultStore = create<MemvaultState>()(
  devtools(
    withJournal((set) => ({
      viewMode: 'grid',
      filters: DEFAULT_FILTERS,
      page: 1,
      pageSize: 20,
      selectedBlock: null,
      searchQuery: '',
      kg_galaxyLayers: new Set<GalaxyLayer>(['blocks', 'summaries', 'communities']),
      activeLens: 'recall',
      showAdvancedQuery: false,

      selectBlock: (block) => set({ selectedBlock: block }, false, 'memvault/selectBlock'),
      setPage: (page) => set({ page }, false, 'memvault/setPage'),
      setFilters: (filters) =>
        set(
          (state) => ({ filters: { ...state.filters, ...filters }, page: 1 }),
          false,
          'memvault/setFilters',
        ),
      setViewMode: (mode) => set({ viewMode: mode }, false, 'memvault/setViewMode'),
      setSearchQuery: (query) => set({ searchQuery: query }, false, 'memvault/setSearchQuery'),
      clearSearch: () => set({ searchQuery: '' }, false, 'memvault/clearSearch'),
      setKgGalaxyLayers: (layers) =>
        set({ kg_galaxyLayers: layers }, false, 'memvault/setKgGalaxyLayers'),
      setActiveLens: (lens) => set({ activeLens: lens }, false, 'memvault/setActiveLens'),
      toggleAdvancedQuery: () =>
        set((s) => ({ showAdvancedQuery: !s.showAdvancedQuery }), false, 'memvault/toggleAdvancedQuery'),
    })),
    { name: 'memvaultStore' },
  ),
)

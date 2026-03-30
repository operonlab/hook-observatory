import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'
import { handleStoreError } from '@/shared/utils/storeHelpers'
import type {
  KASProfile,
  MemoryBlock,
  MemoryBlockCreate,
  MemoryBlockUpdate,
  PaginatedResponse,
  SemanticSearchResult,
} from '@/types'
import { kgApi, memvaultApi } from '../api'
import type {
  AttitudeFact,
  BlockFilters,
  BrowserTab,
  CascadeRecallResult,
  Community,
  CommunityDetail,
  CommunitySummary,
  GalaxyLayer,
  SkillProfile,
  Triple,
  ViewMode,
} from '../types'

const DEFAULT_FILTERS: BlockFilters = {
  blockType: null,
  tag: null,
  sortField: 'updated_at',
  sortOrder: 'desc',
}

/** Stale-While-Revalidate TTL in ms (5 minutes) */
const STALE_TTL = 5 * 60 * 1000

/** Per-data-section freshness timestamps */
interface FetchedAt {
  blocks: number
  profile: number
  kg_triples: number
  kg_communities: number
  kg_summaries: number
  kg_attitudes: number
  kg_skills: number
}

const EMPTY_FETCHED_AT: FetchedAt = {
  blocks: 0,
  profile: 0,
  kg_triples: 0,
  kg_communities: 0,
  kg_summaries: 0,
  kg_attitudes: 0,
  kg_skills: 0,
}

interface MemvaultState {
  // Data
  blocks: MemoryBlock[]
  total: number
  page: number
  pageSize: number
  selectedBlock: MemoryBlock | null
  profile: KASProfile | null

  // Search
  searchQuery: string
  searchResults: SemanticSearchResult[]
  isSearching: boolean

  // UI state
  viewMode: ViewMode
  filters: BlockFilters
  loading: boolean
  error: string | null

  // KG Data
  kg_triples: Triple[]
  kg_triplesTotal: number
  kg_triplesPage: number
  kg_communities: Community[]
  kg_selectedCommunity: CommunityDetail | null
  kg_summaries: CommunitySummary[]
  kg_attitudes: AttitudeFact[]
  kg_attitudeHistory: AttitudeFact[]
  kg_skills: SkillProfile[]
  kg_cascadeResult: CascadeRecallResult | null

  // KG UI
  kg_activeTab: BrowserTab
  kg_galaxyLayers: Set<GalaxyLayer>
  kg_loading: boolean

  // SWR: freshness tracking
  _fetchedAt: FetchedAt

  // SWR: memo caches for on-demand detail fetches
  _communityDetailCache: Record<string, CommunityDetail>
  _attitudeHistoryCache: Record<string, AttitudeFact[]>

  // SWR helpers
  isStale: (key: keyof FetchedAt) => boolean

  // Actions
  fetchBlocks: () => Promise<void>
  fetchProfile: () => Promise<void>
  createBlock: (data: MemoryBlockCreate) => Promise<void>
  updateBlock: (id: string, data: MemoryBlockUpdate) => Promise<void>
  deleteBlock: (id: string) => Promise<void>
  selectBlock: (block: MemoryBlock | null) => void
  setPage: (page: number) => void
  setFilters: (filters: Partial<BlockFilters>) => void
  setViewMode: (mode: ViewMode) => void
  setSearchQuery: (query: string) => void
  searchSemantic: () => Promise<void>
  clearSearch: () => void

  // KG Actions
  setKgActiveTab: (tab: BrowserTab) => void
  setKgGalaxyLayers: (layers: Set<GalaxyLayer>) => void
  fetchTriples: (page?: number) => Promise<void>
  fetchCommunities: () => Promise<void>
  fetchCommunityDetail: (id: string) => Promise<void>
  fetchSummaries: () => Promise<void>
  fetchAttitudes: (category?: string) => Promise<void>
  fetchAttitudeHistory: (factId: string) => Promise<void>
  fetchSkillProfiles: () => Promise<void>
  cascadeRecall: (q: string) => Promise<void>
  clearCascadeResult: () => void

  // KG CRUD
  deleteTriple: (id: string) => Promise<void>
  deleteAttitude: (id: string) => Promise<void>
  updateAttitude: (id: string, data: { fact: string; category: string }) => Promise<void>
  // Profile
  recalculateProfile: () => Promise<void>
}

export const useMemvaultStore = create<MemvaultState>()(
  devtools(
    persist(
      (set, get) => ({
        // Data
        blocks: [],
        total: 0,
        page: 1,
        pageSize: 20,
        selectedBlock: null,
        profile: null,

        // Search
        searchQuery: '',
        searchResults: [],
        isSearching: false,

        // UI state
        viewMode: 'grid',
        filters: DEFAULT_FILTERS,
        loading: false,
        error: null,

        // KG Data
        kg_triples: [],
        kg_triplesTotal: 0,
        kg_triplesPage: 1,
        kg_communities: [],
        kg_selectedCommunity: null,
        kg_summaries: [],
        kg_attitudes: [],
        kg_attitudeHistory: [],
        kg_skills: [],
        kg_cascadeResult: null,

        // KG UI
        kg_activeTab: 'blocks',
        kg_galaxyLayers: new Set<GalaxyLayer>(['blocks', 'summaries', 'communities']),
        kg_loading: false,

        // SWR
        _fetchedAt: { ...EMPTY_FETCHED_AT },
        _communityDetailCache: {},
        _attitudeHistoryCache: {},

        isStale: (key: keyof FetchedAt) => {
          const ts = get()._fetchedAt[key]
          return ts === 0 || Date.now() - ts > STALE_TTL
        },

        // Actions

        fetchBlocks: async () => {
          const { page, pageSize, filters } = get()
          set({ loading: true, error: null })
          try {
            let response: PaginatedResponse<MemoryBlock>
            if (filters.tag !== null) {
              response = await memvaultApi.listByTag(filters.tag, page, pageSize)
            } else if (filters.blockType !== null) {
              response = await memvaultApi.listByType(filters.blockType, page, pageSize)
            } else {
              response = await memvaultApi.list(page, pageSize)
            }
            set((s) => ({
              blocks: response.items,
              total: response.total,
              _fetchedAt: { ...s._fetchedAt, blocks: Date.now() },
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch blocks')
          } finally {
            set({ loading: false })
          }
        },

        fetchProfile: async () => {
          set({ loading: true, error: null })
          try {
            const profile = await memvaultApi.getProfile()
            set((s) => ({
              profile,
              _fetchedAt: { ...s._fetchedAt, profile: Date.now() },
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch profile')
          } finally {
            set({ loading: false })
          }
        },

        createBlock: async (data: MemoryBlockCreate) => {
          set({ loading: true, error: null })
          try {
            await memvaultApi.create(data)
            await get().fetchBlocks()
          } catch (err) {
            handleStoreError(set, err, 'Failed to create block')
          } finally {
            set({ loading: false })
          }
        },

        updateBlock: async (id: string, data: MemoryBlockUpdate) => {
          set({ loading: true, error: null })
          try {
            const updated = await memvaultApi.update(id, data)
            set((state) => ({
              blocks: state.blocks.map((b) => (b.id === id ? updated : b)),
              selectedBlock: state.selectedBlock?.id === id ? updated : state.selectedBlock,
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to update block')
          } finally {
            set({ loading: false })
          }
        },

        deleteBlock: async (id: string) => {
          set({ loading: true, error: null })
          try {
            await memvaultApi.delete(id)
            set((state) => ({
              blocks: state.blocks.filter((b) => b.id !== id),
              total: state.total - 1,
              selectedBlock: state.selectedBlock?.id === id ? null : state.selectedBlock,
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to delete block')
          } finally {
            set({ loading: false })
          }
        },

        selectBlock: (block: MemoryBlock | null) => {
          set({ selectedBlock: block })
        },

        setPage: (page: number) => {
          set({ page })
          get().fetchBlocks()
        },

        setFilters: (filters: Partial<BlockFilters>) => {
          set((state) => ({
            filters: { ...state.filters, ...filters },
            page: 1,
          }))
          get().fetchBlocks()
        },

        setViewMode: (mode: ViewMode) => {
          set({ viewMode: mode })
        },

        setSearchQuery: (query: string) => {
          set({ searchQuery: query })
        },

        searchSemantic: async () => {
          const { searchQuery } = get()
          if (!searchQuery.trim()) return
          set({ isSearching: true, error: null })
          try {
            const results = await memvaultApi.searchSemantic(searchQuery)
            set({ searchResults: results })
          } catch (err) {
            handleStoreError(set, err, 'Semantic search failed')
          } finally {
            set({ isSearching: false })
          }
        },

        clearSearch: () => {
          set({ searchQuery: '', searchResults: [] })
        },

        // ── KG Actions ──

        setKgActiveTab: (tab: BrowserTab) => {
          set({ kg_activeTab: tab })
        },

        setKgGalaxyLayers: (layers: Set<GalaxyLayer>) => {
          set({ kg_galaxyLayers: layers })
        },

        fetchTriples: async (page?: number) => {
          const p = page ?? get().kg_triplesPage
          set({ kg_loading: true })
          try {
            const res = await kgApi.listTriples(p, 20)
            set((s) => ({
              kg_triples: res.items,
              kg_triplesTotal: res.total,
              kg_triplesPage: p,
              _fetchedAt: { ...s._fetchedAt, kg_triples: Date.now() },
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch triples')
          } finally {
            set({ kg_loading: false })
          }
        },

        fetchCommunities: async () => {
          set({ kg_loading: true })
          try {
            const communities = await kgApi.listCommunities()
            set((s) => ({
              kg_communities: communities,
              _fetchedAt: { ...s._fetchedAt, kg_communities: Date.now() },
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch communities')
          } finally {
            set({ kg_loading: false })
          }
        },

        fetchCommunityDetail: async (id: string) => {
          const cached = get()._communityDetailCache[id]
          if (cached) {
            set({ kg_selectedCommunity: cached })
            return
          }
          set({ kg_loading: true })
          try {
            const detail = await kgApi.getCommunity(id)
            set((s) => ({
              kg_selectedCommunity: detail,
              _communityDetailCache: { ...s._communityDetailCache, [id]: detail },
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch community detail')
          } finally {
            set({ kg_loading: false })
          }
        },

        fetchSummaries: async () => {
          set({ kg_loading: true })
          try {
            const summaries = await kgApi.listSummaries()
            set((s) => ({
              kg_summaries: summaries,
              _fetchedAt: { ...s._fetchedAt, kg_summaries: Date.now() },
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch summaries')
          } finally {
            set({ kg_loading: false })
          }
        },

        fetchAttitudes: async (category?: string) => {
          set({ kg_loading: true })
          try {
            const attitudes = await kgApi.listAttitudes(category)
            set((s) => ({
              kg_attitudes: attitudes,
              _fetchedAt: { ...s._fetchedAt, kg_attitudes: Date.now() },
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch attitudes')
          } finally {
            set({ kg_loading: false })
          }
        },

        fetchAttitudeHistory: async (factId: string) => {
          const cached = get()._attitudeHistoryCache[factId]
          if (cached) {
            set({ kg_attitudeHistory: cached })
            return
          }
          set({ kg_loading: true })
          try {
            const history = await kgApi.attitudeHistory(factId)
            set((s) => ({
              kg_attitudeHistory: history,
              _attitudeHistoryCache: { ...s._attitudeHistoryCache, [factId]: history },
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch attitude history')
          } finally {
            set({ kg_loading: false })
          }
        },

        fetchSkillProfiles: async () => {
          set({ kg_loading: true })
          try {
            const skills = await kgApi.skillProfiles()
            set((s) => ({
              kg_skills: skills,
              _fetchedAt: { ...s._fetchedAt, kg_skills: Date.now() },
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to fetch skills')
          } finally {
            set({ kg_loading: false })
          }
        },

        cascadeRecall: async (q: string) => {
          set({ kg_loading: true })
          try {
            const result = await kgApi.cascadeRecall(q)
            set({ kg_cascadeResult: result })
          } catch (err) {
            handleStoreError(set, err, 'Cascade recall failed')
          } finally {
            set({ kg_loading: false })
          }
        },

        clearCascadeResult: () => {
          set({ kg_cascadeResult: null })
        },

        // ── KG CRUD ──

        deleteTriple: async (id: string) => {
          try {
            await kgApi.deleteTriple(id)
            set((state) => ({
              kg_triples: state.kg_triples.filter((t) => t.id !== id),
              kg_triplesTotal: state.kg_triplesTotal - 1,
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to delete triple')
          }
        },

        deleteAttitude: async (id: string) => {
          try {
            await kgApi.deleteAttitude(id)
            set((state) => ({
              kg_attitudes: state.kg_attitudes.filter((a) => a.id !== id),
              _attitudeHistoryCache: {},
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to delete attitude')
          }
        },

        updateAttitude: async (id: string, data: { fact: string; category: string }) => {
          try {
            const updated = await kgApi.updateAttitude(id, data)
            set((state) => ({
              kg_attitudes: state.kg_attitudes.map((a) => (a.id === id ? updated : a)),
              _attitudeHistoryCache: {},
            }))
          } catch (err) {
            handleStoreError(set, err, 'Failed to update attitude')
          }
        },

        // ── Profile ──

        recalculateProfile: async () => {
          set({ loading: true, error: null })
          try {
            const profile = await memvaultApi.recalculateProfile()
            set((s) => ({
              profile,
              _fetchedAt: { ...s._fetchedAt, profile: Date.now() },
            }))
          } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to recalculate profile' })
          } finally {
            set({ loading: false })
          }
        },
      }),
      {
        name: 'memvault-cache',
        version: 3,
        migrate: () => ({}),
        partialize: (state) => ({
          blocks: state.blocks,
          total: state.total,
          profile: state.profile,
        }),
        // Set cannot be serialized to JSON — convert on storage
        storage: {
          getItem: (name) => {
            const raw = localStorage.getItem(name)
            if (!raw) return null
            try {
              return JSON.parse(raw)
            } catch {
              return null
            }
          },
          setItem: (name, value) => {
            localStorage.setItem(name, JSON.stringify(value))
          },
          removeItem: (name) => {
            localStorage.removeItem(name)
          },
        },
      },
    ),
    { name: 'memvaultStore' },
  ),
)

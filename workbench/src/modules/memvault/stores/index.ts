import { create } from "zustand";
import type {
  MemoryBlock,
  MemoryBlockCreate,
  MemoryBlockUpdate,
  KASProfile,
  SemanticSearchResult,
  PaginatedResponse,
} from "@/types";
import type { BlockFilters, ViewMode } from "../types";
import { memvaultApi } from "../api";

const DEFAULT_FILTERS: BlockFilters = {
  blockType: null,
  tag: null,
  sortField: "updated_at",
  sortOrder: "desc",
};

interface MemvaultState {
  // Data
  blocks: MemoryBlock[];
  total: number;
  page: number;
  pageSize: number;
  selectedBlock: MemoryBlock | null;
  profile: KASProfile | null;

  // Search
  searchQuery: string;
  searchResults: SemanticSearchResult[];
  isSearching: boolean;

  // UI state
  viewMode: ViewMode;
  filters: BlockFilters;
  loading: boolean;
  error: string | null;

  // Actions
  fetchBlocks: () => Promise<void>;
  fetchProfile: () => Promise<void>;
  createBlock: (data: MemoryBlockCreate) => Promise<void>;
  updateBlock: (id: string, data: MemoryBlockUpdate) => Promise<void>;
  deleteBlock: (id: string) => Promise<void>;
  selectBlock: (block: MemoryBlock | null) => void;
  setPage: (page: number) => void;
  setFilters: (filters: Partial<BlockFilters>) => void;
  setViewMode: (mode: ViewMode) => void;
  setSearchQuery: (query: string) => void;
  searchSemantic: () => Promise<void>;
  clearSearch: () => void;
}

export const useMemvaultStore = create<MemvaultState>((set, get) => ({
  // Data
  blocks: [],
  total: 0,
  page: 1,
  pageSize: 20,
  selectedBlock: null,
  profile: null,

  // Search
  searchQuery: "",
  searchResults: [],
  isSearching: false,

  // UI state
  viewMode: "grid",
  filters: DEFAULT_FILTERS,
  loading: false,
  error: null,

  // Actions

  fetchBlocks: async () => {
    const { page, pageSize, filters } = get();
    set({ loading: true, error: null });
    try {
      let response: PaginatedResponse<MemoryBlock>;
      if (filters.tag !== null) {
        response = await memvaultApi.listByTag(filters.tag, page, pageSize);
      } else if (filters.blockType !== null) {
        response = await memvaultApi.listByType(filters.blockType, page, pageSize);
      } else {
        response = await memvaultApi.list(page, pageSize);
      }
      set({
        blocks: response.items,
        total: response.total,
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to fetch blocks" });
    } finally {
      set({ loading: false });
    }
  },

  fetchProfile: async () => {
    set({ loading: true, error: null });
    try {
      const profile = await memvaultApi.getProfile();
      set({ profile });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to fetch profile" });
    } finally {
      set({ loading: false });
    }
  },

  createBlock: async (data: MemoryBlockCreate) => {
    set({ loading: true, error: null });
    try {
      await memvaultApi.create(data);
      await get().fetchBlocks();
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to create block" });
    } finally {
      set({ loading: false });
    }
  },

  updateBlock: async (id: string, data: MemoryBlockUpdate) => {
    set({ loading: true, error: null });
    try {
      const updated = await memvaultApi.update(id, data);
      set((state) => ({
        blocks: state.blocks.map((b) => (b.id === id ? updated : b)),
        selectedBlock: state.selectedBlock?.id === id ? updated : state.selectedBlock,
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to update block" });
    } finally {
      set({ loading: false });
    }
  },

  deleteBlock: async (id: string) => {
    set({ loading: true, error: null });
    try {
      await memvaultApi.delete(id);
      set((state) => ({
        blocks: state.blocks.filter((b) => b.id !== id),
        total: state.total - 1,
        selectedBlock: state.selectedBlock?.id === id ? null : state.selectedBlock,
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to delete block" });
    } finally {
      set({ loading: false });
    }
  },

  selectBlock: (block: MemoryBlock | null) => {
    set({ selectedBlock: block });
  },

  setPage: (page: number) => {
    set({ page });
    get().fetchBlocks();
  },

  setFilters: (filters: Partial<BlockFilters>) => {
    set((state) => ({
      filters: { ...state.filters, ...filters },
      page: 1,
    }));
    get().fetchBlocks();
  },

  setViewMode: (mode: ViewMode) => {
    set({ viewMode: mode });
  },

  setSearchQuery: (query: string) => {
    set({ searchQuery: query });
  },

  searchSemantic: async () => {
    const { searchQuery } = get();
    if (!searchQuery.trim()) return;
    set({ isSearching: true, error: null });
    try {
      const results = await memvaultApi.searchSemantic(searchQuery);
      set({ searchResults: results });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Semantic search failed" });
    } finally {
      set({ isSearching: false });
    }
  },

  clearSearch: () => {
    set({ searchQuery: "", searchResults: [] });
  },
}));

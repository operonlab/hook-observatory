import { createCrudApi, request } from "@/api/client";
import type {
  MemoryBlock,
  MemoryBlockCreate,
  MemoryBlockUpdate,
  KASProfile,
  SemanticSearchResult,
  PaginatedResponse,
} from "@/types";

export interface SyncScanResult {
  total: number;
  synced: number;
  failed: number;
  skipped: number;
  already: number;
  log: string;
}

export interface SyncStats {
  total: number;
  synced: number;
  failed: number;
  skipped: number;
}

const USE_MOCK = (import.meta as unknown as { env: Record<string, string> }).env.VITE_USE_MOCK === "true";

const crudApi = createCrudApi<MemoryBlock, MemoryBlockCreate, MemoryBlockUpdate>(
  "/memvault/blocks",
);

const realApi = {
  ...crudApi,

  searchSemantic: (query: string, topK = 10): Promise<SemanticSearchResult[]> =>
    request<SemanticSearchResult[]>(
      `/memvault/search?q=${encodeURIComponent(query)}&top_k=${topK}`,
    ),

  getProfile: (): Promise<KASProfile> =>
    request<KASProfile>("/memvault/profile"),

  listByTag: (
    tag: string,
    page = 1,
    pageSize = 20,
  ): Promise<PaginatedResponse<MemoryBlock>> =>
    request<PaginatedResponse<MemoryBlock>>(
      `/memvault/blocks?tag=${encodeURIComponent(tag)}&page=${page}&page_size=${pageSize}`,
    ),

  listByType: (
    blockType: string,
    page = 1,
    pageSize = 20,
  ): Promise<PaginatedResponse<MemoryBlock>> =>
    request<PaginatedResponse<MemoryBlock>>(
      `/memvault/blocks?block_type=${encodeURIComponent(blockType)}&page=${page}&page_size=${pageSize}`,
    ),

  syncScan: (recent?: number): Promise<SyncScanResult> =>
    request<SyncScanResult>(
      `/memvault/sync/scan${recent ? `?recent=${recent}` : ""}`,
      { method: "POST" },
    ),

  syncStats: (): Promise<SyncStats> =>
    request<SyncStats>("/memvault/sync/stats"),
};

import { mockMemvaultApi } from "./mock";

const api = USE_MOCK ? mockMemvaultApi : realApi;
export { api as memvaultApi };

// --- Auth types ---

export interface User {
  id: string
  email: string
  name: string
  avatar_url: string | null
  role: string
  status: string
  created_at: string
}

// --- App shell types ---

export type LauncherKind = 'app' | 'folder'
export type LauncherStatus = 'available' | 'coming-soon' | 'external'

/**
 * Unified entity for the App Launcher (`/apps`).
 * Replaces the old `AppInfo` + `ToolEntry` split — both apps and folders
 * live in the same list, distinguished by `kind`.
 * Folder membership is *not* stored on the item itself; it lives in the
 * user-mutable `AppLayout.folders` map so the same defaults can be
 * rearranged per-user without rewriting source.
 */
export interface LauncherItem {
  id: string
  kind: LauncherKind
  name: string
  description: string
  icon: string
  color: string
  status: LauncherStatus

  // app-only
  path?: string
  externalUrl?: string

  // folder-only — `true` means defined in apps.ts (cannot be deleted, name fixed)
  builtIn?: boolean
}

/** Persisted launcher arrangement. Versioned for forward compatibility. */
export interface AppLayoutV2 {
  version: 2
  /** top-level item ids for the internal section (apps + folders) */
  internal: string[]
  /** top-level item ids for the external section (apps + folders) */
  external: string[]
  /** folder.id -> child app ids (ordered). Folders cannot nest. */
  folders: Record<string, string[]>
  /** metadata for user-created folders (built-in folders use apps.ts) */
  userFolders: Record<string, { name: string; icon: string; color: string }>
  /** ids the user has stashed via long-press */
  hidden: string[]
}

// --- Shared base types (mirrors core/src/shared/schemas.py) ---

export interface BaseEntity {
  id: string
  space_id: string
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface ErrorResponse {
  detail: string
  code: string
  module: string | null
}

// --- Memvault API types (P1 contract — shared between worktrees) ---

export interface MemoryBlock extends BaseEntity {
  content: string
  block_type: 'knowledge' | 'skill' | 'attitude' | 'general'
  tags: string[]
  source_session: string | null
  confidence: number
}

export interface MemoryBlockCreate {
  content: string
  block_type: 'knowledge' | 'skill' | 'attitude' | 'general'
  tags?: string[]
  source_session?: string
}

export interface MemoryBlockUpdate {
  content?: string
  block_type?: 'knowledge' | 'skill' | 'attitude' | 'general'
  tags?: string[]
  confidence?: number
}

export interface KASProfile {
  id: string
  space_id: string
  knowledge_score: number
  attitude_score: number
  skill_score: number
  updated_at: string
}

export interface SemanticSearchResult {
  block: MemoryBlock
  score: number
}

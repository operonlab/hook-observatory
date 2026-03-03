export type BlockType = 'knowledge' | 'skill' | 'attitude' | 'general'

export type ViewMode = 'grid' | 'list'

export type SortField = 'created_at' | 'updated_at' | 'confidence'
export type SortOrder = 'asc' | 'desc'

export interface BlockFilters {
  blockType: BlockType | null
  tag: string | null
  sortField: SortField
  sortOrder: SortOrder
}

// ── Galaxy types ──

export type GalaxyLayer = 'blocks' | 'triples' | 'clusters' | 'wisdom'

export interface GalaxyNode {
  id: string
  label: string
  type: BlockType
  confidence: number
  layer: GalaxyLayer
  x?: number
  y?: number
  z?: number
  vx?: number
  vy?: number
  vz?: number
}

export interface GalaxyLink {
  source: string
  target: string
  strength: number
}

export const BLOCK_TYPE_CONFIG: Record<BlockType, { label: string; color: string }> = {
  knowledge: { label: '知識', color: 'var(--blue)' },
  skill: { label: '技能', color: 'var(--green)' },
  attitude: { label: '態度', color: 'var(--mauve)' },
  general: { label: '通用', color: 'var(--text)' },
}

export const KG_LAYER_CONFIG: Record<GalaxyLayer, { label: string; color: string }> = {
  blocks: { label: '區塊', color: 'var(--text)' },
  triples: { label: '三元組', color: 'var(--teal)' },
  clusters: { label: '群集', color: 'var(--blue)' },
  wisdom: { label: '智慧', color: 'var(--peach)' },
}

// ── KG API types (mirrors kg_schemas.py) ──

export type BrowserTab = 'blocks' | 'kg-explorer' | 'skills'

export interface Triple {
  id: string
  space_id: string
  created_by: string | null
  created_at: string
  updated_at: string
  subject: string
  predicate: string
  object: string
  source_session: string | null
  timestamp: string | null
  topic: string | null
}

export interface Cluster {
  id: string
  space_id: string
  created_by: string | null
  created_at: string
  updated_at: string
  name: string
  size: number
  top_subjects: string[]
  top_predicates: string[]
  top_objects: string[]
  summary: string | null
  verdict: string
  generation_batch: string | null
}

export interface ClusterDetail extends Cluster {
  triples: Triple[]
}

export interface WisdomNode {
  id: string
  space_id: string
  created_by: string | null
  created_at: string
  updated_at: string
  wisdom: string
  confidence: string // HIGH/MEDIUM/LOW
  bridge_entity: string
  cluster_ids: string[]
  evidence_count: number | null
  tags: string[]
  verified: boolean
}

export interface AttitudeFact {
  id: string
  space_id: string
  created_by: string | null
  created_at: string
  updated_at: string
  fact: string
  category: string
  operation: string
  confidence: number
  source_sessions: string[]
  superseded_by: string | null
  previous_version: string | null
}

export interface SkillProficiency {
  skill_name: string
  invocation_count: number
  success_count: number
  success_rate: number
  last_invoked: string | null
  proficiency: number
}

export interface SkillInvocation {
  id: string
  space_id: string
  created_by: string | null
  created_at: string
  updated_at: string
  skill_name: string
  source_session: string
  cwd: string | null
  invoked_at: string
  outcome: string
  duration_ms: number | null
}

export interface CascadeRecallResult {
  wisdom: WisdomNode[]
  clusters: Cluster[]
  triples: Triple[]
  blocks: any[]
  layers_searched: string[]
}

import type { BaseEntity } from '@/types'

// ======================== Document ========================

export interface Document extends BaseEntity {
  title: string
  source_type: string
  source_uri: string | null
  content_hash: string
  current_version_id: string | null
  tags: string[]
  metadata: Record<string, unknown> | null
  status: string
  confidence: number | null
  access_count: number
  last_accessed_at: string | null
}

export interface DocumentCreate {
  title: string
  source_type?: string
  source_uri?: string
  content_hash: string
  tags?: string[]
  metadata?: Record<string, unknown>
}

export interface DocumentUpdate {
  title?: string
  tags?: string[]
  metadata?: Record<string, unknown>
  status?: string
  confidence?: number
}

export interface DocumentBrief {
  id: string
  title: string
  source_type: string
  tags: string[]
  status: string
  created_at: string
}

// ======================== DocumentVersion ========================

export interface DocumentVersion extends BaseEntity {
  document_id: string
  version_number: number
  content_hash: string
  status: string
  chunk_count: number
  extraction_model: string | null
  summary: string | null
  table_of_contents: Record<string, unknown> | null
}

// ======================== DocumentChunk ========================

export interface DocumentChunk extends BaseEntity {
  version_id: string
  document_id: string
  chunk_index: number
  content: string
  section_path: string | null
  page_range: string | null
  heading: string | null
  token_count: number
  chunk_type: string
}

// ======================== DocumentRelation ========================

export interface DocumentRelation extends BaseEntity {
  source_document_id: string
  target_document_id: string
  relation_type: string
  evidence: string | null
  source_chunk_id: string | null
  confidence: number | null
  valid_from: string | null
  invalid_at: string | null
  invalidated_by: string | null
}

export interface DocumentRelationCreate {
  source_document_id: string
  target_document_id: string
  relation_type: string
  evidence?: string
  source_chunk_id?: string
  confidence?: number
}

// ======================== CoverageGap ========================

export interface CoverageGap extends BaseEntity {
  query_text: string
  query_hash: string
  detected_at: string
  gap_type: string
  status: string
  resolution: string | null
  resolved_document_id: string | null
  suggested_sources: Record<string, unknown> | null
}

// ======================== QA ========================

export interface QARequest {
  question: string
  mode?: 'factual' | 'mixed'
  domain?: string
  top_k?: number
}

export interface CitationRef {
  document_id: string
  chunk_id: string | null
  section: string | null
  page: string | null
  quote: string | null
}

export interface QAResponse {
  question: string
  answer: string
  citations: CitationRef[]
  confidence: number | null
  crag_verdict: string | null
  pipeline_used: string
  qa_log_id: string | null
}

export interface QALog extends BaseEntity {
  query_text: string
  query_hash: string
  answer_text: string
  citations: Record<string, unknown> | null
  confidence: number | null
  crag_verdict: string | null
  feedback: string | null
  pipeline_used: string
  latency_ms: number | null
}

// ======================== Dashboard ========================

export interface DashboardData {
  total_documents: number
  total_chunks: number
  total_qa_logs: number
  coverage_gap_count: number
  published_count: number
  recent_documents: DocumentBrief[]
}

// ======================== Contradiction ========================

export interface Contradiction {
  relation_id: string
  other_document_id: string
  other_document_title: string
  evidence: string | null
  confidence: number | null
  source_chunk_id: string | null
  created_at: string | null
}

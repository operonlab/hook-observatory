import type { BaseEntity } from '@/types'

export type RelevanceTier = 'high' | 'medium' | 'low'

// Article — matches backend ArticleResponse
export interface Article extends BaseEntity {
  title: string
  abstract: string | null
  arxiv_id: string | null
  doi: string | null
  year: number | null
  authors: Array<{ name: string; affiliation?: string }>
  journal: string | null
  categories: string[]
  tags: string[]
  pdf_url: string | null
  source_url: string | null
  full_text: string | null
  s3_uri: string | null
  digest: Digest | null
}

export interface ArticleCreate {
  title: string
  abstract?: string
  arxiv_id?: string
  doi?: string
  year?: number
  authors?: Array<{ name: string }>
  journal?: string
  categories?: string[]
  tags?: string[]
  pdf_url?: string
  source_url?: string
  full_text?: string
}

export interface ArticleUpdate {
  title?: string
  abstract?: string
  tags?: string[]
  categories?: string[]
  year?: number
}

// ArticleBrief — matches backend ArticleBrief
export interface ArticleBrief {
  id: string
  title: string
  arxiv_id: string | null
  doi: string | null
  year: number | null
  authors: Array<{ name: string }>
  journal: string | null
  categories: string[]
  tags: string[]
  created_at: string
}

// Digest — matches backend DigestResponse
export interface Digest {
  id: string
  paper_id: string
  one_liner: string | null
  key_findings: string[]
  workshop_relevance: string | null
  applicable_modules: string[]
  actionable_insight: string | null
  effort_estimate: string | null
  confidence: number | null
  model_used: string | null
  generated_at: string | null
  created_at: string
}

// Annotation — matches backend AnnotationResponse
export interface Annotation extends BaseEntity {
  paper_id: string
  note: string
  annotation_type: string
  tags: string[]
}

export interface AnnotationCreate {
  note: string
  annotation_type?: string
  tags?: string[]
}

// Search — matches backend PaperSearchResult
export interface SearchResult {
  article: ArticleBrief
  score: number
  digest_one_liner: string | null
  workshop_relevance: string | null
}

// Dashboard — matches backend DashboardResponse
export interface DashboardData {
  total_articles: number
  total_digests: number
  total_annotations: number
  high_relevance_count: number
  recent_articles: ArticleBrief[]
  cannibalize_candidates: ArticleBrief[]
}

import type { BaseEntity } from '@/types'

// Search Config
export interface SearchConfig {
  search_query_en?: string
  focus_areas?: string
  subreddits?: string
  cities?: { name_en: string; name_cn: string }[]
  content_priorities?: string[]
}

// Analyst
export interface Analyst extends BaseEntity {
  name: string
  display_name: string
  color: string
  avatar_url: string | null
  model_id: string | null
  system_prompt: string | null
  cli_command: string | null
  enabled: boolean
  priority: number
}

export interface AnalystCreate {
  name: string
  display_name: string
  color?: string
  model_id?: string
  system_prompt?: string
  cli_command?: string
}

export interface AnalystUpdate {
  display_name?: string
  color?: string
  avatar_url?: string | null
  model_id?: string | null
  system_prompt?: string | null
  cli_command?: string | null
  enabled?: boolean
  priority?: number
}

// Briefing Subtopic
export interface BriefingSubtopic extends BaseEntity {
  topic_id: string
  name: string
  parameters: Record<string, unknown>
  enabled: boolean
}

// Briefing Topic
export interface BriefingTopic extends BaseEntity {
  name: string
  display_name: string
  description: string | null
  enabled: boolean
  priority: number
  prompt_template: string | null
  sources: Record<string, unknown>[]
  schedule: string
  topic_type: string
  search_config: SearchConfig
  subtopics: BriefingSubtopic[]
}

export interface BriefingTopicCreate {
  name: string
  display_name: string
  description?: string
  enabled?: boolean
  priority?: number
  prompt_template?: string
  sources?: Record<string, unknown>[]
  schedule?: string
  topic_type?: string
  search_config?: SearchConfig
}

export interface BriefingTopicUpdate {
  display_name?: string
  description?: string
  enabled?: boolean
  priority?: number
  prompt_template?: string
  sources?: Record<string, unknown>[]
  schedule?: string
  topic_type?: string
  search_config?: SearchConfig
}

export interface BriefingSubtopicCreate {
  name: string
  parameters?: Record<string, unknown>
  enabled?: boolean
}

export interface BriefingSubtopicUpdate {
  name?: string
  parameters?: Record<string, unknown>
  enabled?: boolean
}

// Briefing Entry (normalized per-entry storage)
export interface BriefingEntry {
  id: string
  space_id: string
  briefing_id: string
  phase: 'raw' | 'analysis' | 'debate' | 'conclusion'
  key: string
  content: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

// Briefing
export interface Briefing extends BaseEntity {
  date: string
  topic_id: string | null
  domain: string
  status: string
  raw_data: Record<string, string> | null
  analyses: Record<string, string> | null
  debate: string | null
  entries: BriefingEntry[]
  conclusion: string | null
  conclusion_meta: Record<string, unknown> | null
  follow_ups: FollowUp[]
}

// Follow-Up
export interface FollowUp extends BaseEntity {
  briefing_id: string
  question: string
  answer: string | null
  status: string
  metadata: Record<string, unknown>
}

export interface FollowUpCreate {
  question: string
}

// Daily Summary (merged view)
export interface DomainSummary {
  domain: string
  display_name: string
  briefing_id: string
  status: string
  sources_count: number
  analysts_count: number
  has_conclusion: boolean
}

export interface DailySummary {
  date: string
  status: string
  domains: DomainSummary[]
  merged_conclusion: string | null
  consensus_points: string[]
  dissent_points: Record<string, unknown>[]
  confidence: number | null
  briefing_ids: string[]
  follow_up_count: number
}

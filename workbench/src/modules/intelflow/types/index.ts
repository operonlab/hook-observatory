import type { BaseEntity } from '@/types'

// Report
export interface Report extends BaseEntity {
  title: string
  query: string
  content: string
  sources: ReportSource[]
  tags: string[]
  skill_name: string | null
  topics: TopicBrief[]
}

export interface ReportSource {
  url: string
  title: string
}

export interface ReportCreate {
  title: string
  query: string
  content: string
  sources?: ReportSource[]
  tags?: string[]
  skill_name?: string
}

export interface ReportUpdate {
  title?: string
  content?: string
  sources?: ReportSource[]
  tags?: string[]
}

export interface ReportBrief {
  id: string
  title: string
  query: string
  tags: string[]
  skill_name: string | null
  created_at: string
}

// Topic
export interface Topic extends BaseEntity {
  name: string
  display_name: string | null
  report_count: number
}

export interface TopicBrief {
  id: string
  name: string
  display_name: string | null
}

export interface TopicGraphNode {
  id: string
  name: string
  display_name: string | null
  report_count: number
}

export interface TopicGraphEdge {
  source: string
  target: string
  weight: number
}

export interface TopicGraph {
  nodes: TopicGraphNode[]
  edges: TopicGraphEdge[]
}

// Search
export interface SearchResult {
  report: ReportBrief
  score: number
}

export interface SearchCheckResult {
  exists: boolean
  matches: SearchResult[]
}

// Dashboard
export interface DashboardData {
  total_reports: number
  total_topics: number
  total_briefings: number
  recent_reports: ReportBrief[]
}

export interface TimelineEntry {
  date: string
  count: number
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
}

export interface BriefingTopicUpdate {
  display_name?: string
  description?: string
  enabled?: boolean
  priority?: number
  prompt_template?: string
  sources?: Record<string, unknown>[]
  schedule?: string
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

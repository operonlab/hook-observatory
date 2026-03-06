import { createCrudApi, request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  DashboardData,
  Report,
  ReportCreate,
  ReportUpdate,
  SearchCheckResult,
  SearchResult,
  TimelineEntry,
  Topic,
  TopicGraph,
} from '../types'

const reportCrud = createCrudApi<Report, ReportCreate, ReportUpdate>('/intelflow/reports')

export const intelflowApi = {
  ...reportCrud,

  listByTags: (tags: string[], page = 1, pageSize = 20) =>
    request<PaginatedResponse<Report>>(
      `/intelflow/reports?tags=${tags.join(',')}&page=${page}&page_size=${pageSize}`,
    ),

  listByTopic: (topicId: string, page = 1, pageSize = 20) =>
    request<PaginatedResponse<Report>>(
      `/intelflow/reports?topic_id=${topicId}&page=${page}&page_size=${pageSize}`,
    ),

  search: (query: string, limit = 10, threshold = 0.5) =>
    request<SearchResult[]>('/intelflow/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit, threshold }),
    }),

  checkDuplicate: (query: string, threshold = 0.85) =>
    request<SearchCheckResult>('/intelflow/search/check', {
      method: 'POST',
      body: JSON.stringify({ query, threshold }),
    }),

  getDashboard: () => request<DashboardData>('/intelflow/dashboard'),

  getTimeline: (days = 30) =>
    request<{ entries: TimelineEntry[] }>(`/intelflow/dashboard/timeline?days=${days}`),

  listTopics: (page = 1, pageSize = 50) =>
    request<PaginatedResponse<Topic>>(`/intelflow/topics?page=${page}&page_size=${pageSize}`),

  getTopicGraph: () => request<TopicGraph>('/intelflow/topics/graph'),
}

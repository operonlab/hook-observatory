import { createCrudApi, request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  BriefingSubtopic,
  BriefingSubtopicCreate,
  BriefingSubtopicUpdate,
  BriefingTopic,
  BriefingTopicCreate,
  BriefingTopicUpdate,
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

  // Briefing Topics
  listBriefingTopics: (page = 1, pageSize = 50) =>
    request<PaginatedResponse<BriefingTopic>>(
      `/intelflow/briefings/topics?page=${page}&page_size=${pageSize}`,
    ),

  createBriefingTopic: (data: BriefingTopicCreate) =>
    request<BriefingTopic>('/intelflow/briefings/topics', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateBriefingTopic: (id: string, data: BriefingTopicUpdate) =>
    request<BriefingTopic>(`/intelflow/briefings/topics/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteBriefingTopic: (id: string) =>
    request<void>(`/intelflow/briefings/topics/${id}`, {
      method: 'DELETE',
    }),

  toggleBriefingTopic: (id: string) =>
    request<BriefingTopic>(`/intelflow/briefings/topics/${id}/toggle`, {
      method: 'PATCH',
    }),

  addBriefingSubtopic: (topicId: string, data: BriefingSubtopicCreate) =>
    request<BriefingSubtopic>(`/intelflow/briefings/topics/${topicId}/subtopics`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateBriefingSubtopic: (topicId: string, subtopicId: string, data: BriefingSubtopicUpdate) =>
    request<BriefingSubtopic>(`/intelflow/briefings/topics/${topicId}/subtopics/${subtopicId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteBriefingSubtopic: (topicId: string, subtopicId: string) =>
    request<void>(`/intelflow/briefings/topics/${topicId}/subtopics/${subtopicId}`, {
      method: 'DELETE',
    }),
}

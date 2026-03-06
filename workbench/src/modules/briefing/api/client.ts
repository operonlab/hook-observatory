import { request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  Analyst,
  AnalystCreate,
  AnalystUpdate,
  Briefing,
  BriefingEntry,
  BriefingSubtopic,
  BriefingSubtopicCreate,
  BriefingSubtopicUpdate,
  BriefingTopic,
  BriefingTopicCreate,
  BriefingTopicUpdate,
  DailySummary,
  FollowUp,
  FollowUpCreate,
} from '../types'

export const briefingApi = {
  // ── Topics ──

  listTopics: (page = 1, pageSize = 50) =>
    request<PaginatedResponse<BriefingTopic>>(
      `/briefing/topics?page=${page}&page_size=${pageSize}`,
    ),

  createTopic: (data: BriefingTopicCreate) =>
    request<BriefingTopic>('/briefing/topics', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateTopic: (id: string, data: BriefingTopicUpdate) =>
    request<BriefingTopic>(`/briefing/topics/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteTopic: (id: string) =>
    request<void>(`/briefing/topics/${id}`, { method: 'DELETE' }),

  toggleTopic: (id: string) =>
    request<BriefingTopic>(`/briefing/topics/${id}/toggle`, { method: 'PATCH' }),

  // ── Subtopics ──

  addSubtopic: (topicId: string, data: BriefingSubtopicCreate) =>
    request<BriefingSubtopic>(`/briefing/topics/${topicId}/subtopics`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateSubtopic: (topicId: string, subtopicId: string, data: BriefingSubtopicUpdate) =>
    request<BriefingSubtopic>(`/briefing/topics/${topicId}/subtopics/${subtopicId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteSubtopic: (topicId: string, subtopicId: string) =>
    request<void>(`/briefing/topics/${topicId}/subtopics/${subtopicId}`, {
      method: 'DELETE',
    }),

  // ── Analysts ──

  listAnalysts: () => request<Analyst[]>('/briefing/analysts'),

  createAnalyst: (data: AnalystCreate) =>
    request<Analyst>('/briefing/analysts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateAnalyst: (id: string, data: AnalystUpdate) =>
    request<Analyst>(`/briefing/analysts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteAnalyst: (id: string) =>
    request<void>(`/briefing/analysts/${id}`, { method: 'DELETE' }),

  toggleAnalyst: (id: string) =>
    request<Analyst>(`/briefing/analysts/${id}/toggle`, { method: 'PATCH' }),

  // ── Briefings (daily) ──

  listBriefings: (page = 1, pageSize = 20) =>
    request<PaginatedResponse<Briefing>>(
      `/briefing/daily?page=${page}&page_size=${pageSize}`,
    ),

  getBriefingsByDate: (date: string) =>
    request<Briefing[]>(`/briefing/daily/${date}`),

  getDailySummary: (date: string) =>
    request<DailySummary>(`/briefing/daily/${date}/summary`),

  getBriefingByDomain: (date: string, domain: string) =>
    request<Briefing>(`/briefing/daily/${date}/${domain}`),

  // ── Entries ──

  getEntries: (briefingId: string, phase?: string) => {
    const params = phase ? `?phase=${phase}` : ''
    return request<BriefingEntry[]>(`/briefing/daily/${briefingId}/entries${params}`)
  },

  // ── Follow-Ups ──

  listFollowUps: (briefingId: string) =>
    request<FollowUp[]>(`/briefing/daily/${briefingId}/follow-ups`),

  createFollowUp: (briefingId: string, data: FollowUpCreate) =>
    request<FollowUp>(`/briefing/daily/${briefingId}/follow-ups`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}

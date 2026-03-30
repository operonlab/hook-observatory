import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { intelflowApi } from '@/modules/intelflow/api/client'

const STALE_TIME = 5 * 60 * 1000

export const intelflowKeys = {
  all: ['intelflow'] as const,
  dashboard: () => [...intelflowKeys.all, 'dashboard'] as const,
  timeline: (days: number) => [...intelflowKeys.all, 'timeline', { days }] as const,
  reports: (params: { page: number; tag: string | null; pageSize: number }) =>
    [...intelflowKeys.all, 'reports', params] as const,
  report: (id: string) => [...intelflowKeys.all, 'report', id] as const,
  topics: () => [...intelflowKeys.all, 'topics'] as const,
  topicReports: (params: { topicId: string; page: number }) =>
    [...intelflowKeys.all, 'topicReports', params] as const,
  search: (query: string) => [...intelflowKeys.all, 'search', query] as const,
}

export function useIntelflowDashboard() {
  return useQuery({
    queryKey: intelflowKeys.dashboard(),
    queryFn: () => intelflowApi.getDashboard(),
    staleTime: STALE_TIME,
  })
}

export function useIntelflowTimeline(days = 30) {
  return useQuery({
    queryKey: intelflowKeys.timeline(days),
    queryFn: async () => {
      const data = await intelflowApi.getTimeline(days)
      return data.entries
    },
    staleTime: STALE_TIME,
  })
}

export function useIntelflowReports(page: number, tag: string | null, pageSize = 20) {
  return useQuery({
    queryKey: intelflowKeys.reports({ page, tag, pageSize }),
    queryFn: () =>
      tag ? intelflowApi.listByTags([tag], page, pageSize) : intelflowApi.list(page, pageSize),
    staleTime: STALE_TIME,
  })
}

export function useIntelflowReport(id: string | undefined) {
  return useQuery({
    queryKey: intelflowKeys.report(id!),
    queryFn: () => intelflowApi.get(id!),
    enabled: !!id,
  })
}

export function useIntelflowTopics() {
  return useQuery({
    queryKey: intelflowKeys.topics(),
    queryFn: () => intelflowApi.listTopics(1, 200),
    staleTime: STALE_TIME,
  })
}

export function useTopicReports(topicId: string | undefined, page: number, pageSize = 20) {
  return useQuery({
    queryKey: intelflowKeys.topicReports({ topicId: topicId!, page }),
    queryFn: () => intelflowApi.listByTopic(topicId!, page, pageSize),
    enabled: !!topicId,
  })
}

export function useIntelflowSearch(query: string) {
  return useQuery({
    queryKey: intelflowKeys.search(query),
    queryFn: () => intelflowApi.search(query, 10, 0.3),
    enabled: query.trim().length > 0,
  })
}

export function useDeleteReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => intelflowApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: intelflowKeys.all })
    },
  })
}

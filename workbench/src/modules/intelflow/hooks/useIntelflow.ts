import { useIntelflowStore } from '@/modules/intelflow/stores'
import {
  useDeleteReport as useDeleteReportMutation,
  useIntelflowDashboard,
  useIntelflowReport,
  useIntelflowReports,
  useIntelflowSearch,
  useIntelflowTimeline,
  useIntelflowTopics,
} from './queries'

export function useDashboard() {
  const { data: dashboard, isLoading } = useIntelflowDashboard()
  return { dashboard: dashboard ?? null, loading: isLoading }
}

export function useTimeline(days = 30) {
  const { data: timeline = [], isLoading } = useIntelflowTimeline(days)
  return { timeline, loading: isLoading }
}

export function useReports() {
  const { activeTag, reportsPage, setActiveTag, setReportsPage } = useIntelflowStore()
  const pageSize = 20
  const { data, isLoading } = useIntelflowReports(reportsPage, activeTag, pageSize)
  const deleteMutation = useDeleteReportMutation()

  const reports = data?.items ?? []
  const total = data?.total ?? 0
  const allTags = [...new Set(reports.flatMap((r) => r.tags))].sort()

  return {
    reports,
    total,
    page: reportsPage,
    pageSize,
    loading: isLoading,
    activeTag,
    allTags,
    setActiveTag,
    setPage: setReportsPage,
    deleteReport: deleteMutation.mutateAsync,
  }
}

export function useReportDetail(id: string | undefined) {
  const { data: report, isLoading } = useIntelflowReport(id)
  return { report: report ?? null, loading: isLoading }
}

export function useTopics() {
  const { activeTopic, setActiveTopic } = useIntelflowStore()
  const { data, isLoading } = useIntelflowTopics()

  return {
    topics: data?.items ?? [],
    total: data?.total ?? 0,
    loading: isLoading,
    activeTopic,
    setActiveTopic,
  }
}

export function useSearch() {
  const { searchQuery, setSearchQuery, clearSearch } = useIntelflowStore()
  const { data: results = [], isLoading } = useIntelflowSearch(searchQuery)

  return {
    query: searchQuery,
    results: searchQuery.trim() ? results : [],
    loading: isLoading,
    setQuery: setSearchQuery,
    search: setSearchQuery,
    clear: clearSearch,
  }
}

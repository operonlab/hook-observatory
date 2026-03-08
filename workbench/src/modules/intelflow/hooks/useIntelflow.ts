import { useEffect } from 'react'
import { useIntelflowStore } from '../stores'

const STALE_MS = 5 * 60 * 1000

export function useDashboard() {
  const { dashboard, dashboardLoading, dashboardFetchedAt, fetchDashboard } = useIntelflowStore()

  useEffect(() => {
    if (!dashboard || Date.now() - dashboardFetchedAt > STALE_MS) fetchDashboard()
  }, [dashboard, dashboardFetchedAt, fetchDashboard])

  return { dashboard, loading: dashboardLoading && !dashboard }
}

export function useTimeline(days = 30) {
  const { timeline, timelineLoading, timelineFetchedAt, fetchTimeline } = useIntelflowStore()

  useEffect(() => {
    if (timeline.length === 0 || Date.now() - timelineFetchedAt > STALE_MS) fetchTimeline(days)
  }, [timeline.length, timelineFetchedAt, fetchTimeline, days])

  return { timeline, loading: timelineLoading && timeline.length === 0 }
}

export function useReports() {
  const {
    reports,
    reportsTotal,
    reportsPage,
    reportsPageSize,
    reportsLoading,
    activeTag,
    allTags,
    fetchReports,
    deleteReport,
    setActiveTag,
  } = useIntelflowStore()

  useEffect(() => {
    fetchReports()
  }, [fetchReports])

  return {
    reports,
    total: reportsTotal,
    page: reportsPage,
    pageSize: reportsPageSize,
    loading: reportsLoading && reports.length === 0,
    activeTag,
    allTags,
    fetchReports,
    deleteReport,
    setActiveTag,
  }
}

export function useReportDetail(id: string | undefined) {
  const { selectedReport, reportDetailLoading, fetchReportById, clearSelectedReport } =
    useIntelflowStore()

  useEffect(() => {
    if (id) fetchReportById(id)
    return () => clearSelectedReport()
  }, [id, fetchReportById, clearSelectedReport])

  return { report: selectedReport, loading: reportDetailLoading }
}

export function useTopics() {
  const {
    topics,
    topicsTotal,
    topicsLoading,
    topicsFetchedAt,
    activeTopic,
    fetchTopics,
    setActiveTopic,
  } = useIntelflowStore()

  useEffect(() => {
    if (topics.length === 0 || Date.now() - topicsFetchedAt > STALE_MS) fetchTopics()
  }, [topics.length, topicsFetchedAt, fetchTopics])

  return {
    topics,
    total: topicsTotal,
    loading: topicsLoading && topics.length === 0,
    activeTopic,
    setActiveTopic,
  }
}

export function useSearch() {
  const { searchQuery, searchResults, searchLoading, setSearchQuery, searchReports, clearSearch } =
    useIntelflowStore()

  return {
    query: searchQuery,
    results: searchResults,
    loading: searchLoading,
    setQuery: setSearchQuery,
    search: searchReports,
    clear: clearSearch,
  }
}

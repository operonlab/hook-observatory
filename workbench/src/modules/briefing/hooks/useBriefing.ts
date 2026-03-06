import { useEffect } from 'react'
import { useBriefingStore } from '../stores'

const STALE_MS = 5 * 60 * 1000

export function useTodaySummary() {
  const { todaySummary, todayLoading, todayFetchedAt, selectedDate, fetchTodaySummary } =
    useBriefingStore()

  useEffect(() => {
    if (!todaySummary || Date.now() - todayFetchedAt > STALE_MS) {
      fetchTodaySummary(selectedDate)
    }
  }, [todaySummary, todayFetchedAt, selectedDate, fetchTodaySummary])

  return { summary: todaySummary, loading: todayLoading && !todaySummary }
}

export function useBriefingDetail(date: string | undefined) {
  const { selectedBriefings, detailLoading, fetchBriefingsByDate, clearSelectedBriefings } =
    useBriefingStore()

  useEffect(() => {
    if (date) fetchBriefingsByDate(date)
    return () => clearSelectedBriefings()
  }, [date, fetchBriefingsByDate, clearSelectedBriefings])

  return { briefings: selectedBriefings, loading: detailLoading }
}

export function useBriefingHistory() {
  const { briefings, briefingsTotal, briefingsPage, briefingsLoading, briefingsFetchedAt, fetchBriefings } =
    useBriefingStore()

  useEffect(() => {
    if (briefings.length === 0 || Date.now() - briefingsFetchedAt > STALE_MS) fetchBriefings()
  }, [briefings.length, briefingsFetchedAt, fetchBriefings])

  return {
    briefings,
    total: briefingsTotal,
    page: briefingsPage,
    loading: briefingsLoading && briefings.length === 0,
    fetchBriefings,
  }
}

export function useTopics() {
  const { topics, topicsLoading, topicsFetchedAt, fetchTopics } = useBriefingStore()

  useEffect(() => {
    if (topics.length === 0 || Date.now() - topicsFetchedAt > STALE_MS) fetchTopics()
  }, [topics.length, topicsFetchedAt, fetchTopics])

  return { topics, loading: topicsLoading && topics.length === 0, fetchTopics }
}

export function useAnalysts() {
  const { analysts, analystsLoading, analystsFetchedAt, fetchAnalysts } = useBriefingStore()

  useEffect(() => {
    if (analysts.length === 0 || Date.now() - analystsFetchedAt > STALE_MS) fetchAnalysts()
  }, [analysts.length, analystsFetchedAt, fetchAnalysts])

  return { analysts, loading: analystsLoading && analysts.length === 0, fetchAnalysts }
}

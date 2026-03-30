import { useBriefingStore } from '../stores'
import {
  useAnalystsQuery,
  useBriefingsListQuery,
  useBriefingsByDateQuery,
  useInvalidateBriefing,
  useTodaySummaryQuery,
  useTopicsQuery,
} from './queries'

export function useTodaySummary() {
  const selectedDate = useBriefingStore((s) => s.selectedDate)
  const { data, isLoading } = useTodaySummaryQuery(selectedDate)
  return { summary: data ?? null, loading: isLoading && !data }
}

export function useBriefingDetail(date: string | undefined) {
  const { data, isLoading } = useBriefingsByDateQuery(date)
  return { briefings: data ?? [], loading: isLoading }
}

export function useBriefingHistory() {
  const briefingsPage = useBriefingStore((s) => s.briefingsPage)
  const setBriefingsPage = useBriefingStore((s) => s.setBriefingsPage)
  const { data, isLoading } = useBriefingsListQuery(briefingsPage)

  return {
    briefings: data?.items ?? [],
    total: data?.total ?? 0,
    page: briefingsPage,
    loading: isLoading && !data,
    fetchBriefings: setBriefingsPage,
  }
}

export function useTopics() {
  const { data, isLoading } = useTopicsQuery()
  const { invalidateTopics } = useInvalidateBriefing()
  return {
    topics: data?.items ?? [],
    loading: isLoading && !data,
    fetchTopics: invalidateTopics,
  }
}

export function useAnalysts() {
  const { data, isLoading } = useAnalystsQuery()
  const { invalidateAnalysts } = useInvalidateBriefing()
  return {
    analysts: data ?? [],
    loading: isLoading && !data,
    fetchAnalysts: invalidateAnalysts,
  }
}

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { briefingApi } from '../api/client'

export const briefingKeys = {
  all: ['briefing'] as const,
  todaySummary: (date: string) => ['briefing', 'todaySummary', date] as const,
  byDate: (date: string) => ['briefing', 'byDate', date] as const,
  list: (page: number) => ['briefing', 'list', page] as const,
  topics: () => ['briefing', 'topics'] as const,
  analysts: () => ['briefing', 'analysts'] as const,
  runStatus: () => ['briefing', 'runStatus'] as const,
}

const STALE_5MIN = 5 * 60 * 1000

export function useTodaySummaryQuery(date: string) {
  return useQuery({
    queryKey: briefingKeys.todaySummary(date),
    queryFn: () => briefingApi.getDailySummary(date),
    staleTime: STALE_5MIN,
  })
}

export function useBriefingsByDateQuery(date: string | undefined) {
  return useQuery({
    queryKey: briefingKeys.byDate(date!),
    queryFn: () => briefingApi.getBriefingsByDate(date!),
    enabled: !!date,
  })
}

export function useBriefingsListQuery(page: number) {
  return useQuery({
    queryKey: briefingKeys.list(page),
    queryFn: () => briefingApi.listBriefings(page, 20),
    staleTime: STALE_5MIN,
  })
}

export function useTopicsQuery() {
  return useQuery({
    queryKey: briefingKeys.topics(),
    queryFn: () => briefingApi.listTopics(1, 100),
    staleTime: STALE_5MIN,
  })
}

export function useAnalystsQuery() {
  return useQuery({
    queryKey: briefingKeys.analysts(),
    queryFn: () => briefingApi.listAnalysts(),
    staleTime: STALE_5MIN,
  })
}

export function useRunStatusQuery() {
  return useQuery({
    queryKey: briefingKeys.runStatus(),
    queryFn: () => briefingApi.getRunStatus(),
  })
}

export function useInvalidateBriefing() {
  const queryClient = useQueryClient()
  return {
    invalidateTopics: () => queryClient.invalidateQueries({ queryKey: briefingKeys.topics() }),
    invalidateAnalysts: () => queryClient.invalidateQueries({ queryKey: briefingKeys.analysts() }),
    invalidateRunStatus: () =>
      queryClient.invalidateQueries({ queryKey: briefingKeys.runStatus() }),
  }
}

import { buildParams, createCrudApi, request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  ActivateResponse,
  ActivitySpan,
  ActivitySpanCreate,
  ActivitySpanUpdate,
  DailyPlan,
  DailyPlanStats,
  Method,
  MethodCreate,
  MethodSelection,
  MethodUpdate,
  PlanItem,
  RecurringItem,
  RecurringItemCreate,
  RecurringItemUpdate,
  TaskGroup,
  TaskGroupCreate,
  TaskGroupUpdate,
} from '../types'

export const methodApi = {
  ...createCrudApi<Method, MethodCreate, MethodUpdate>('/dailyos/methods'),

  listAll: (params?: { include_presets?: boolean; page?: number; page_size?: number }) =>
    request<PaginatedResponse<Method>>(
      `/dailyos/methods${buildParams((params ?? {}) as Record<string, unknown>, { page_size: 50 })}`,
    ),

  clone: (id: string) => request<Method>(`/dailyos/methods/${id}/clone`, { method: 'POST' }),

  preview: (id: string) =>
    request<{
      method: Method
      suggested_items: PlanItem[]
      frog_ids: string[]
      warnings: string[]
    }>(`/dailyos/methods/${id}/preview`, { method: 'POST' }),
}

export const configApi = {
  getActive: (context = 'default') =>
    request<MethodSelection[]>(`/dailyos/config/method?context=${context}`),

  activate: (data: { method_id: string; context?: string; overrides?: Record<string, unknown> }) =>
    request<ActivateResponse>('/dailyos/config/method/activate', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  deactivate: (selectionId: string) =>
    request<MethodSelection>(`/dailyos/config/method/${selectionId}`, {
      method: 'DELETE',
    }),

  history: (context = 'default', page = 1) =>
    request<PaginatedResponse<MethodSelection>>(
      `/dailyos/config/method/history?context=${context}&page=${page}`,
    ),

  getGuide: (context = 'default') =>
    request<{ guide: string; method_count: number; method_names: string[] }>(
      `/dailyos/config/guide?context=${context}`,
    ),
}

export const planApi = {
  list: (params?: { page?: number; date_from?: string; date_to?: string }) =>
    request<PaginatedResponse<DailyPlan>>(
      `/dailyos/plans${buildParams((params ?? {}) as Record<string, unknown>)}`,
    ),

  today: () => request<DailyPlan>('/dailyos/plans/today'),

  forDate: (date: string) => request<DailyPlan>(`/dailyos/plans/for-date/${date}`),

  stats: (dateFrom: string, dateTo: string) =>
    request<DailyPlanStats[]>(`/dailyos/plans/stats?date_from=${dateFrom}&date_to=${dateTo}`),

  get: (id: string) => request<DailyPlan>(`/dailyos/plans/${id}`),

  update: (
    id: string,
    data: {
      items?: PlanItem[]
      method_state?: Record<string, unknown>
      reflection?: string
      completion_score?: number
    },
  ) =>
    request<DailyPlan>(`/dailyos/plans/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  transition: (id: string, status: string) =>
    request<DailyPlan>(`/dailyos/plans/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ status }),
    }),
}

export const recurringApi = {
  list: () => request<RecurringItem[]>('/dailyos/recurring'),

  create: (data: RecurringItemCreate) =>
    request<RecurringItem>('/dailyos/recurring', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: string, data: RecurringItemUpdate) =>
    request<RecurringItem>(`/dailyos/recurring/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  remove: (id: string) => request<void>(`/dailyos/recurring/${id}`, { method: 'DELETE' }),

  forDate: (date: string) => request<RecurringItem[]>(`/dailyos/recurring/for-date/${date}`),
}

export const taskGroupApi = {
  list: () => request<TaskGroup[]>('/dailyos/groups'),

  create: (data: TaskGroupCreate) =>
    request<TaskGroup>('/dailyos/groups', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: string, data: TaskGroupUpdate) =>
    request<TaskGroup>(`/dailyos/groups/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  remove: (id: string) => request<void>(`/dailyos/groups/${id}`, { method: 'DELETE' }),
}

export const spanApi = {
  list: (params?: { date_from?: string; date_to?: string }) => {
    const qs = new URLSearchParams()
    if (params?.date_from) qs.set('date_from', params.date_from)
    if (params?.date_to) qs.set('date_to', params.date_to)
    const query = qs.toString()
    return request<ActivitySpan[]>(`/dailyos/spans${query ? `?${query}` : ''}`)
  },

  create: (data: ActivitySpanCreate) =>
    request<ActivitySpan>('/dailyos/spans', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: string, data: ActivitySpanUpdate) =>
    request<ActivitySpan>(`/dailyos/spans/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  remove: (id: string) => request<void>(`/dailyos/spans/${id}`, { method: 'DELETE' }),

  forDate: (date: string) => request<ActivitySpan[]>(`/dailyos/spans/for-date/${date}`),

  forRange: (start: string, end: string) =>
    request<ActivitySpan[]>(`/dailyos/spans/for-range?range_start=${start}&range_end=${end}`),
}

import { createCrudApi, request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  Task,
  TaskCreate,
  TaskProgressStats,
  TaskResponse,
  TaskStatus,
  TaskUpdate,
  TaskUpdateCreate,
  TaskUpdateEntry,
} from '../types'

// ─── Base CRUD ───

export const taskApi = {
  ...createCrudApi<Task, TaskCreate, TaskUpdate>('/taskflow/tasks'),

  listFiltered: (params: {
    page?: number
    page_size?: number
    status?: TaskStatus | ''
    source?: string
    project?: string
    priority?: string
    tag?: string
    search?: string
    top_level?: boolean
  }) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== '') qs.set(k, String(v))
    }
    if (!qs.has('page')) qs.set('page', '1')
    if (!qs.has('page_size')) qs.set('page_size', '20')
    return request<PaginatedResponse<Task>>(`/taskflow/tasks?${qs}`)
  },

  transition: (id: string, status: TaskStatus, comment?: string) =>
    request<TaskResponse>(`/taskflow/tasks/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ status, comment }),
    }),

  getSubtasks: (id: string) => request<Task[]>(`/taskflow/tasks/${id}/subtasks`),

  getUpdates: (id: string) => request<TaskUpdateEntry[]>(`/taskflow/tasks/${id}/updates`),

  addUpdate: (id: string, data: TaskUpdateCreate) =>
    request<TaskUpdateEntry>(`/taskflow/tasks/${id}/updates`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}

// ─── Dashboard ───

export const dashboardApi = {
  today: () => request<Task[]>('/taskflow/today'),

  upcoming: (days = 7) => request<Task[]>(`/taskflow/upcoming?days=${days}`),

  progress: () => request<TaskProgressStats>('/taskflow/progress'),
}

// ─── Trash ───

export const trashApi = {
  list: () => request<PaginatedResponse<Task>>('/taskflow/trash'),

  restore: (id: string) =>
    request<TaskResponse>(`/taskflow/trash/${id}/restore`, { method: 'POST' }),
}

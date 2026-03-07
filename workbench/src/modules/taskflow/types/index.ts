import type { BaseEntity } from '@/types'

// ─── Enums ───

export type TaskStatus = 'todo' | 'in_progress' | 'review' | 'done' | 'blocked' | 'cancelled'

export type TaskPriority = 'urgent' | 'high' | 'medium' | 'low'

export type TaskSource = 'personal' | 'family' | 'company'

export type UpdateType = 'progress' | 'blocker' | 'note'

// ─── Task ───

export interface Task extends BaseEntity {
  title: string
  description: string | null
  status: TaskStatus
  priority: TaskPriority
  source: TaskSource
  project: string | null
  tags: string[]
  due_date: string | null
  scheduled_at: string | null
  estimated_hours: number | null
  actual_hours: number | null
  parent_id: string | null
  subtask_count: number
  completed_subtask_count: number
}

export interface TaskCreate {
  title: string
  description?: string
  status?: TaskStatus
  priority?: TaskPriority
  source?: TaskSource
  project?: string
  tags?: string[]
  due_date?: string
  scheduled_at?: string
  estimated_hours?: number
  parent_id?: string
}

export interface TaskUpdate {
  title?: string
  description?: string
  priority?: TaskPriority
  source?: TaskSource
  project?: string
  tags?: string[]
  due_date?: string
  scheduled_at?: string
  estimated_hours?: number
  actual_hours?: number
}

export interface TaskResponse extends Task {}

// ─── Task Update Entry ───

export interface TaskUpdateEntry extends BaseEntity {
  task_id: string
  update_type: UpdateType
  content: string
  progress_pct: number | null
}

export interface TaskUpdateCreate {
  update_type: UpdateType
  content: string
  progress_pct?: number
}

// ─── Progress Stats ───

export interface TaskProgressStats {
  by_status: Record<TaskStatus, number>
  by_source: Record<TaskSource, number>
  by_priority: Record<TaskPriority, number>
  overdue: number
  total: number
  estimated_hours: number
  actual_hours: number
}

// ─── Display Configs ───

export interface StatusConfig {
  label: string
  color: string
  bgColor: string
  borderColor: string
  icon: string
}

export const STATUS_CONFIG: Record<TaskStatus, StatusConfig> = {
  todo: {
    label: '待辦',
    color: '#a6adc8',
    bgColor: 'rgba(166, 173, 200, 0.15)',
    borderColor: 'rgba(166, 173, 200, 0.3)',
    icon: '○',
  },
  in_progress: {
    label: '進行中',
    color: '#89b4fa',
    bgColor: 'rgba(137, 180, 250, 0.15)',
    borderColor: 'rgba(137, 180, 250, 0.3)',
    icon: '◑',
  },
  review: {
    label: '審查中',
    color: '#f9e2af',
    bgColor: 'rgba(249, 226, 175, 0.15)',
    borderColor: 'rgba(249, 226, 175, 0.3)',
    icon: '◈',
  },
  done: {
    label: '完成',
    color: '#a6e3a1',
    bgColor: 'rgba(166, 227, 161, 0.15)',
    borderColor: 'rgba(166, 227, 161, 0.3)',
    icon: '✓',
  },
  blocked: {
    label: '阻塞',
    color: '#f38ba8',
    bgColor: 'rgba(243, 139, 168, 0.15)',
    borderColor: 'rgba(243, 139, 168, 0.3)',
    icon: '✕',
  },
  cancelled: {
    label: '取消',
    color: '#585b70',
    bgColor: 'rgba(88, 91, 112, 0.15)',
    borderColor: 'rgba(88, 91, 112, 0.3)',
    icon: '⊘',
  },
}

export interface PriorityConfig {
  label: string
  color: string
  bgColor: string
}

export const PRIORITY_CONFIG: Record<TaskPriority, PriorityConfig> = {
  urgent: {
    label: '緊急',
    color: '#f38ba8',
    bgColor: 'rgba(243, 139, 168, 0.15)',
  },
  high: {
    label: '高',
    color: '#fab387',
    bgColor: 'rgba(250, 179, 135, 0.15)',
  },
  medium: {
    label: '中',
    color: '#89b4fa',
    bgColor: 'rgba(137, 180, 250, 0.15)',
  },
  low: {
    label: '低',
    color: '#a6adc8',
    bgColor: 'rgba(166, 173, 200, 0.15)',
  },
}

export interface SourceConfig {
  label: string
  color: string
  icon: string
}

export const SOURCE_CONFIG: Record<TaskSource, SourceConfig> = {
  personal: { label: '個人', color: '#cba6f7', icon: '👤' },
  family: { label: '家庭', color: '#f9e2af', icon: '🏠' },
  company: { label: '公司', color: '#89b4fa', icon: '💼' },
}

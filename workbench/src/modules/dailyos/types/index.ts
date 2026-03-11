import type { BaseEntity } from '@/types'

// ─── Method ───

export type LayoutType = 'list' | 'columns' | 'timeline' | 'grid' | 'kanban'

export interface Method extends BaseEntity {
  slug: string
  name: string
  name_zh: string | null
  description: string | null
  icon: string | null
  color: string | null
  is_preset: boolean
  cloned_from_id: string | null
  config: MethodConfig
  version: number
  layout_type: LayoutType
  tags: string[] | null
}

export interface MethodCreate {
  slug: string
  name: string
  name_zh?: string
  description?: string
  icon?: string
  color?: string
  config: MethodConfig
  layout_type?: LayoutType
  tags?: string[]
}

export interface MethodUpdate {
  name?: string
  name_zh?: string
  description?: string
  icon?: string
  color?: string
  config?: MethodConfig
  layout_type?: LayoutType
  tags?: string[]
}

// ─── Method Config (JSONB) ───

export interface CategoryDef {
  id: string
  name: string
  name_zh?: string
  icon?: string
  color?: string
  max_items: number | null
  min_items: number
  sort_order: number
  priority_weight: number
  accept_filter?: Record<string, unknown>
}

export interface FrogConfig {
  enabled: boolean
  count?: number
  label?: string
  label_zh?: string
  icon?: string
  auto_suggest?: boolean
  suggest_criteria?: {
    prefer_high_priority?: boolean
    prefer_dreaded?: boolean
    prefer_high_impact?: boolean
    max_age_days?: number
  }
  must_do_first?: boolean
}

export interface TimeAwareness {
  enabled: boolean
  mode: 'blocks' | 'estimates' | 'none'
  day_start?: string
  day_end?: string
  slot_duration_minutes?: number
  include_breaks?: boolean
  break_pattern?: { work_minutes: number; break_minutes: number }
  pomodoro?: {
    work_minutes: number
    short_break: number
    long_break: number
    long_break_interval: number
  } | null
}

export interface ReviewCycleEntry {
  enabled: boolean
  default_time?: string
  prompt?: string
  prompt_zh?: string
  day_of_week?: number
}

export interface CompletionRule {
  mode: 'all' | 'percentage' | 'frog_plus_percentage' | 'weighted'
  threshold?: number
  frog_required?: boolean
  streak_tracking?: boolean
  celebration?: Record<string, string>
}

export interface OverflowConfig {
  mode: 'carry_forward' | 'review_then_decide' | 'drop' | 'backlog'
  max_carry_days?: number | null
  carry_limit?: number | null
  stale_warning_days?: number
}

export interface MethodConfig {
  dimensions?: string[]
  max_items?: number | null
  categories?: CategoryDef[]
  ordering?: 'sequential' | 'priority' | 'time' | 'free' | 'category'
  sequential_strict?: boolean
  frog?: FrogConfig
  time_awareness?: TimeAwareness
  review_cycle?: {
    morning_review?: ReviewCycleEntry
    midday_check?: ReviewCycleEntry
    evening_review?: ReviewCycleEntry
    weekly_review?: ReviewCycleEntry
  }
  completion_rule?: CompletionRule
  overflow?: OverflowConfig
  item_sources?: Record<string, { enabled: boolean; [key: string]: unknown }>
  ui_hints?: {
    show_numbers?: boolean
    show_category_headers?: boolean
    show_progress_bar?: boolean
    show_time_column?: boolean
    show_frog_badge?: boolean
    empty_state_message?: string
    empty_state_message_zh?: string
    compact_mode?: boolean
  }
}

// ─── Method Selection ───

export interface MethodSelection extends BaseEntity {
  method_id: string
  context: string
  is_active: boolean
  overrides: Partial<MethodConfig> | null
  activated_at: string
  deactivated_at: string | null
  method: Method | null
}

export interface DimensionConflict {
  dimension: string
  replaced_method_id: string
  replaced_method_name: string
}

export interface ActivateResponse {
  selection: MethodSelection
  replaced: DimensionConflict[]
  active_count: number
}

// ─── Daily Plan ───

export type PlanStatus = 'planning' | 'active' | 'reviewing' | 'completed'

export interface PlanItem {
  id: string
  title: string
  source_module?: string
  source_id?: string
  category?: string
  priority?: string
  status: 'pending' | 'done' | 'cancelled'
  is_frog?: boolean
  sort_order: number
  estimated_hours?: number
  scheduled_time?: string
  carry_count?: number
  group_id?: string
}

export interface DailyPlan extends BaseEntity {
  plan_date: string
  context: string
  method_selection_id: string | null
  status: PlanStatus
  items: PlanItem[]
  method_state: Record<string, unknown> | null
  reflection: string | null
  completion_score: number | null
}

// ─── Plan Stats ───

export interface DailyPlanStats {
  plan_date: string
  status: PlanStatus
  total_items: number
  done_count: number
  completion_score: number
}

// ─── Task Group ───

export interface TaskGroup {
  id: string
  name: string
  color: string
  icon: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface TaskGroupCreate {
  name: string
  color?: string
  icon?: string
  sort_order?: number
}

export type TaskGroupUpdate = Partial<TaskGroupCreate>

// ─── Recurring Item ───

export interface RecurringItem {
  id: string
  title: string
  recurrence_type: 'daily' | 'weekly' | 'monthly'
  day_of_week?: number // 0=Mon...6=Sun
  day_of_month?: number // 1-31
  start_time?: string // "HH:MM"
  end_time?: string // "HH:MM"
  category?: string
  group_id?: string
  is_active: boolean
  created_at?: string
  updated_at?: string
}

export type RecurringItemCreate = Omit<
  RecurringItem,
  'id' | 'is_active' | 'created_at' | 'updated_at'
>
export type RecurringItemUpdate = Partial<RecurringItemCreate> & { is_active?: boolean }

// ─── Plan Status Config ───

export interface PlanStatusConfig {
  label: string
  color: string
  bgColor: string
  icon: string
}

export const PLAN_STATUS_CONFIG: Record<PlanStatus, PlanStatusConfig> = {
  planning: {
    label: '規劃中',
    color: '#a6adc8',
    bgColor: 'rgba(166, 173, 200, 0.15)',
    icon: 'pencil',
  },
  active: { label: '執行中', color: '#89b4fa', bgColor: 'rgba(137, 180, 250, 0.15)', icon: 'play' },
  reviewing: {
    label: '回顧中',
    color: '#f9e2af',
    bgColor: 'rgba(249, 226, 175, 0.15)',
    icon: 'eye',
  },
  completed: {
    label: '已完成',
    color: '#a6e3a1',
    bgColor: 'rgba(166, 227, 161, 0.15)',
    icon: 'check-circle',
  },
}

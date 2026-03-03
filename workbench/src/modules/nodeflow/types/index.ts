import type { BaseEntity } from '@/types'

// ======================== Node Types ========================

export type NodeType = 'trigger' | 'action' | 'condition' | 'transform' | 'notify' | 'delay'
export type TriggerType = 'event' | 'schedule' | 'manual'
export type FlowStatus = 'draft' | 'active' | 'paused' | 'archived'
export type RunStatus = 'running' | 'completed' | 'failed' | 'cancelled'
export type NodeRunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

// ======================== Models ========================

export interface Flow extends BaseEntity {
  name: string
  description?: string | null
  trigger_type: TriggerType
  trigger_config?: Record<string, unknown> | null
  status: FlowStatus
}

export interface FlowNode extends BaseEntity {
  flow_id: string
  node_type: NodeType
  label: string
  config?: Record<string, unknown> | null
  position_x: number
  position_y: number
}

export interface FlowEdge extends BaseEntity {
  flow_id: string
  source_node_id: string
  target_node_id: string
  source_port: string
}

export interface FlowRun extends BaseEntity {
  flow_id: string
  status: RunStatus
  trigger_event?: Record<string, unknown> | null
  started_at: string
  finished_at?: string | null
  error?: string | null
}

export interface NodeRunLog extends BaseEntity {
  flow_run_id: string
  node_id: string
  status: NodeRunStatus
  input_data?: Record<string, unknown> | null
  output_data?: Record<string, unknown> | null
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface FlowDetail extends Flow {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

export interface FlowRunDetail extends FlowRun {
  node_run_logs: NodeRunLog[]
}

// ======================== Display Config ========================

export const NODE_TYPE_CONFIG: Record<NodeType, { label: string; color: string }> = {
  trigger: { label: '觸發器', color: 'var(--peach)' },
  action: { label: '動作', color: 'var(--blue)' },
  condition: { label: '條件', color: 'var(--yellow)' },
  transform: { label: '轉換', color: 'var(--teal)' },
  notify: { label: '通知', color: 'var(--mauve)' },
  delay: { label: '延遲', color: 'var(--overlay1)' },
}

export const FLOW_STATUS_CONFIG: Record<FlowStatus, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'var(--overlay1)' },
  active: { label: '啟用', color: 'var(--green)' },
  paused: { label: '暫停', color: 'var(--yellow)' },
  archived: { label: '已封存', color: 'var(--overlay0)' },
}

export const RUN_STATUS_CONFIG: Record<RunStatus, { label: string; color: string }> = {
  running: { label: '執行中', color: 'var(--blue)' },
  completed: { label: '完成', color: 'var(--green)' },
  failed: { label: '失敗', color: 'var(--red)' },
  cancelled: { label: '已取消', color: 'var(--overlay1)' },
}

export const NODE_RUN_STATUS_CONFIG: Record<NodeRunStatus, { label: string; color: string }> = {
  pending: { label: '等待中', color: 'var(--overlay1)' },
  running: { label: '執行中', color: 'var(--blue)' },
  completed: { label: '完成', color: 'var(--green)' },
  failed: { label: '失敗', color: 'var(--red)' },
  skipped: { label: '跳過', color: 'var(--overlay0)' },
}

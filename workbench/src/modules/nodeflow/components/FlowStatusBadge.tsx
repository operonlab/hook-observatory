import type { FlowStatus, NodeRunStatus, RunStatus } from '../types'
import { FLOW_STATUS_CONFIG, NODE_RUN_STATUS_CONFIG, RUN_STATUS_CONFIG } from '../types'

export function FlowStatusBadge({ status }: { status: FlowStatus }) {
  const cfg = FLOW_STATUS_CONFIG[status]
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ backgroundColor: cfg.color, color: 'var(--base)' }}
    >
      {cfg.label}
    </span>
  )
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const cfg = RUN_STATUS_CONFIG[status]
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ backgroundColor: cfg.color, color: 'var(--base)' }}
    >
      {cfg.label}
    </span>
  )
}

export function NodeRunStatusBadge({ status }: { status: NodeRunStatus }) {
  const cfg = NODE_RUN_STATUS_CONFIG[status]
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ backgroundColor: cfg.color, color: 'var(--base)' }}
    >
      {cfg.label}
    </span>
  )
}

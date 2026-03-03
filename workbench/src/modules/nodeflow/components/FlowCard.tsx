import { useNavigate } from 'react-router-dom'
import type { Flow } from '../types'
import { FlowStatusBadge } from './FlowStatusBadge'

const TRIGGER_LABELS: Record<string, string> = {
  event: '事件觸發',
  schedule: '排程觸發',
  manual: '手動觸發',
}

export default function FlowCard({ flow }: { flow: Flow }) {
  const navigate = useNavigate()

  return (
    <button
      type="button"
      className="cursor-pointer rounded-xl p-4 text-left transition-all hover:ring-1 w-full"
      style={
        {
          backgroundColor: 'var(--surface0)',
          '--tw-ring-color': 'var(--accent)',
        } as React.CSSProperties
      }
      onClick={() => navigate(`/nodeflow/${flow.id}`)}
    >
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-semibold" style={{ color: 'var(--text)' }}>
          {flow.name}
        </h3>
        <FlowStatusBadge status={flow.status} />
      </div>
      {flow.description && (
        <p className="mb-2 text-sm" style={{ color: 'var(--subtext0)' }}>
          {flow.description}
        </p>
      )}
      <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--subtext0)' }}>
        <span className="rounded px-1.5 py-0.5" style={{ backgroundColor: 'var(--surface1)' }}>
          {TRIGGER_LABELS[flow.trigger_type] || flow.trigger_type}
        </span>
        {flow.trigger_config?.event_type && (
          <span className="truncate" title={String(flow.trigger_config.event_type)}>
            {String(flow.trigger_config.event_type)}
          </span>
        )}
      </div>
    </button>
  )
}

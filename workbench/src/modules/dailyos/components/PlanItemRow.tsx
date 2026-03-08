import { Check, Circle } from 'lucide-react'
import type { PlanItem } from '../types'

interface PlanItemRowProps {
  item: PlanItem
  index?: number
  showNumber?: boolean
  dimmed?: boolean
  onToggle?: (item: PlanItem) => void
}

const PRIORITY_COLORS: Record<string, string> = {
  urgent: '#f38ba8',
  high: '#fab387',
  medium: '#89b4fa',
  low: '#a6adc8',
}

export default function PlanItemRow({
  item,
  index,
  showNumber,
  dimmed,
  onToggle,
}: PlanItemRowProps) {
  const isDone = item.status === 'done'
  const isCancelled = item.status === 'cancelled'
  const opacity = dimmed ? 0.4 : 1

  return (
    <div
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors group"
      style={{
        backgroundColor: 'var(--do-bg-elevated)',
        opacity,
      }}
    >
      {/* Number */}
      {showNumber && index !== undefined && (
        <span
          className="text-[11px] font-mono w-5 text-center shrink-0"
          style={{ color: 'var(--do-text-muted)' }}
        >
          {index + 1}
        </span>
      )}

      {/* Checkbox */}
      <button
        type="button"
        onClick={() => onToggle?.(item)}
        className="shrink-0 transition-colors"
        style={{ color: isDone ? 'var(--do-completed)' : 'var(--do-text-muted)' }}
      >
        {isDone ? <Check size={16} /> : <Circle size={16} />}
      </button>

      {/* Frog Badge */}
      {item.is_frog && (
        <span
          className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
          style={{
            color: 'var(--do-frog)',
            backgroundColor: 'var(--do-frog-alpha)',
          }}
        >
          🐸
        </span>
      )}

      {/* Title */}
      <span
        className="flex-1 text-[13px] min-w-0 truncate"
        style={{
          color: isDone || isCancelled ? 'var(--do-text-muted)' : 'var(--do-text)',
          textDecoration: isDone ? 'line-through' : 'none',
        }}
      >
        {item.title}
      </span>

      {/* Category Badge */}
      {item.category && (
        <span
          className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
          style={{
            color: 'var(--do-text-tertiary)',
            backgroundColor: 'var(--do-bg-surface)',
          }}
        >
          {item.category}
        </span>
      )}

      {/* Priority Dot */}
      {item.priority && (
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: PRIORITY_COLORS[item.priority] || 'var(--do-text-muted)' }}
        />
      )}

      {/* Carry Count */}
      {item.carry_count && item.carry_count > 0 && (
        <span
          className="text-[10px] shrink-0"
          style={{ color: 'var(--do-urgent)' }}
          title={`已延遲 ${item.carry_count} 天`}
        >
          +{item.carry_count}d
        </span>
      )}
    </div>
  )
}

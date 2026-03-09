import { Bug, Check, ChevronDown, ChevronUp, Circle, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { PlanItem } from '../types'

interface PlanItemRowProps {
  item: PlanItem
  index?: number
  showNumber?: boolean
  dimmed?: boolean
  onToggle?: (item: PlanItem) => void
  onEdit?: (itemId: string, updates: Partial<PlanItem>) => void
  onRemove?: (itemId: string) => void
  onReorder?: (itemId: string, direction: 'up' | 'down') => void
  showReorder?: boolean
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
  onEdit,
  onRemove,
  onReorder,
  showReorder,
}: PlanItemRowProps) {
  const isDone = item.status === 'done'
  const isCancelled = item.status === 'cancelled'
  const opacity = dimmed ? 0.4 : 1

  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [hovered, setHovered] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const handleSave = () => {
    const trimmed = editTitle.trim()
    if (trimmed && trimmed !== item.title) {
      onEdit?.(item.id, { title: trimmed })
    }
    setEditing(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSave()
    if (e.key === 'Escape') setEditing(false)
  }

  const priorityColor = item.priority
    ? PRIORITY_COLORS[item.priority] || 'var(--do-text-muted)'
    : null

  return (
    <div
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg group"
      style={{
        backgroundColor: hovered ? 'rgba(42, 42, 62, 0.5)' : 'var(--do-bg-elevated)',
        opacity,
        transition: 'background-color 150ms ease',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
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
        className="shrink-0 cursor-pointer"
        style={{
          color: isDone ? 'var(--do-completed)' : 'var(--do-text-muted)',
          transition: 'color 200ms ease, transform 200ms ease',
          transform: isDone ? 'scale(1.1)' : 'scale(1)',
        }}
      >
        {isDone ? <Check size={16} strokeWidth={2.5} /> : <Circle size={16} />}
      </button>

      {/* Frog Badge — "eat the frog" indicator */}
      {item.is_frog && (
        <span
          className="flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded shrink-0"
          style={{
            color: '#94e2d5',
            backgroundColor: 'rgba(148, 226, 213, 0.12)',
          }}
        >
          <Bug size={12} />
        </span>
      )}

      {/* Title */}
      {editing ? (
        <input
          ref={inputRef}
          type="text"
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={handleSave}
          className="flex-1 text-[13px] min-w-0 bg-transparent outline-none border-b"
          style={{
            color: 'var(--do-text)',
            borderColor: 'var(--do-accent)',
            boxShadow: '0 1px 0 0 var(--do-accent-alpha)',
            transition: 'border-color 150ms ease, box-shadow 150ms ease',
          }}
        />
      ) : (
        <span
          className={`flex-1 text-[13px] min-w-0 truncate ${isDone ? 'strikethrough-animate' : ''}`}
          style={{
            color: isDone || isCancelled ? 'var(--do-text-muted)' : 'var(--do-text)',
            textDecoration: isDone ? 'line-through' : 'none',
            transition: 'color 200ms ease',
          }}
          onDoubleClick={() => {
            setEditTitle(item.title)
            setEditing(true)
          }}
        >
          {item.title}
        </span>
      )}

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
      {priorityColor && (
        <span
          className="w-2 h-2 rounded-full shrink-0"
          style={{
            backgroundColor: priorityColor,
            boxShadow: `0 0 4px ${priorityColor}`,
          }}
        />
      )}

      {/* Carry Count */}
      {item.carry_count && item.carry_count > 0 && (
        <span
          className="text-[10px] shrink-0 px-1.5 py-0.5 rounded-full"
          style={{
            color: 'var(--do-urgent)',
            border: '1px solid rgba(243, 139, 168, 0.3)',
            backgroundColor: 'rgba(243, 139, 168, 0.08)',
            fontFeatureSettings: '"tnum"',
          }}
          title={`已延遲 ${item.carry_count} 天`}
        >
          +{item.carry_count}d
        </span>
      )}

      {/* Hover Actions — fade in */}
      <div
        className="flex items-center gap-0.5 shrink-0"
        style={{
          opacity: hovered ? 1 : 0,
          transition: 'opacity 150ms ease',
          pointerEvents: hovered ? 'auto' : 'none',
        }}
      >
        {showReorder && onReorder && (
          <>
            <button
              type="button"
              onClick={() => onReorder(item.id, 'up')}
              className="p-0.5 rounded cursor-pointer"
              style={{
                color: 'var(--do-text-muted)',
                transition: 'color 150ms ease, background-color 150ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'var(--do-text-secondary)'
                e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.08)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--do-text-muted)'
                e.currentTarget.style.backgroundColor = 'transparent'
              }}
            >
              <ChevronUp size={12} />
            </button>
            <button
              type="button"
              onClick={() => onReorder(item.id, 'down')}
              className="p-0.5 rounded cursor-pointer"
              style={{
                color: 'var(--do-text-muted)',
                transition: 'color 150ms ease, background-color 150ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'var(--do-text-secondary)'
                e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.08)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--do-text-muted)'
                e.currentTarget.style.backgroundColor = 'transparent'
              }}
            >
              <ChevronDown size={12} />
            </button>
          </>
        )}
        {onRemove && (
          <button
            type="button"
            onClick={() => onRemove(item.id)}
            className="p-0.5 rounded cursor-pointer"
            style={{
              color: 'var(--do-text-muted)',
              transition: 'color 150ms ease, background-color 150ms ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = '#f38ba8'
              e.currentTarget.style.backgroundColor = 'rgba(243, 139, 168, 0.1)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--do-text-muted)'
              e.currentTarget.style.backgroundColor = 'transparent'
            }}
          >
            <X size={12} />
          </button>
        )}
      </div>
    </div>
  )
}

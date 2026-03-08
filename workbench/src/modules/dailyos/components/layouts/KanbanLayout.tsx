import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { MethodConfig, PlanItem } from '../../types'

interface KanbanLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
  onMoveRight?: (item: PlanItem) => void
  onMoveLeft?: (item: PlanItem) => void
}

// Kanban uses a 3-column layout: todo -> doing -> done
const KANBAN_COLUMNS = [
  { key: 'todo', label: '待辦', color: '#a6adc8' },
  { key: 'doing', label: '進行中', color: '#89b4fa' },
  { key: 'done', label: '完成', color: '#a6e3a1' },
] as const

export default function KanbanLayout({
  items,
  config,
  onMoveRight,
  onMoveLeft,
}: KanbanLayoutProps) {
  const pendingItems = items
    .filter((i) => i.status === 'pending')
    .sort((a, b) => a.sort_order - b.sort_order)
  const doneItems = items.filter((i) => i.status === 'done')

  // Doing column: frog items first, then items explicitly categorized as "doing"
  const doingItems = pendingItems.filter(
    (i) => i.is_frog || i.category === 'doing',
  )
  const doingIds = new Set(doingItems.map((i) => i.id))
  const todoItems = pendingItems.filter((i) => !doingIds.has(i.id))

  const columnData = [
    { ...KANBAN_COLUMNS[0], items: todoItems },
    { ...KANBAN_COLUMNS[1], items: doingItems },
    { ...KANBAN_COLUMNS[2], items: doneItems },
  ]

  const wipLimit = config.max_items ? Math.ceil(config.max_items / 3) : undefined

  return (
    <div className="grid grid-cols-3 gap-3">
      {columnData.map((col, colIndex) => {
        const isOverWip = wipLimit && col.items.length > wipLimit

        return (
          <div
            key={col.key}
            className="rounded-lg border p-3 min-h-[200px]"
            style={{
              borderColor: isOverWip ? 'var(--do-urgent)' : 'var(--do-border)',
              backgroundColor: 'var(--do-bg-elevated)',
            }}
          >
            {/* Column Header */}
            <div
              className="flex items-center justify-between mb-3 pb-2 border-b"
              style={{ borderColor: 'var(--do-border)' }}
            >
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: col.color }} />
                <span className="text-[13px] font-medium" style={{ color: col.color }}>
                  {col.label}
                </span>
              </div>
              <span
                className="text-[11px]"
                style={{ color: isOverWip ? 'var(--do-urgent)' : 'var(--do-text-muted)' }}
              >
                {col.items.length}
                {wipLimit && ` / ${wipLimit}`}
              </span>
            </div>

            {/* Items */}
            <div className="space-y-1.5">
              {col.items.length === 0 ? (
                <div
                  className="text-[11px] text-center py-4"
                  style={{ color: 'var(--do-text-muted)' }}
                >
                  空
                </div>
              ) : (
                col.items.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center gap-2 px-2.5 py-2 rounded-md"
                    style={{ backgroundColor: 'var(--do-bg-surface)' }}
                  >
                    {/* Move left button */}
                    {onMoveLeft && colIndex > 0 && item.status !== 'done' && (
                      <button
                        type="button"
                        onClick={() => onMoveLeft(item)}
                        className="shrink-0 p-0.5 rounded transition-colors hover:bg-[rgba(255,255,255,0.05)]"
                        style={{ color: 'var(--do-text-muted)' }}
                        title="移動到前一欄"
                      >
                        <ChevronLeft size={14} />
                      </button>
                    )}
                    {item.is_frog && <span className="text-[10px]">🐸</span>}
                    <span
                      className="flex-1 text-[12px] min-w-0 truncate"
                      style={{
                        color: item.status === 'done' ? 'var(--do-text-muted)' : 'var(--do-text)',
                        textDecoration: item.status === 'done' ? 'line-through' : 'none',
                      }}
                    >
                      {item.title}
                    </span>
                    {/* Move right button */}
                    {onMoveRight && colIndex < KANBAN_COLUMNS.length - 1 && (
                      <button
                        type="button"
                        onClick={() => onMoveRight(item)}
                        className="shrink-0 p-0.5 rounded transition-colors hover:bg-[rgba(255,255,255,0.05)]"
                        style={{ color: 'var(--do-text-muted)' }}
                        title="移動到下一欄"
                      >
                        <ChevronRight size={14} />
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

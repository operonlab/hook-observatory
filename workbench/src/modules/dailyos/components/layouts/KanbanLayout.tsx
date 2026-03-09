import type { DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  pointerWithin,
  useDroppable,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  Bug,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Circle,
  GripVertical,
  Loader,
} from 'lucide-react'
import { useState } from 'react'
import type { MethodConfig, PlanItem } from '../../types'

interface KanbanLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
  onMoveRight?: (item: PlanItem) => void
  onMoveLeft?: (item: PlanItem) => void
  onDragToColumn?: (itemId: string, column: 'todo' | 'doing' | 'done') => void
}

// Kanban uses a 3-column layout: todo -> doing -> done
const KANBAN_COLUMNS = [
  { key: 'todo', label: '待辦', color: '#a6adc8', icon: Circle },
  { key: 'doing', label: '進行中', color: '#89b4fa', icon: Loader },
  { key: 'done', label: '完成', color: '#a6e3a1', icon: CheckCircle },
] as const

type ColumnKey = (typeof KANBAN_COLUMNS)[number]['key']

interface KanbanItemProps {
  item: PlanItem
  colIndex: number
  onMoveLeft?: (item: PlanItem) => void
  onMoveRight?: (item: PlanItem) => void
}

function KanbanItem({ item, colIndex, onMoveLeft, onMoveRight }: KanbanItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: item.id,
    data: { type: 'kanban-item', item },
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    position: 'relative' as const,
    zIndex: isDragging ? 10 : undefined,
  }

  return (
    <div
      ref={setNodeRef}
      style={{ ...style, backgroundColor: 'var(--do-bg-surface)' }}
      className="flex items-center gap-2 px-2.5 py-2 rounded-md"
    >
      {/* Drag handle */}
      <button
        type="button"
        className="shrink-0 p-0.5 cursor-grab active:cursor-grabbing touch-none"
        style={{ color: 'var(--do-text-muted)' }}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={12} />
      </button>
      {/* Move left button */}
      {onMoveLeft && colIndex > 0 && (
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
      {item.is_frog && <Bug size={11} style={{ color: '#94e2d5', flexShrink: 0 }} />}
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
  )
}

interface DroppableColumnProps {
  id: string
  children: React.ReactNode
  isOverWip: boolean
}

function DroppableColumn({ id, children, isOverWip }: DroppableColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id })

  return (
    <div
      ref={setNodeRef}
      className="space-y-1.5 min-h-[60px] rounded-md p-1 transition-colors"
      style={{
        backgroundColor: isOver ? 'rgba(137,180,250,0.08)' : 'transparent',
        outline: isOver ? '1px dashed var(--do-accent)' : 'none',
      }}
    >
      {children}
    </div>
  )
}

export default function KanbanLayout({
  items,
  config,
  onMoveRight,
  onMoveLeft,
  onDragToColumn,
}: KanbanLayoutProps) {
  const pendingItems = items
    .filter((i) => i.status === 'pending')
    .sort((a, b) => a.sort_order - b.sort_order)
  const doneItems = items.filter((i) => i.status === 'done')

  // Doing column: frog items first, then items explicitly categorized as "doing"
  const doingItems = pendingItems.filter((i) => i.is_frog || i.category === 'doing')
  const doingIds = new Set(doingItems.map((i) => i.id))
  const todoItems = pendingItems.filter((i) => !doingIds.has(i.id))

  const columnData: { key: ColumnKey; label: string; color: string; items: PlanItem[] }[] = [
    { ...KANBAN_COLUMNS[0], items: todoItems },
    { ...KANBAN_COLUMNS[1], items: doingItems },
    { ...KANBAN_COLUMNS[2], items: doneItems },
  ]

  const wipLimit = config.max_items ? Math.ceil(config.max_items / 3) : undefined

  const [activeItem, setActiveItem] = useState<PlanItem | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  )

  const handleDragStart = (event: DragStartEvent) => {
    const found = items.find((i) => i.id === event.active.id)
    setActiveItem(found ?? null)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveItem(null)
    const { active, over } = event
    if (!over || !onDragToColumn) return

    const itemId = active.id as string
    const overId = over.id as string

    // Determine target column: either dropped directly on a column droppable,
    // or on another item within a column
    const columnKeys: ColumnKey[] = ['todo', 'doing', 'done']
    let targetColumn: ColumnKey | null = null

    if (columnKeys.includes(overId as ColumnKey)) {
      targetColumn = overId as ColumnKey
    } else {
      // Dropped on an item -- find which column the target item belongs to
      for (const col of columnData) {
        if (col.items.some((i) => i.id === overId)) {
          targetColumn = col.key
          break
        }
      }
    }

    if (!targetColumn) return

    // Find which column the dragged item currently belongs to
    let sourceColumn: ColumnKey | null = null
    for (const col of columnData) {
      if (col.items.some((i) => i.id === itemId)) {
        sourceColumn = col.key
        break
      }
    }

    // Only fire callback if column actually changed
    if (sourceColumn !== targetColumn) {
      onDragToColumn(itemId, targetColumn)
    }
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="grid grid-cols-3 gap-3">
        {columnData.map((col, colIndex) => {
          const isOverWip = !!(wipLimit && col.items.length > wipLimit)
          const colItemIds = col.items.map((i) => i.id)

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
                  <col.icon size={13} style={{ color: col.color }} />
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
              <SortableContext items={colItemIds} strategy={verticalListSortingStrategy}>
                <DroppableColumn id={col.key} isOverWip={isOverWip}>
                  {col.items.length === 0 ? (
                    <div
                      className="text-[11px] text-center py-4 select-none"
                      style={{ color: 'var(--do-text-muted)' }}
                    >
                      —
                    </div>
                  ) : (
                    col.items.map((item) => (
                      <KanbanItem
                        key={item.id}
                        item={item}
                        colIndex={colIndex}
                        onMoveLeft={onMoveLeft}
                        onMoveRight={onMoveRight}
                      />
                    ))
                  )}
                </DroppableColumn>
              </SortableContext>
            </div>
          )
        })}
      </div>
      <DragOverlay dropAnimation={null}>
        {activeItem && (
          <div
            className="px-2.5 py-2 rounded-md text-[12px] shadow-lg"
            style={{
              backgroundColor: 'var(--do-bg-surface)',
              color: 'var(--do-text)',
              border: '1px solid var(--do-accent)',
            }}
          >
            {activeItem.is_frog && <Bug size={11} className="mr-1" style={{ color: '#94e2d5' }} />}
            {activeItem.title}
          </div>
        )}
      </DragOverlay>
    </DndContext>
  )
}

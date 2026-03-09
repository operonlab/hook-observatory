import type { DragEndEvent, DragStartEvent } from '@dnd-kit/core'
import {
  closestCenter,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { arrayMove, SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useState } from 'react'
import type { MethodConfig, PlanItem } from '../../types'
import PlanItemRow from '../PlanItemRow'
import SortableItem from '../SortableItem'

interface ListLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
  onReorder?: (itemId: string, direction: 'up' | 'down') => void
  onReorderItems?: (orderedIds: string[]) => void
  onEdit?: (itemId: string, updates: Partial<PlanItem>) => void
  onRemove?: (itemId: string) => void
}

export default function ListLayout({
  items,
  config,
  onToggle,
  onReorderItems,
  onEdit,
  onRemove,
}: ListLayoutProps) {
  const [activeItem, setActiveItem] = useState<PlanItem | null>(null)
  const showNumbers = config.ui_hints?.show_numbers !== false
  const sequentialStrict = config.sequential_strict === true

  const firstIncompleteIdx = items.findIndex((it) => it.status === 'pending')

  const sorted = [...items].sort((a, b) => a.sort_order - b.sort_order)
  const itemIds = sorted.map((i) => i.id)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  )

  const handleDragStart = (event: DragStartEvent) => {
    const draggedId = String(event.active.id)
    const found = sorted.find((i) => i.id === draggedId) ?? null
    setActiveItem(found)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveItem(null)
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = sorted.findIndex((i) => i.id === active.id)
    const newIndex = sorted.findIndex((i) => i.id === over.id)
    if (oldIndex < 0 || newIndex < 0) return
    const reordered = arrayMove(sorted, oldIndex, newIndex)
    onReorderItems?.(reordered.map((i) => i.id))
  }

  return (
    <div className="space-y-1.5">
      {sorted.length === 0 ? (
        <div
          className="rounded-lg border p-6 text-center text-[13px]"
          style={{ borderColor: 'var(--do-border)', color: 'var(--do-text-muted)' }}
        >
          {config.ui_hints?.empty_state_message_zh || '尚未新增任何項目'}
        </div>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <SortableContext items={itemIds} strategy={verticalListSortingStrategy}>
            {sorted.map((item, idx) => {
              const dimmed =
                sequentialStrict &&
                item.status === 'pending' &&
                firstIncompleteIdx >= 0 &&
                idx > firstIncompleteIdx

              return (
                <SortableItem
                  key={item.id}
                  item={item}
                  index={idx}
                  showNumber={showNumbers}
                  dimmed={dimmed}
                  onToggle={onToggle}
                  onEdit={onEdit}
                  onRemove={onRemove}
                />
              )
            })}
          </SortableContext>
          <DragOverlay dropAnimation={null}>
            {activeItem && <PlanItemRow item={activeItem} />}
          </DragOverlay>
        </DndContext>
      )}
    </div>
  )
}

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
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { Inbox, X } from 'lucide-react'
import { useState } from 'react'
import type { CategoryDef, MethodConfig, PlanItem } from '../../types'
import PlanItemRow from '../PlanItemRow'
import SortableItem from '../SortableItem'

interface ColumnsLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
  onAssignCategory?: (itemId: string, categoryId: string) => void
  onReorderItems?: (orderedIds: string[]) => void
}

const UNCATEGORIZED_ID = 'uncategorized'

function DroppableColumn({ id, children }: { id: string; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id })
  return (
    <div
      ref={setNodeRef}
      style={{
        outline: isOver ? '2px dashed var(--do-accent)' : undefined,
        outlineOffset: isOver ? '-2px' : undefined,
        borderRadius: isOver ? '8px' : undefined,
        transition: 'outline 150ms ease',
      }}
    >
      {children}
    </div>
  )
}

export default function ColumnsLayout({
  items,
  config,
  onToggle,
  onAssignCategory,
  onReorderItems,
}: ColumnsLayoutProps) {
  const categories = config.categories || []
  const [activeItem, setActiveItem] = useState<PlanItem | null>(null)

  // Sort categories by sort_order
  const sortedCategories = [...categories].sort((a, b) => a.sort_order - b.sort_order)

  // Group items by category, collecting uncategorized separately
  const grouped = new Map<string, PlanItem[]>()
  const knownCatIds = new Set(categories.map((c) => c.id))
  const uncategorizedItems: PlanItem[] = []

  for (const cat of sortedCategories) {
    grouped.set(cat.id, [])
  }
  for (const item of items) {
    if (!item.category || !knownCatIds.has(item.category)) {
      uncategorizedItems.push(item)
    } else {
      const list = grouped.get(item.category)!
      list.push(item)
    }
  }

  // Helper: find which category (or uncategorized) an item belongs to
  const findCategoryForItem = (itemId: string): string | undefined => {
    for (const [catId, catItems] of grouped.entries()) {
      if (catItems.some((i) => i.id === itemId)) return catId
    }
    if (uncategorizedItems.some((i) => i.id === itemId)) return UNCATEGORIZED_ID
    return undefined
  }

  // DnD sensors
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  )

  const handleDragStart = (event: DragStartEvent) => {
    const draggedId = String(event.active.id)
    const found = items.find((i) => i.id === draggedId) ?? null
    setActiveItem(found)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveItem(null)
    const { active, over } = event
    if (!over) return

    const activeId = String(active.id)
    const overId = String(over.id)

    if (activeId === overId) return

    const activeCategory = findCategoryForItem(activeId)

    // Determine the target category:
    // 1. If overId matches a droppable column id (category id or UNCATEGORIZED_ID), use that
    // 2. Otherwise, overId is another item -- find which category that item belongs to
    let overCategory: string | undefined
    if (overId === UNCATEGORIZED_ID || knownCatIds.has(overId)) {
      overCategory = overId
    } else {
      overCategory = findCategoryForItem(overId)
    }

    if (!overCategory || !activeCategory) return

    if (activeCategory !== overCategory && onAssignCategory) {
      // Cross-container move
      onAssignCategory(activeId, overCategory === UNCATEGORIZED_ID ? '' : overCategory)
    } else if (activeCategory === overCategory && onReorderItems) {
      // Same-container reorder
      const containerItems =
        activeCategory === UNCATEGORIZED_ID
          ? [...uncategorizedItems].sort((a, b) => a.sort_order - b.sort_order)
          : [...(grouped.get(activeCategory) || [])].sort((a, b) => a.sort_order - b.sort_order)

      const oldIndex = containerItems.findIndex((i) => i.id === activeId)
      const newIndex = containerItems.findIndex((i) => i.id === overId)
      if (oldIndex < 0 || newIndex < 0 || oldIndex === newIndex) return

      const reordered = [...containerItems]
      const [moved] = reordered.splice(oldIndex, 1)
      reordered.splice(newIndex, 0, moved)
      onReorderItems(reordered.map((i) => i.id))
    }
  }

  if (categories.length === 0) {
    return (
      <div
        className="rounded-lg border p-6 text-center text-[13px]"
        style={{ borderColor: 'var(--do-border)', color: 'var(--do-text-muted)' }}
      >
        此方法論尚未定義分類
      </div>
    )
  }

  // Prepare sorted item arrays and their IDs for each sortable context
  const sortedGrouped = new Map<string, PlanItem[]>()
  for (const [catId, catItems] of grouped.entries()) {
    sortedGrouped.set(
      catId,
      [...catItems].sort((a, b) => a.sort_order - b.sort_order),
    )
  }
  const sortedUncategorized = [...uncategorizedItems].sort((a, b) => a.sort_order - b.sort_order)

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="space-y-3">
        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: `repeat(${Math.min(categories.length, 3)}, 1fr)` }}
        >
          {sortedCategories.map((cat: CategoryDef) => {
            const catItems = sortedGrouped.get(cat.id) || []
            const catItemIds = catItems.map((i) => i.id)
            const doneCount = catItems.filter((i) => i.status === 'done').length
            return (
              <DroppableColumn key={cat.id} id={cat.id}>
                <div
                  className="rounded-lg border p-3"
                  style={{
                    borderColor: 'var(--do-border)',
                    backgroundColor: 'var(--do-bg-elevated)',
                  }}
                >
                  {/* Column Header */}
                  <div
                    className="flex items-center justify-between mb-3 pb-2 border-b"
                    style={{ borderColor: 'var(--do-border)' }}
                  >
                    <div className="flex items-center gap-1.5">
                      <span
                        className="w-2.5 h-2.5 rounded-sm shrink-0"
                        style={{ backgroundColor: cat.color || '#89b4fa' }}
                      />
                      <span
                        className="text-[13px] font-medium"
                        style={{ color: cat.color || 'var(--do-text)' }}
                      >
                        {cat.name_zh || cat.name}
                      </span>
                    </div>
                    <span className="text-[11px]" style={{ color: 'var(--do-text-muted)' }}>
                      {doneCount}/{catItems.length}
                      {cat.max_items != null && ` (最多 ${cat.max_items})`}
                    </span>
                  </div>

                  {/* Items */}
                  <SortableContext items={catItemIds} strategy={verticalListSortingStrategy}>
                    <div className="space-y-1">
                      {catItems.length === 0 ? (
                        <div
                          className="text-[11px] text-center py-3 select-none"
                          style={{ color: 'var(--do-text-muted)' }}
                        >
                          —
                        </div>
                      ) : (
                        catItems.map((item) => (
                          <div key={item.id} className="group/item relative">
                            <SortableItem item={item} onToggle={onToggle} />
                            {/* Reassign / remove buttons on hover */}
                            {onAssignCategory && (
                              <div
                                className="hidden group-hover/item:flex items-center gap-0.5 absolute right-1 top-1/2 -translate-y-1/2 bg-[var(--do-bg-elevated)] rounded px-0.5 py-0.5 shadow-sm border"
                                style={{ borderColor: 'var(--do-border)' }}
                              >
                                {sortedCategories
                                  .filter((c) => c.id !== cat.id)
                                  .map((targetCat) => {
                                    const tc = targetCat.color || '#89b4fa'
                                    return (
                                      <button
                                        key={targetCat.id}
                                        type="button"
                                        title={`移至${targetCat.name_zh || targetCat.name}`}
                                        onClick={() => onAssignCategory(item.id, targetCat.id)}
                                        className="w-4 h-4 rounded text-[7px] font-bold transition-opacity hover:opacity-100 opacity-70"
                                        style={{
                                          backgroundColor: `${tc}33`,
                                          color: tc,
                                        }}
                                      >
                                        {(targetCat.name_zh || targetCat.name)[0]}
                                      </button>
                                    )
                                  })}
                                <button
                                  type="button"
                                  title="移回未分類"
                                  onClick={() => onAssignCategory(item.id, '')}
                                  className="w-4 h-4 rounded text-[7px] transition-opacity hover:opacity-100 opacity-70"
                                  style={{
                                    backgroundColor: 'var(--do-bg-surface)',
                                    color: 'var(--do-text-muted)',
                                  }}
                                >
                                  <X size={8} />
                                </button>
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </SortableContext>
                </div>
              </DroppableColumn>
            )
          })}
        </div>

        {/* Uncategorized Items */}
        {uncategorizedItems.length > 0 && (
          <DroppableColumn id={UNCATEGORIZED_ID}>
            <div
              className="rounded-lg border p-3 col-span-full"
              style={{
                borderColor: 'var(--do-border)',
                borderStyle: 'dashed',
                backgroundColor: 'var(--do-bg-elevated)',
              }}
            >
              <div
                className="flex items-center gap-1.5 mb-2 pb-1.5 border-b"
                style={{ borderColor: 'var(--do-border)' }}
              >
                <Inbox size={14} style={{ color: 'var(--do-text-secondary)' }} />
                <span
                  className="text-[12px] font-medium"
                  style={{ color: 'var(--do-text-secondary)' }}
                >
                  未分類
                </span>
                <span className="text-[10px] ml-auto" style={{ color: 'var(--do-text-muted)' }}>
                  {uncategorizedItems.length}
                </span>
              </div>
              <div className="text-[10px] mb-2" style={{ color: 'var(--do-text-muted)' }}>
                拖曳項目到上方欄位，或點擊色塊按鈕分配
              </div>
              <SortableContext
                items={sortedUncategorized.map((i) => i.id)}
                strategy={verticalListSortingStrategy}
              >
                <div className="space-y-1.5">
                  {sortedUncategorized.map((item) => (
                    <div key={item.id} className="flex items-center gap-2">
                      <div className="flex-1 min-w-0">
                        <SortableItem item={item} onToggle={onToggle} />
                      </div>
                      {onAssignCategory && (
                        <div className="flex gap-1 shrink-0">
                          {sortedCategories.map((cat) => (
                            <button
                              key={cat.id}
                              type="button"
                              title={cat.name_zh || cat.name}
                              onClick={() => onAssignCategory(item.id, cat.id)}
                              className="w-5 h-5 rounded text-[8px] font-bold transition-opacity hover:opacity-100 opacity-60"
                              style={{
                                backgroundColor: `${cat.color || '#89b4fa'}33`,
                                color: cat.color || '#89b4fa',
                                border: `1px solid ${cat.color || '#89b4fa'}66`,
                              }}
                            >
                              {(cat.name_zh || cat.name)[0]}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </SortableContext>
            </div>
          </DroppableColumn>
        )}
      </div>

      {/* Drag Overlay — shows a ghost of the dragged item */}
      <DragOverlay dropAnimation={null}>
        {activeItem ? (
          <div
            className="rounded border px-2 py-1 shadow-lg"
            style={{
              backgroundColor: 'var(--do-bg-elevated)',
              borderColor: 'var(--do-accent)',
              opacity: 0.9,
            }}
          >
            <PlanItemRow item={activeItem} onToggle={undefined} />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}

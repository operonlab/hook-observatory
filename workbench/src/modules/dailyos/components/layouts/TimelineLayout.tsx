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
import { CalendarClock, Clock, X } from 'lucide-react'
import { useState } from 'react'
import type { MethodConfig, PlanItem } from '../../types'
import PlanItemRow from '../PlanItemRow'
import SortableItem from '../SortableItem'
import TimePicker from '../TimePicker'

interface TimelineLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
  onSchedule?: (itemId: string, time: string | undefined) => void
}

function generateTimeSlots(start: string, end: string, slotMinutes: number): string[] {
  const slots: string[] = []
  const [sh, sm] = start.split(':').map(Number)
  const [eh, em] = end.split(':').map(Number)
  let totalStart = sh * 60 + sm
  const totalEnd = eh * 60 + em

  while (totalStart < totalEnd) {
    const h = Math.floor(totalStart / 60)
    const m = totalStart % 60
    slots.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)
    totalStart += slotMinutes
  }
  return slots
}

interface DroppableSlotProps {
  id: string
  children: React.ReactNode
}

function DroppableSlot({ id, children }: DroppableSlotProps) {
  const { setNodeRef, isOver } = useDroppable({ id })

  return (
    <div
      ref={setNodeRef}
      className="flex-1 pb-1 rounded-md transition-colors"
      style={{
        backgroundColor: isOver ? 'rgba(137,180,250,0.08)' : 'transparent',
        outline: isOver ? '1px dashed var(--do-accent)' : 'none',
      }}
    >
      {children}
    </div>
  )
}

interface DroppableUnscheduledProps {
  children: React.ReactNode
}

function DroppableUnscheduled({ children }: DroppableUnscheduledProps) {
  const { setNodeRef, isOver } = useDroppable({ id: 'unscheduled' })

  return (
    <div
      ref={setNodeRef}
      className="space-y-1 ml-6 rounded-md p-1 transition-colors"
      style={{
        backgroundColor: isOver ? 'rgba(137,180,250,0.08)' : 'transparent',
        outline: isOver ? '1px dashed var(--do-accent)' : 'none',
      }}
    >
      {children}
    </div>
  )
}

export default function TimelineLayout({
  items,
  config,
  onToggle,
  onSchedule,
}: TimelineLayoutProps) {
  const [activeItem, setActiveItem] = useState<PlanItem | null>(null)
  const [editingItemId, setEditingItemId] = useState<string | null>(null)

  const timeConfig = config.time_awareness
  const dayStart = timeConfig?.day_start || '09:00'
  const dayEnd = timeConfig?.day_end || '18:00'
  const slotMinutes = timeConfig?.slot_duration_minutes || 60

  const slots = generateTimeSlots(dayStart, dayEnd, slotMinutes)

  // Group items by scheduled_time slot
  const itemsBySlot = new Map<string, PlanItem[]>()
  const unscheduled: PlanItem[] = []

  for (const item of items) {
    if (item.scheduled_time) {
      const slotKey = item.scheduled_time.slice(0, 5) // "HH:MM"
      const list = itemsBySlot.get(slotKey) || []
      list.push(item)
      itemsBySlot.set(slotKey, list)
    } else {
      unscheduled.push(item)
    }
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  )

  const handleDragStart = (event: DragStartEvent) => {
    const draggedItem = items.find((i) => i.id === event.active.id)
    setActiveItem(draggedItem || null)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveItem(null)

    const { active, over } = event
    if (!over || !onSchedule) return

    const itemId = active.id as string
    const overId = over.id as string

    if (overId === 'unscheduled') {
      // Dropped on unscheduled zone -- unschedule the item
      onSchedule(itemId, undefined)
    } else if (slots.includes(overId)) {
      // Dropped on a time slot
      onSchedule(itemId, overId)
    } else {
      // Dropped on another item -- find which slot or zone that item belongs to
      const targetItem = items.find((i) => i.id === overId)
      if (targetItem) {
        if (targetItem.scheduled_time) {
          const slotKey = targetItem.scheduled_time.slice(0, 5)
          onSchedule(itemId, slotKey)
        } else {
          onSchedule(itemId, undefined)
        }
      }
    }
  }

  const unscheduledIds = unscheduled.map((i) => i.id)

  // Empty state when no items exist
  if (items.length === 0) {
    const emptyMessage =
      config.ui_hints?.empty_state_message_zh ||
      config.ui_hints?.empty_state_message ||
      '拖入任務到時間軸，規劃你的一天'

    return (
      <div
        className="rounded-lg border p-8 text-center"
        style={{
          borderColor: 'var(--do-border)',
          backgroundColor: 'var(--do-bg-elevated)',
        }}
      >
        <CalendarClock
          size={32}
          className="mx-auto mb-3"
          style={{ color: 'var(--do-text-muted)' }}
        />
        <p className="text-[13px] mb-1" style={{ color: 'var(--do-text-secondary)' }}>
          {emptyMessage}
        </p>
        <p className="text-[11px]" style={{ color: 'var(--do-text-muted)' }}>
          {dayStart} - {dayEnd}
        </p>
      </div>
    )
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="space-y-1">
        {/* Timeline Slots */}
        {slots.map((slot) => {
          const slotItems = itemsBySlot.get(slot) || []

          return (
            <div key={slot} className="flex gap-3 min-h-[48px]">
              {/* Time Label */}
              <div className="w-14 shrink-0 text-right pt-2">
                <span
                  className="text-[11px] font-mono"
                  style={{ color: 'var(--do-text-tertiary)' }}
                >
                  {slot}
                </span>
              </div>

              {/* Divider */}
              <div className="flex flex-col items-center shrink-0">
                <div
                  className="rounded-full mt-2.5"
                  style={{
                    width: slotItems.length > 0 ? 10 : 8,
                    height: slotItems.length > 0 ? 10 : 8,
                    backgroundColor: slotItems.length > 0 ? 'var(--do-accent)' : 'var(--do-border)',
                    transition: 'all 150ms ease',
                  }}
                />
                <div className="w-px flex-1" style={{ backgroundColor: 'var(--do-border)' }} />
              </div>

              {/* Content -- droppable slot */}
              <DroppableSlot id={slot}>
                {slotItems.length > 0 ? (
                  <div className="space-y-1">
                    {slotItems.map((item) => (
                      <div key={item.id} className="group flex items-center">
                        <div className="flex-1 min-w-0">
                          <PlanItemRow item={item} onToggle={onToggle} />
                        </div>
                        {onSchedule && (
                          <div className="hidden group-hover:flex items-center gap-0.5 shrink-0 ml-1">
                            {editingItemId === item.id ? (
                              <TimePicker
                                compact
                                value={item.scheduled_time?.slice(0, 5)}
                                onChange={(time) => {
                                  onSchedule(item.id, time)
                                  setEditingItemId(null)
                                }}
                                onCancel={() => setEditingItemId(null)}
                              />
                            ) : (
                              <button
                                type="button"
                                onClick={() => setEditingItemId(item.id)}
                                className="p-0.5 rounded transition-colors"
                                style={{
                                  color: 'var(--do-text-muted)',
                                  backgroundColor: 'var(--do-bg-surface)',
                                }}
                                title="修改時間"
                              >
                                <Clock size={12} />
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => onSchedule(item.id, undefined)}
                              className="text-[9px] px-1 py-0.5 rounded"
                              style={{
                                color: 'var(--do-text-muted)',
                                backgroundColor: 'var(--do-bg-surface)',
                              }}
                              title="取消排定"
                            >
                              <X size={10} />
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : slotItems.length === 0 && onSchedule && unscheduled.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => onSchedule(unscheduled[0].id, slot)}
                    className="w-full py-2 text-[11px] text-left rounded transition-colors hover:bg-[rgba(137,180,250,0.08)]"
                    style={{ color: 'var(--do-text-muted)' }}
                    title={`排入: ${unscheduled[0].title}`}
                  >
                    <span style={{ color: 'var(--do-text-muted)' }}>+ 排入項目</span>
                  </button>
                ) : (
                  <div className="py-2 text-[11px]" style={{ color: 'var(--do-text-muted)' }}>
                    &nbsp;
                  </div>
                )}
              </DroppableSlot>
            </div>
          )
        })}

        {/* Unscheduled Items */}
        {unscheduled.length > 0 && (
          <div className="mt-4">
            <div className="flex items-center gap-2 mb-2">
              <Clock size={12} style={{ color: 'var(--do-text-muted)' }} />
              <span
                className="text-[12px] font-medium"
                style={{ color: 'var(--do-text-secondary)' }}
              >
                未排定時間 ({unscheduled.length})
              </span>
            </div>
            <SortableContext items={unscheduledIds} strategy={verticalListSortingStrategy}>
              <DroppableUnscheduled>
                {unscheduled.map((item) => (
                  <div key={item.id} className="group">
                    <SortableItem item={item} onToggle={onToggle} />
                    {onSchedule && (
                      <div
                        className="ml-6 mt-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150"
                        style={{ pointerEvents: 'none' }}
                      >
                        <div style={{ pointerEvents: 'auto' }}>
                          <TimePicker compact onChange={(time) => onSchedule(item.id, time)} />
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </DroppableUnscheduled>
            </SortableContext>
          </div>
        )}
      </div>

      <DragOverlay dropAnimation={null}>
        {activeItem && <PlanItemRow item={activeItem} />}
      </DragOverlay>
    </DndContext>
  )
}

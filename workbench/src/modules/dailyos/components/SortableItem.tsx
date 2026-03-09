import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical } from 'lucide-react'
import type { PlanItem } from '../types'
import PlanItemRow from './PlanItemRow'

interface SortableItemProps {
  item: PlanItem
  index?: number
  showNumber?: boolean
  dimmed?: boolean
  onToggle?: (item: PlanItem) => void
  onEdit?: (itemId: string, updates: Partial<PlanItem>) => void
  onRemove?: (itemId: string) => void
}

export default function SortableItem({
  item,
  index,
  showNumber,
  dimmed,
  onToggle,
  onEdit,
  onRemove,
}: SortableItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: item.id,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0 : undefined,
    height: isDragging ? 'auto' : undefined,
    zIndex: isDragging ? 10 : undefined,
    position: 'relative' as const,
  }

  return (
    <div ref={setNodeRef} style={style}>
      <div className="flex items-center">
        <button
          type="button"
          className="shrink-0 p-0.5 cursor-grab active:cursor-grabbing touch-none"
          style={{ color: 'var(--do-text-muted)' }}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={14} />
        </button>
        <div className="flex-1 min-w-0">
          <PlanItemRow
            item={item}
            index={index}
            showNumber={showNumber}
            dimmed={dimmed}
            onToggle={onToggle}
            onEdit={onEdit}
            onRemove={onRemove}
          />
        </div>
      </div>
    </div>
  )
}

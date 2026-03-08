import { Clock } from 'lucide-react'
import type { MethodConfig, PlanItem } from '../../types'
import PlanItemRow from '../PlanItemRow'

interface TimelineLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
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

export default function TimelineLayout({ items, config, onToggle }: TimelineLayoutProps) {
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

  return (
    <div className="space-y-1">
      {/* Timeline Slots */}
      {slots.map((slot) => {
        const slotItems = itemsBySlot.get(slot) || []
        const _isBreak =
          timeConfig?.include_breaks && timeConfig?.break_pattern
            ? false // Simplified: no break detection in V1
            : false

        return (
          <div key={slot} className="flex gap-3 min-h-[48px]">
            {/* Time Label */}
            <div className="w-14 shrink-0 text-right pt-2">
              <span className="text-[11px] font-mono" style={{ color: 'var(--do-text-tertiary)' }}>
                {slot}
              </span>
            </div>

            {/* Divider */}
            <div className="flex flex-col items-center shrink-0">
              <div
                className="w-2 h-2 rounded-full mt-2.5"
                style={{
                  backgroundColor: slotItems.length > 0 ? 'var(--do-accent)' : 'var(--do-border)',
                }}
              />
              <div className="w-px flex-1" style={{ backgroundColor: 'var(--do-border)' }} />
            </div>

            {/* Content */}
            <div className="flex-1 pb-1">
              {slotItems.length > 0 ? (
                <div className="space-y-1">
                  {slotItems.map((item) => (
                    <PlanItemRow key={item.id} item={item} onToggle={onToggle} />
                  ))}
                </div>
              ) : (
                <div className="py-2 text-[11px]" style={{ color: 'var(--do-text-muted)' }}>
                  &nbsp;
                </div>
              )}
            </div>
          </div>
        )
      })}

      {/* Unscheduled Items */}
      {unscheduled.length > 0 && (
        <div className="mt-4">
          <div className="flex items-center gap-2 mb-2">
            <Clock size={12} style={{ color: 'var(--do-text-muted)' }} />
            <span className="text-[12px] font-medium" style={{ color: 'var(--do-text-secondary)' }}>
              未排定時間 ({unscheduled.length})
            </span>
          </div>
          <div className="space-y-1 ml-6">
            {unscheduled.map((item) => (
              <PlanItemRow key={item.id} item={item} onToggle={onToggle} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

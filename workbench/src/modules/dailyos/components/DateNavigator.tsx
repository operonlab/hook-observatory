import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useCallback, useMemo } from 'react'

interface DateNavigatorProps {
  currentDate: string // YYYY-MM-DD
  onChange: (date: string) => void
}

function formatDisplay(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000)
  const weekday = d.toLocaleDateString('zh-TW', { weekday: 'short' })
  const monthDay = `${d.getMonth() + 1}/${d.getDate()}`
  if (diff === 0) return `今天 ${monthDay} (${weekday})`
  if (diff === -1) return `昨天 ${monthDay} (${weekday})`
  if (diff === 1) return `明天 ${monthDay} (${weekday})`
  return `${monthDay} (${weekday})`
}

function addDays(dateStr: string, days: number): string {
  const d = new Date(`${dateStr}T00:00:00`)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

function isToday(dateStr: string): boolean {
  return dateStr === new Date().toISOString().slice(0, 10)
}

export function DateNavigator({ currentDate, onChange }: DateNavigatorProps) {
  const prev = useCallback(() => onChange(addDays(currentDate, -1)), [currentDate, onChange])
  const next = useCallback(() => onChange(addDays(currentDate, 1)), [currentDate, onChange])
  const goToday = useCallback(() => onChange(new Date().toISOString().slice(0, 10)), [onChange])
  const display = useMemo(() => formatDisplay(currentDate), [currentDate])
  const todayActive = isToday(currentDate)

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <button
        type="button"
        onClick={prev}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--do-text-secondary)',
          cursor: 'pointer',
          padding: 4,
          borderRadius: 4,
          display: 'flex',
        }}
        title="前一天"
      >
        <ChevronLeft size={20} />
      </button>
      <span
        style={{
          color: 'var(--do-text)',
          fontWeight: 600,
          fontSize: 15,
          minWidth: 140,
          textAlign: 'center',
        }}
      >
        {display}
      </span>
      <button
        type="button"
        onClick={next}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--do-text-secondary)',
          cursor: 'pointer',
          padding: 4,
          borderRadius: 4,
          display: 'flex',
        }}
        title="後一天"
      >
        <ChevronRight size={20} />
      </button>
      {!todayActive && (
        <button
          type="button"
          onClick={goToday}
          style={{
            background: 'var(--do-accent-alpha)',
            border: '1px solid var(--do-accent-dim)',
            color: 'var(--do-accent)',
            cursor: 'pointer',
            padding: '2px 10px',
            borderRadius: 12,
            fontSize: 12,
            fontWeight: 500,
          }}
        >
          今天
        </button>
      )}
    </div>
  )
}

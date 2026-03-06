import { ChevronLeft, ChevronRight } from 'lucide-react'

interface DateNavigatorProps {
  date: string // YYYY-MM-DD
  onDateChange: (date: string) => void
}

function addDays(dateStr: string, days: number): string {
  const d = new Date(dateStr + 'T00:00:00')
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

function formatDate(dateStr: string): string {
  return new Date(dateStr + 'T00:00:00').toLocaleDateString('zh-TW', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  })
}

function isToday(dateStr: string): boolean {
  return dateStr === new Date().toISOString().slice(0, 10)
}

export default function DateNavigator({ date, onDateChange }: DateNavigatorProps) {
  const today = new Date().toISOString().slice(0, 10)
  const canGoForward = date < today

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={() => onDateChange(addDays(date, -1))}
        className="p-2 transition-colors"
        style={{ color: 'var(--bf-text-tertiary)' }}
        onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--bf-accent)' }}
        onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--bf-text-tertiary)' }}
      >
        <ChevronLeft size={18} />
      </button>

      <div className="text-center">
        <h1
          className="text-xl sm:text-2xl font-light"
          style={{ fontFamily: 'var(--bf-font-display)', color: 'var(--bf-text)' }}
        >
          {formatDate(date)}
        </h1>
        {isToday(date) && (
          <span
            className="text-[10px] uppercase tracking-widest"
            style={{ color: 'var(--bf-accent)' }}
          >
            Today
          </span>
        )}
      </div>

      <button
        onClick={() => canGoForward && onDateChange(addDays(date, 1))}
        className="p-2 transition-colors"
        style={{
          color: canGoForward ? 'var(--bf-text-tertiary)' : 'var(--bf-text-dim)',
          cursor: canGoForward ? 'pointer' : 'not-allowed',
        }}
        onMouseEnter={(e) => {
          if (canGoForward) e.currentTarget.style.color = 'var(--bf-accent)'
        }}
        onMouseLeave={(e) => {
          if (canGoForward) e.currentTarget.style.color = 'var(--bf-text-tertiary)'
        }}
        disabled={!canGoForward}
      >
        <ChevronRight size={18} />
      </button>
    </div>
  )
}

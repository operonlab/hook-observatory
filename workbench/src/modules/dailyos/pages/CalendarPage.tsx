import { ChevronLeft, ChevronRight, Circle, Repeat } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { planApi, recurringApi } from '../api'
import type { DailyPlan, PlanItem, RecurringItem } from '../types'
import { PLAN_STATUS_CONFIG } from '../types'

// ─── Helpers ───

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

function endOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0)
}

function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

/** Check if a recurring item matches a given date */
function recurringMatchesDate(item: RecurringItem, date: Date): boolean {
  if (!item.is_active) return false
  if (item.recurrence_type === 'daily') return true
  if (item.recurrence_type === 'weekly') {
    const jsDay = date.getDay()
    const isoDay = jsDay === 0 ? 6 : jsDay - 1
    return item.day_of_week === isoDay
  }
  if (item.recurrence_type === 'monthly') {
    return item.day_of_month === date.getDate()
  }
  return false
}

function itemDotColor(item: PlanItem): string {
  if (item.status === 'done') return 'var(--do-completed)'
  if (item.is_frog) return 'var(--do-frog)'
  return 'var(--do-text-muted)'
}

const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']

// ─── DayCell Sub-component ───

interface DayCellProps {
  date: Date
  inMonth: boolean
  isToday: boolean
  plan: DailyPlan | undefined
  dayRecurring: RecurringItem[]
  onNavigate: (path: string) => void
}

function PlanBadge({ plan }: { plan: DailyPlan }) {
  const statusCfg = PLAN_STATUS_CONFIG[plan.status]
  const doneCount = plan.items.filter((i) => i.status === 'done').length
  const totalItems = plan.items.length
  const pct = totalItems > 0 ? Math.round((doneCount / totalItems) * 100) : 0
  return (
    <div className="flex items-center gap-1">
      <Circle size={6} fill={statusCfg.color} stroke="none" />
      <span className="text-[10px] truncate" style={{ color: statusCfg.color }}>
        {doneCount}/{totalItems}
      </span>
      {pct === 100 && (
        <span className="text-[9px]" style={{ color: 'var(--do-completed)' }}>
          ✓
        </span>
      )}
    </div>
  )
}

function RecurringList({ items }: { items: RecurringItem[] }) {
  return (
    <>
      {items.slice(0, 3).map((r) => (
        <div key={r.id} className="flex items-center gap-1 truncate">
          <Repeat size={8} style={{ color: 'var(--do-accent-dim)', flexShrink: 0 }} />
          <span className="text-[10px] truncate" style={{ color: 'var(--do-text-tertiary)' }}>
            {r.start_time ? `${r.start_time} ` : ''}
            {r.title}
          </span>
        </div>
      ))}
      {items.length > 3 && (
        <span className="text-[9px]" style={{ color: 'var(--do-text-muted)' }}>
          +{items.length - 3} 項
        </span>
      )}
    </>
  )
}

function PlanItemsPreview({ items }: { items: PlanItem[] }) {
  return (
    <>
      {items.slice(0, 2).map((item) => (
        <div key={item.id} className="flex items-center gap-1 truncate">
          <span
            className="w-1 h-1 rounded-full flex-shrink-0"
            style={{ backgroundColor: itemDotColor(item) }}
          />
          <span
            className="text-[10px] truncate"
            style={{
              color: item.status === 'done' ? 'var(--do-text-muted)' : 'var(--do-text-tertiary)',
              textDecoration: item.status === 'done' ? 'line-through' : 'none',
            }}
          >
            {item.title}
          </span>
        </div>
      ))}
    </>
  )
}

function cellBgColor(isToday: boolean, hasContent: boolean, inMonth: boolean): string {
  if (isToday) return 'var(--do-accent-alpha)'
  if (hasContent && inMonth) return 'rgba(255,255,255,0.02)'
  return 'transparent'
}

function cellDateColor(isToday: boolean, inMonth: boolean): string {
  if (isToday) return 'var(--do-accent)'
  if (inMonth) return 'var(--do-text-secondary)'
  return 'var(--do-text-muted)'
}

function planCompletion(plan: DailyPlan) {
  const doneCount = plan.items.filter((i) => i.status === 'done').length
  const totalItems = plan.items.length
  const pct = totalItems > 0 ? Math.round((doneCount / totalItems) * 100) : 0
  return { doneCount, totalItems, pct, statusCfg: PLAN_STATUS_CONFIG[plan.status] }
}

function DayCell({ date, inMonth, isToday, plan, dayRecurring, onNavigate }: DayCellProps) {
  const hasContent = !!plan || dayRecurring.length > 0
  const completion = plan ? planCompletion(plan) : null

  return (
    <button
      type="button"
      onClick={() => inMonth && onNavigate(isToday ? '/dailyos' : '/dailyos/history')}
      className="relative flex flex-col p-1.5 md:p-2 min-h-[72px] md:min-h-[90px] border-b border-r transition-colors text-left"
      style={{
        borderColor: 'var(--do-border)',
        backgroundColor: cellBgColor(isToday, hasContent, inMonth),
        cursor: inMonth ? 'pointer' : 'default',
        opacity: inMonth ? 1 : 0.35,
      }}
    >
      <span
        className="text-[12px] md:text-[13px] leading-none font-medium"
        style={{ color: cellDateColor(isToday, inMonth) }}
      >
        {date.getDate()}
      </span>

      <div className="flex-1 mt-1 space-y-0.5 overflow-hidden">
        {plan && <PlanBadge plan={plan} />}
        {dayRecurring.length > 0 && <RecurringList items={dayRecurring} />}
        {plan && dayRecurring.length === 0 && <PlanItemsPreview items={plan.items} />}
      </div>

      {completion && completion.totalItems > 0 && (
        <div
          className="absolute bottom-0 left-0 h-[2px]"
          style={{
            width: `${completion.pct}%`,
            backgroundColor:
              completion.pct === 100 ? 'var(--do-completed)' : completion.statusCfg.color,
            transition: 'width 300ms ease',
          }}
        />
      )}
    </button>
  )
}

// ─── Main Component ───

export default function CalendarPage() {
  const navigate = useNavigate()
  const today = useMemo(() => new Date(), [])
  const [viewMonth, setViewMonth] = useState(
    () => new Date(today.getFullYear(), today.getMonth(), 1),
  )
  const [plans, setPlans] = useState<DailyPlan[]>([])
  const [recurring, setRecurring] = useState<RecurringItem[]>([])
  const [loading, setLoading] = useState(true)

  // ─── Fetch data for visible month ───
  const loadMonth = useCallback(async (month: Date) => {
    setLoading(true)
    try {
      const s = startOfMonth(month)
      const e = endOfMonth(month)
      const [planRes, recRes] = await Promise.all([
        planApi.list({ date_from: toDateStr(s), date_to: toDateStr(e), page: 1 }),
        recurringApi.list(),
      ])
      setPlans(planRes.items)
      setRecurring(recRes)
    } catch {
      // silently fail — calendar just shows empty
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadMonth(viewMonth)
  }, [loadMonth, viewMonth])

  // ─── Build calendar grid cells ───
  const cells = useMemo(() => {
    const first = startOfMonth(viewMonth)
    const last = endOfMonth(viewMonth)
    const jsFirstDay = first.getDay()
    const startOffset = jsFirstDay === 0 ? 6 : jsFirstDay - 1

    const result: Array<{ date: Date; inMonth: boolean }> = []

    for (let i = startOffset - 1; i >= 0; i--) {
      const d = new Date(first)
      d.setDate(d.getDate() - i - 1)
      result.push({ date: d, inMonth: false })
    }

    for (let d = 1; d <= last.getDate(); d++) {
      result.push({
        date: new Date(viewMonth.getFullYear(), viewMonth.getMonth(), d),
        inMonth: true,
      })
    }

    while (result.length % 7 !== 0) {
      const lastDate = result[result.length - 1].date
      const next = new Date(lastDate)
      next.setDate(next.getDate() + 1)
      result.push({ date: next, inMonth: false })
    }

    return result
  }, [viewMonth])

  // ─── Index plans by date string ───
  const plansByDate = useMemo(() => {
    const map = new Map<string, DailyPlan>()
    for (const p of plans) {
      map.set(p.plan_date, p)
    }
    return map
  }, [plans])

  // ─── Navigation ───
  const prevMonth = () => setViewMonth((m) => new Date(m.getFullYear(), m.getMonth() - 1, 1))
  const nextMonth = () => setViewMonth((m) => new Date(m.getFullYear(), m.getMonth() + 1, 1))
  const goToday = () => setViewMonth(new Date(today.getFullYear(), today.getMonth(), 1))

  const monthLabel = viewMonth.toLocaleDateString('zh-TW', { year: 'numeric', month: 'long' })
  const isCurrentMonth =
    viewMonth.getFullYear() === today.getFullYear() && viewMonth.getMonth() === today.getMonth()

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4 do-fade-in">
      {/* ─── Header ─── */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--do-text)' }}>
          日曆總覽
        </h1>
        <div className="flex items-center gap-2">
          {!isCurrentMonth && (
            <button
              type="button"
              onClick={goToday}
              className="px-2.5 py-1 rounded text-[11px]"
              style={{ color: 'var(--do-accent)', backgroundColor: 'var(--do-accent-alpha)' }}
            >
              今天
            </button>
          )}
          <button
            type="button"
            onClick={prevMonth}
            className="p-1.5 rounded hover:opacity-80 transition-opacity"
            style={{ color: 'var(--do-text-secondary)' }}
          >
            <ChevronLeft size={16} />
          </button>
          <span
            className="text-[13px] font-medium min-w-[100px] text-center tabular-nums"
            style={{ color: 'var(--do-text)' }}
          >
            {monthLabel}
          </span>
          <button
            type="button"
            onClick={nextMonth}
            className="p-1.5 rounded hover:opacity-80 transition-opacity"
            style={{ color: 'var(--do-text-secondary)' }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* ─── Calendar Grid ─── */}
      <div
        className="rounded-lg border overflow-hidden"
        style={{ borderColor: 'var(--do-border)', backgroundColor: 'var(--do-bg-elevated)' }}
      >
        {/* Weekday headers */}
        <div className="grid grid-cols-7">
          {WEEKDAY_LABELS.map((label, i) => (
            <div
              key={label}
              className="py-2 text-center text-[11px] font-medium"
              style={{
                color: i >= 5 ? 'var(--do-accent-dim)' : 'var(--do-text-muted)',
                borderBottom: '1px solid var(--do-border)',
              }}
            >
              {label}
            </div>
          ))}
        </div>

        {/* Day cells */}
        <div
          className="grid grid-cols-7"
          style={{ opacity: loading ? 0.5 : 1, transition: 'opacity 200ms' }}
        >
          {cells.map(({ date, inMonth }) => {
            const dateStr = toDateStr(date)
            return (
              <DayCell
                key={dateStr}
                date={date}
                inMonth={inMonth}
                isToday={isSameDay(date, today)}
                plan={plansByDate.get(dateStr)}
                dayRecurring={recurring.filter((r) => recurringMatchesDate(r, date))}
                onNavigate={navigate}
              />
            )
          })}
        </div>
      </div>

      {/* ─── Legend ─── */}
      <div
        className="flex flex-wrap items-center gap-4 text-[11px]"
        style={{ color: 'var(--do-text-muted)' }}
      >
        <div className="flex items-center gap-1.5">
          <Circle size={6} fill="var(--do-planning)" stroke="none" />
          <span>規劃中</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Circle size={6} fill="var(--do-active)" stroke="none" />
          <span>執行中</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Circle size={6} fill="var(--do-completed)" stroke="none" />
          <span>已完成</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Repeat size={10} style={{ color: 'var(--do-accent-dim)' }} />
          <span>固定行程</span>
        </div>
      </div>
    </div>
  )
}

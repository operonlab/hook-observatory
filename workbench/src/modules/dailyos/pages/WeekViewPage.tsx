import { ChevronLeft, ChevronRight, Circle, Repeat } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { planApi, recurringApi } from '../api'
import { useMethodStore } from '../stores/methodStore'
import type { DailyPlan, PlanItem, RecurringItem } from '../types'
import { PLAN_STATUS_CONFIG } from '../types'

function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function getMonday(d: Date): Date {
  const day = d.getDay()
  const diff = d.getDate() - (day === 0 ? 6 : day - 1)
  return new Date(d.getFullYear(), d.getMonth(), diff)
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

function recurringMatchesDate(item: RecurringItem, date: Date): boolean {
  if (!item.is_active) return false
  if (item.recurrence_type === 'daily') return true
  if (item.recurrence_type === 'weekly') {
    const jsDay = date.getDay()
    const isoDay = jsDay === 0 ? 6 : jsDay - 1
    return item.day_of_week === isoDay
  }
  if (item.recurrence_type === 'monthly') return item.day_of_month === date.getDate()
  return false
}

const WEEKDAY_LABELS = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']

function WeeklyReviewCard({ plans }: { plans: DailyPlan[] }) {
  const total = plans.reduce((s, p) => s + p.items.length, 0)
  const done = plans.reduce((s, p) => s + p.items.filter((i) => i.status === 'done').length, 0)
  const completedDays = plans.filter((p) => p.status === 'completed').length
  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  return (
    <div className="do-card p-4 space-y-3" style={{ borderLeft: '3px solid var(--do-accent)' }}>
      <h3 className="text-[13px] font-medium" style={{ color: 'var(--do-text)' }}>
        本週摘要
      </h3>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className="text-[18px] font-semibold" style={{ color: 'var(--do-accent)' }}>
            {done}/{total}
          </div>
          <div className="text-[10px]" style={{ color: 'var(--do-text-muted)' }}>
            完成項目
          </div>
        </div>
        <div>
          <div className="text-[18px] font-semibold" style={{ color: 'var(--do-completed)' }}>
            {completedDays}/7
          </div>
          <div className="text-[10px]" style={{ color: 'var(--do-text-muted)' }}>
            完成天數
          </div>
        </div>
        <div>
          <div
            className="text-[18px] font-semibold"
            style={{ color: pct >= 80 ? 'var(--do-completed)' : 'var(--do-text-secondary)' }}
          >
            {pct}%
          </div>
          <div className="text-[10px]" style={{ color: 'var(--do-text-muted)' }}>
            完成率
          </div>
        </div>
      </div>
    </div>
  )
}

interface DayColumnProps {
  date: Date
  isToday: boolean
  plan: DailyPlan | undefined
  dayRecurring: RecurringItem[]
  onNavigate: (path: string) => void
}

function DayColumn({ date, isToday, plan, dayRecurring, onNavigate }: DayColumnProps) {
  const hiddenGroupIds = useMethodStore((s) => s.hiddenGroupIds)
  const filterItem = (i: PlanItem) => !i.group_id || !hiddenGroupIds.has(i.group_id)
  const visiblePlanItems = plan ? plan.items.filter(filterItem) : []
  const visibleRecurring = dayRecurring.filter((r) => !r.group_id || !hiddenGroupIds.has(r.group_id))
  const statusCfg = plan ? PLAN_STATUS_CONFIG[plan.status] : null
  const doneCount = visiblePlanItems.filter((i) => i.status === 'done').length
  const totalItems = visiblePlanItems.length
  const pct = totalItems > 0 ? Math.round((doneCount / totalItems) * 100) : 0
  const ds = toDateStr(date)
  const todayStr = toDateStr(new Date())

  return (
    <button
      type="button"
      onClick={() => onNavigate(ds === todayStr ? '/dailyos' : `/dailyos?date=${ds}`)}
      className="flex flex-col border rounded-lg p-3 min-h-[200px] transition-colors text-left"
      style={{
        borderColor: isToday ? 'var(--do-accent-dim)' : 'var(--do-border)',
        backgroundColor: isToday ? 'var(--do-accent-alpha)' : 'var(--do-bg-elevated)',
        cursor: 'pointer',
        flex: '1 1 0',
        minWidth: 0,
      }}
    >
      {/* Day header */}
      <div className="flex items-center justify-between mb-2">
        <span
          className="text-[12px] font-medium"
          style={{ color: isToday ? 'var(--do-accent)' : 'var(--do-text-secondary)' }}
        >
          {date.getDate()}
        </span>
        {statusCfg && <Circle size={6} fill={statusCfg.color} stroke="none" />}
      </div>

      {/* Plan items */}
      <div className="flex-1 space-y-1 overflow-hidden">
        {visiblePlanItems.slice(0, 6).map((item) => (
          <div key={item.id} className="flex items-center gap-1 truncate">
            <span
              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{
                backgroundColor:
                  item.status === 'done'
                    ? 'var(--do-completed)'
                    : item.is_frog
                      ? 'var(--do-frog)'
                      : 'var(--do-text-muted)',
              }}
            />
            <span
              className="text-[11px] truncate"
              style={{
                color: item.status === 'done' ? 'var(--do-text-muted)' : 'var(--do-text-tertiary)',
                textDecoration: item.status === 'done' ? 'line-through' : 'none',
              }}
            >
              {item.title}
            </span>
          </div>
        ))}
        {visiblePlanItems.length > 6 && (
          <span className="text-[9px]" style={{ color: 'var(--do-text-muted)' }}>
            +{visiblePlanItems.length - 6} 項
          </span>
        )}

        {/* Recurring */}
        {visibleRecurring.slice(0, 3).map((r) => (
          <div key={r.id} className="flex items-center gap-1 truncate">
            <Repeat size={8} style={{ color: 'var(--do-accent-dim)', flexShrink: 0 }} />
            <span className="text-[10px] truncate" style={{ color: 'var(--do-text-tertiary)' }}>
              {r.start_time ? `${r.start_time} ` : ''}
              {r.title}
            </span>
          </div>
        ))}
      </div>

      {/* Bottom progress */}
      {totalItems > 0 && (
        <div className="mt-2">
          <div
            className="h-1 rounded-full overflow-hidden"
            style={{ backgroundColor: 'var(--do-bg-surface)' }}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${pct}%`,
                backgroundColor:
                  pct === 100
                    ? 'var(--do-completed)'
                    : (statusCfg?.color ?? 'var(--do-text-muted)'),
              }}
            />
          </div>
          <span className="text-[9px] mt-0.5 block" style={{ color: 'var(--do-text-muted)' }}>
            {doneCount}/{totalItems}
          </span>
        </div>
      )}
    </button>
  )
}

export default function WeekViewPage() {
  const navigate = useNavigate()
  const today = useMemo(() => new Date(), [])
  const [weekStart, setWeekStart] = useState(() => getMonday(today))
  const [plans, setPlans] = useState<DailyPlan[]>([])
  const [recurring, setRecurring] = useState<RecurringItem[]>([])
  const [loading, setLoading] = useState(true)

  const weekEnd = useMemo(() => addDays(weekStart, 6), [weekStart])

  const loadWeek = useCallback(async (start: Date) => {
    setLoading(true)
    try {
      const end = addDays(start, 6)
      const [planRes, recRes] = await Promise.all([
        planApi.list({ date_from: toDateStr(start), date_to: toDateStr(end) }),
        recurringApi.list(),
      ])
      setPlans(planRes.items)
      setRecurring(recRes)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadWeek(weekStart)
  }, [loadWeek, weekStart])

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  )

  const plansByDate = useMemo(() => {
    const m = new Map<string, DailyPlan>()
    for (const p of plans) m.set(p.plan_date, p)
    return m
  }, [plans])

  const prevWeek = () => setWeekStart((s) => addDays(s, -7))
  const nextWeek = () => setWeekStart((s) => addDays(s, 7))
  const goThisWeek = () => setWeekStart(getMonday(today))
  const isCurrentWeek = isSameDay(weekStart, getMonday(today))

  const weekLabel = `${weekStart.getMonth() + 1}/${weekStart.getDate()} — ${weekEnd.getMonth() + 1}/${weekEnd.getDate()}`

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4 do-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--do-text)' }}>
          週視圖
        </h1>
        <div className="flex items-center gap-2">
          {!isCurrentWeek && (
            <button
              type="button"
              onClick={goThisWeek}
              className="px-2.5 py-1 rounded text-[11px]"
              style={{ color: 'var(--do-accent)', backgroundColor: 'var(--do-accent-alpha)' }}
            >
              本週
            </button>
          )}
          <button
            type="button"
            onClick={prevWeek}
            className="p-1.5 rounded hover:opacity-80 transition-opacity"
            style={{ color: 'var(--do-text-secondary)' }}
          >
            <ChevronLeft size={16} />
          </button>
          <span
            className="text-[13px] font-medium min-w-[100px] text-center tabular-nums"
            style={{ color: 'var(--do-text)' }}
          >
            {weekLabel}
          </span>
          <button
            type="button"
            onClick={nextWeek}
            className="p-1.5 rounded hover:opacity-80 transition-opacity"
            style={{ color: 'var(--do-text-secondary)' }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* Weekday labels */}
      <div
        className="grid grid-cols-7 gap-2"
        style={{ opacity: loading ? 0.5 : 1, transition: 'opacity 200ms' }}
      >
        {days.map((d, i) => (
          <div key={toDateStr(d)} className="text-center">
            <span
              className="text-[11px] font-medium"
              style={{ color: isSameDay(d, today) ? 'var(--do-accent)' : 'var(--do-text-muted)' }}
            >
              {WEEKDAY_LABELS[i]}
            </span>
          </div>
        ))}
      </div>

      {/* Day columns */}
      <div className="grid grid-cols-7 gap-2">
        {days.map((d) => {
          const ds = toDateStr(d)
          return (
            <DayColumn
              key={ds}
              date={d}
              isToday={isSameDay(d, today)}
              plan={plansByDate.get(ds)}
              dayRecurring={recurring.filter((r) => recurringMatchesDate(r, d))}
              onNavigate={navigate}
            />
          )
        })}
      </div>

      {/* Weekly review card */}
      <WeeklyReviewCard plans={plans} />
    </div>
  )
}

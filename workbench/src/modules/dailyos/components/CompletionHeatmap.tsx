import { useEffect, useMemo, useState } from 'react'
import { planApi } from '../api'
import type { DailyPlanStats } from '../types'

function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function heatColor(score: number): string {
  if (score <= 0) return 'var(--do-bg-surface)'
  if (score < 0.25) return 'rgba(166, 227, 161, 0.15)'
  if (score < 0.5) return 'rgba(166, 227, 161, 0.3)'
  if (score < 0.75) return 'rgba(166, 227, 161, 0.5)'
  if (score < 1) return 'rgba(166, 227, 161, 0.7)'
  return 'var(--do-completed)'
}

interface CompletionHeatmapProps {
  year: number
  month: number // 0-indexed
}

export function CompletionHeatmap({ year, month }: CompletionHeatmapProps) {
  const [stats, setStats] = useState<DailyPlanStats[]>([])

  const dateRange = useMemo(() => {
    const start = new Date(year, month, 1)
    const end = new Date(year, month + 1, 0)
    return { from: toDateStr(start), to: toDateStr(end) }
  }, [year, month])

  useEffect(() => {
    planApi
      .stats(dateRange.from, dateRange.to)
      .then(setStats)
      .catch(() => {})
  }, [dateRange.from, dateRange.to])

  const statsByDate = useMemo(() => {
    const m = new Map<string, DailyPlanStats>()
    for (const s of stats) m.set(s.plan_date, s)
    return m
  }, [stats])

  const daysInMonth = new Date(year, month + 1, 0).getDate()

  return (
    <div className="do-card p-4 space-y-2">
      <h3 className="text-[12px] font-medium" style={{ color: 'var(--do-text-secondary)' }}>
        完成度熱力圖
      </h3>
      <div className="flex flex-wrap gap-1">
        {Array.from({ length: daysInMonth }, (_, i) => {
          const ds = toDateStr(new Date(year, month, i + 1))
          const stat = statsByDate.get(ds)
          const score = stat?.completion_score ?? 0
          return (
            <div
              key={ds}
              title={`${i + 1}日: ${stat ? `${Math.round(score * 100)}%` : '無資料'}`}
              style={{
                width: 14,
                height: 14,
                borderRadius: 2,
                backgroundColor: stat ? heatColor(score) : 'var(--do-bg-surface)',
              }}
            />
          )
        })}
      </div>
      <div
        className="flex items-center gap-1 text-[10px]"
        style={{ color: 'var(--do-text-muted)' }}
      >
        <span>少</span>
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <div
            key={v}
            style={{
              width: 10,
              height: 10,
              borderRadius: 2,
              backgroundColor: heatColor(v),
            }}
          />
        ))}
        <span>多</span>
      </div>
    </div>
  )
}

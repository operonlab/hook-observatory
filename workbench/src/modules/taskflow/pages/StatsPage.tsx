import { Suspense, lazy, useEffect, useState } from 'react'
import { dashboardApi } from '../api'
import type { TaskProgressStats } from '../types'

const StatsCharts = lazy(() => import('../components/StatsCharts'))

// ─── Stat card ───

function SummaryCard({
  label,
  value,
  sub,
}: {
  label: string
  value: string | number
  sub?: string
}) {
  return (
    <div
      className="rounded-lg border p-3"
      style={{ borderColor: 'var(--tf-border)', backgroundColor: 'var(--tf-bg-elevated)' }}
    >
      <div className="text-[11px] mb-1" style={{ color: 'var(--tf-text-muted)' }}>
        {label}
      </div>
      <div className="text-xl font-semibold tabular-nums" style={{ color: 'var(--tf-text)' }}>
        {value}
      </div>
      {sub && (
        <div className="text-[11px] mt-0.5" style={{ color: 'var(--tf-text-muted)' }}>
          {sub}
        </div>
      )}
    </div>
  )
}

export default function StatsPage() {
  const [stats, setStats] = useState<TaskProgressStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    dashboardApi
      .progress()
      .then(setStats)
      .catch(() => setStats(null))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--tf-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="p-6 text-center" style={{ color: 'var(--tf-text-muted)' }}>
        無法載入統計資料
      </div>
    )
  }

  const completionRate =
    stats.total > 0 ? Math.round((stats.by_status.done / stats.total) * 100) : 0

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <h1 className="text-base font-medium" style={{ color: 'var(--tf-text)' }}>
        任務統計
      </h1>

      {/* Summary row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SummaryCard label="總任務數" value={stats.total} />
        <SummaryCard label="完成率" value={`${completionRate}%`} />
        <SummaryCard label="逾期" value={stats.overdue} sub={stats.overdue > 0 ? '需要注意' : ''} />
        <SummaryCard
          label="工時差"
          value={`${Math.abs(Math.round((stats.actual_hours - stats.estimated_hours) * 10) / 10)}h`}
          sub={stats.actual_hours > stats.estimated_hours ? '超出預估' : '低於預估'}
        />
      </div>

      {/* Charts grid */}
      <Suspense
        fallback={
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="animate-pulse h-64 bg-white/5 rounded-lg" />
            ))}
          </div>
        }
      >
        <StatsCharts stats={stats} />
      </Suspense>
    </div>
  )
}

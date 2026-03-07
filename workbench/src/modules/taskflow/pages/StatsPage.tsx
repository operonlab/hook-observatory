import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { dashboardApi } from '../api'
import type { TaskPriority, TaskProgressStats, TaskSource, TaskStatus } from '../types'
import { PRIORITY_CONFIG, SOURCE_CONFIG, STATUS_CONFIG } from '../types'

// ─── Chart tooltip ───

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ name: string; value: number; payload: { color?: string } }>
}) {
  if (!active || !payload?.length) return null
  const entry = payload[0]
  return (
    <div
      className="rounded-md border px-3 py-2 text-[12px] shadow-lg"
      style={{ backgroundColor: 'var(--tf-bg-surface)', borderColor: 'var(--tf-border)' }}
    >
      <span style={{ color: entry.payload.color ?? 'var(--tf-text)' }}>
        {entry.name}: {entry.value}
      </span>
    </div>
  )
}

// ─── Card wrapper ───

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-lg border p-4"
      style={{ borderColor: 'var(--tf-border)', backgroundColor: 'var(--tf-bg-elevated)' }}
    >
      <h3 className="text-[13px] font-medium mb-4" style={{ color: 'var(--tf-text)' }}>
        {title}
      </h3>
      {children}
    </div>
  )
}

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

  // Build chart data
  const statusData = (Object.entries(stats.by_status) as [TaskStatus, number][])
    .filter(([, v]) => v > 0)
    .map(([k, v]) => ({
      name: STATUS_CONFIG[k].label,
      value: v,
      color: STATUS_CONFIG[k].color,
    }))

  const sourceData = (Object.entries(stats.by_source) as [TaskSource, number][])
    .filter(([, v]) => v > 0)
    .map(([k, v]) => ({
      name: `${SOURCE_CONFIG[k].icon} ${SOURCE_CONFIG[k].label}`,
      value: v,
      color: k === 'personal' ? '#cba6f7' : k === 'family' ? '#f9e2af' : '#89b4fa',
    }))

  const priorityData = (Object.entries(stats.by_priority) as [TaskPriority, number][]).map(
    ([k, v]) => ({
      name: PRIORITY_CONFIG[k].label,
      value: v,
      color: PRIORITY_CONFIG[k].color,
    }),
  )

  const hoursData = [
    {
      name: '預估',
      value: Math.round(stats.estimated_hours * 10) / 10,
      color: 'var(--tf-chart-1)',
    },
    { name: '實際', value: Math.round(stats.actual_hours * 10) / 10, color: 'var(--tf-chart-2)' },
  ]

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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Status pie */}
        <ChartCard title="狀態分佈">
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={statusData}
                cx="50%"
                cy="50%"
                outerRadius={80}
                dataKey="value"
                nameKey="name"
                label={({ name, percent }) => `${name} ${Math.round((percent ?? 0) * 100)}%`}
                labelLine={false}
              >
                {statusData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip content={<ChartTooltip />} />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Source pie */}
        <ChartCard title="來源分佈">
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={sourceData}
                cx="50%"
                cy="50%"
                outerRadius={80}
                dataKey="value"
                nameKey="name"
              >
                {sourceData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip content={<ChartTooltip />} />
              <Legend
                formatter={(value) => (
                  <span style={{ color: 'var(--tf-text-secondary)', fontSize: 12 }}>{value}</span>
                )}
              />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Priority bar */}
        <ChartCard title="優先級分佈">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={priorityData} margin={{ top: 0, right: 8, left: -20, bottom: 0 }}>
              <XAxis
                dataKey="name"
                tick={{ fill: 'var(--tf-text-tertiary)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: 'var(--tf-text-tertiary)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(255,255,255,0.05)' }} />
              <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                {priorityData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Hours bar */}
        <ChartCard title="工時對比（小時）">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={hoursData} margin={{ top: 0, right: 8, left: -20, bottom: 0 }}>
              <XAxis
                dataKey="name"
                tick={{ fill: 'var(--tf-text-tertiary)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: 'var(--tf-text-tertiary)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(255,255,255,0.05)' }} />
              <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                {hoursData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  )
}

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

interface StatsChartsProps {
  stats: TaskProgressStats
}

export default function StatsCharts({ stats }: StatsChartsProps) {
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

  return (
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
  )
}

import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchTierStats, type TierStat, type TierStatsResponse } from '../api'

type ChartMode = 'pie' | 'bar'

const TIER_COLORS: Record<string, string> = {
  headless: 'var(--blue)',
  relay: 'var(--green)',
  fleet: 'var(--peach)',
}

const TIER_LABELS: Record<string, string> = {
  headless: 'Headless',
  relay: 'Relay',
  fleet: 'Fleet',
}

function getTierColor(tier: string): string {
  return TIER_COLORS[tier] ?? 'var(--overlay0)'
}

function getTierLabel(tier: string): string {
  return TIER_LABELS[tier] ?? tier
}

const TOOLTIP_STYLE = {
  backgroundColor: '#242438',
  border: '1px solid #383854',
  borderRadius: 8,
  fontSize: 12,
  color: '#cdd6f4',
}

const DAYS_OPTIONS = [7, 14, 30, 90]

export default function TierDistributionChart() {
  const [mode, setMode] = useState<ChartMode>('pie')
  const [days, setDays] = useState(30)
  const [data, setData] = useState<TierStatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    fetchTierStats(days)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [days])

  return (
    <div
      className="rounded-xl border p-5"
      style={{
        backgroundColor: 'var(--mantle)',
        borderColor: 'var(--surface0)',
      }}
    >
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold" style={{ color: 'var(--text)' }}>
          Maestro Tier 分佈
        </h2>
        <div className="flex items-center gap-2">
          {/* Days selector */}
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-lg border px-2 py-1 text-xs outline-none"
            style={{
              backgroundColor: 'var(--base)',
              borderColor: 'var(--surface0)',
              color: 'var(--text)',
              minHeight: 32,
            }}
          >
            {DAYS_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {d} 天
              </option>
            ))}
          </select>

          {/* Chart mode toggle */}
          <div
            className="flex gap-0.5 rounded-lg p-0.5"
            style={{ backgroundColor: 'var(--surface0)' }}
          >
            {(['pie', 'bar'] as const).map((m) => (
              <button
                type="button"
                key={m}
                onClick={() => setMode(m)}
                className="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
                style={{
                  backgroundColor: mode === m ? 'var(--mantle)' : 'transparent',
                  color: mode === m ? 'var(--text)' : 'var(--subtext0)',
                  minHeight: 28,
                }}
              >
                {m === 'pie' ? '圓餅圖' : '長條圖'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div
          className="flex items-center justify-center py-16 text-sm"
          style={{ color: 'var(--subtext0)' }}
        >
          載入中...
        </div>
      ) : error ? (
        <div className="rounded-lg px-3 py-8 text-center text-sm" style={{ color: 'var(--red)' }}>
          {error}
        </div>
      ) : !data || data.stats.length === 0 ? (
        <div
          className="flex items-center justify-center py-16 text-sm"
          style={{ color: 'var(--subtext0)' }}
        >
          無調度資料
        </div>
      ) : (
        <>
          {/* Summary */}
          <div className="mb-4 text-center text-xs" style={{ color: 'var(--subtext0)' }}>
            過去 {data.days} 天共 {data.total} 次調度
          </div>

          {/* Chart */}
          {mode === 'pie' ? (
            <TierPieChart stats={data.stats} />
          ) : (
            <TierBarChart stats={data.stats} />
          )}

          {/* Legend */}
          <div className="mt-4 flex flex-wrap justify-center gap-x-6 gap-y-2">
            {data.stats.map((s) => (
              <div key={s.tier} className="flex items-center gap-2 text-xs">
                <div
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: getTierColor(s.tier) }}
                />
                <span style={{ color: 'var(--text)' }}>{getTierLabel(s.tier)}</span>
                <span className="tabular-nums" style={{ color: 'var(--subtext0)' }}>
                  {s.count} ({s.pct.toFixed(1)}%)
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// --- Sub-charts ---

function TierPieChart({ stats }: { stats: TierStat[] }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie
          data={stats}
          dataKey="count"
          nameKey="tier"
          cx="50%"
          cy="50%"
          innerRadius={55}
          outerRadius={90}
          paddingAngle={2}
          stroke="none"
        >
          {stats.map((s) => (
            <Cell key={s.tier} fill={getTierColor(s.tier)} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value: number, name: string) => [
            `${value} 次 (${stats.find((s) => s.tier === name)?.pct.toFixed(1)}%)`,
            getTierLabel(name),
          ]}
        />
      </PieChart>
    </ResponsiveContainer>
  )
}

function TierBarChart({ stats }: { stats: TierStat[] }) {
  const chartData = stats.map((s) => ({
    ...s,
    label: getTierLabel(s.tier),
  }))

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={chartData} barCategoryGap="30%">
        <CartesianGrid strokeDasharray="3 3" stroke="#383854" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 12, fill: '#7f849c' }}
          axisLine={{ stroke: '#383854' }}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 11, fill: '#7f849c' }}
          axisLine={false}
          tickLine={false}
          allowDecimals={false}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value: number, name: string) => {
            if (name === 'count') return [`${value} 次`, '次數']
            if (name === 'avg_duration') return [`${value.toFixed(1)}s`, '平均耗時']
            return [value, name]
          }}
          labelFormatter={(label) => `${label}`}
        />
        <Bar dataKey="count" name="count" radius={[4, 4, 0, 0]}>
          {chartData.map((d) => (
            <Cell key={d.tier} fill={getTierColor(d.tier)} />
          ))}
        </Bar>
        <Bar dataKey="avg_duration" name="avg_duration" radius={[4, 4, 0, 0]} opacity={0.5}>
          {chartData.map((d) => (
            <Cell key={d.tier} fill={getTierColor(d.tier)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

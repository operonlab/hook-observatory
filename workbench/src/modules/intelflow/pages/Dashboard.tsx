import { FileText, Search, Tags, TrendingUp } from 'lucide-react'
import StatCard from '../components/StatCard'
import { useDashboard, useTimeline, useTopics } from '../hooks/useIntelflow'
import type { TimelineEntry, Topic } from '../types'

/* ─── SVG Line Chart ─── */

function TimelineChart({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-xs" style={{ color: 'var(--if-text-dim)' }}>
          尚無資料
        </span>
      </div>
    )
  }

  const maxCount = Math.max(...entries.map((e) => e.count), 1)
  const padding = { top: 20, right: 16, bottom: 40, left: 36 }
  const width = 600
  const height = 220
  const chartW = width - padding.left - padding.right
  const chartH = height - padding.top - padding.bottom

  const points = entries.map((entry, i) => ({
    x: padding.left + (i / Math.max(entries.length - 1, 1)) * chartW,
    y: padding.top + chartH - (entry.count / maxCount) * chartH,
    date: entry.date,
    count: entry.count,
  }))

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
  const areaPath = `${linePath} L ${points[points.length - 1].x} ${padding.top + chartH} L ${points[0].x} ${padding.top + chartH} Z`

  // Y-axis ticks
  const yTicks = [0, Math.round(maxCount / 2), maxCount]

  // X-axis labels (show every ~7th)
  const step = Math.max(1, Math.floor(entries.length / 5))
  const xLabels = entries.filter((_, i) => i % step === 0 || i === entries.length - 1)

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-full">
      {/* Grid lines */}
      {yTicks.map((tick) => {
        const y = padding.top + chartH - (tick / maxCount) * chartH
        return (
          <g key={tick}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={y}
              y2={y}
              stroke="var(--if-border)"
              strokeDasharray="3 3"
            />
            <text
              x={padding.left - 6}
              y={y + 4}
              textAnchor="end"
              fill="var(--if-text-dim)"
              fontSize={10}
            >
              {tick}
            </text>
          </g>
        )
      })}

      {/* Area fill */}
      <path d={areaPath} fill="var(--if-accent)" opacity={0.08} />

      {/* Line */}
      <path d={linePath} fill="none" stroke="var(--if-accent)" strokeWidth={2} />

      {/* Dots */}
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3} fill="var(--if-accent)" />
      ))}

      {/* X-axis labels */}
      {xLabels.map((entry) => {
        const idx = entries.indexOf(entry)
        const x = padding.left + (idx / Math.max(entries.length - 1, 1)) * chartW
        const dateStr = entry.date.slice(5) // MM-DD
        return (
          <text
            key={entry.date}
            x={x}
            y={height - 8}
            textAnchor="middle"
            fill="var(--if-text-dim)"
            fontSize={10}
          >
            {dateStr}
          </text>
        )
      })}
    </svg>
  )
}

/* ─── Horizontal Bar Chart ─── */

function TopicBarChart({ topics }: { topics: Topic[] }) {
  const sorted = [...topics].sort((a, b) => b.report_count - a.report_count).slice(0, 8)

  if (sorted.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-xs" style={{ color: 'var(--if-text-dim)' }}>
          尚無主題
        </span>
      </div>
    )
  }

  const maxCount = Math.max(...sorted.map((t) => t.report_count), 1)

  return (
    <div className="space-y-2.5 sm:space-y-3">
      {sorted.map((topic) => {
        const pct = (topic.report_count / maxCount) * 100
        return (
          <div key={topic.id} className="flex items-center gap-2 sm:gap-3">
            <span
              className="shrink-0 w-20 sm:w-24 text-right text-xs truncate"
              style={{ color: 'var(--if-text-secondary)' }}
            >
              {topic.display_name || topic.name}
            </span>
            <div
              className="flex-1 h-5 relative"
              style={{ backgroundColor: 'var(--if-bg-surface)' }}
            >
              <div
                className="h-full transition-all duration-500"
                style={{
                  width: `${pct}%`,
                  backgroundColor: 'var(--if-accent)',
                  opacity: 0.7,
                }}
              />
            </div>
            <span
              className="shrink-0 w-7 sm:w-8 text-right text-xs tabular-nums"
              style={{ color: 'var(--if-text-tertiary)' }}
            >
              {topic.report_count}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/* ─── Dashboard ─── */

export default function Dashboard() {
  const { dashboard, loading } = useDashboard()
  const { timeline } = useTimeline(30)
  const { topics } = useTopics()

  if (loading && !dashboard) {
    return (
      <div className="flex items-center justify-center h-64">
        <div
          className="h-6 w-6 animate-spin border-2 border-t-transparent"
          style={{ borderColor: 'var(--if-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  const today = new Date().toLocaleDateString('zh-TW', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })

  // Calculate "this month" count from timeline
  const now = new Date()
  const thisMonthPrefix = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  const thisMonthCount = timeline
    .filter((e) => e.date.startsWith(thisMonthPrefix))
    .reduce((sum, e) => sum + e.count, 0)

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-6 sm:space-y-8">
      {/* Header */}
      <div>
        <h1
          className="text-2xl sm:text-3xl font-light"
          style={{ fontFamily: 'var(--if-font-display)', color: 'var(--if-text)' }}
        >
          儀表板
        </h1>
        <p className="text-sm mt-1" style={{ color: 'var(--if-text-dim)' }}>
          {today}
        </p>
      </div>

      {/* Stats row — 2x2 on mobile, 4 cols on xl */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 sm:gap-4">
        <StatCard icon={FileText} label="研究報告" value={dashboard?.total_reports ?? 0} accent />
        <StatCard icon={Tags} label="研究主題" value={dashboard?.total_topics ?? 0} />
        <StatCard icon={Search} label="搜尋次數" value={dashboard?.total_briefings ?? 0} />
        <StatCard icon={TrendingUp} label="本月新增" value={thisMonthCount} />
      </div>

      {/* Charts row — stacked on mobile, side-by-side on xl */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 sm:gap-6">
        {/* Timeline chart */}
        <div
          className="border p-4 sm:p-5"
          style={{
            backgroundColor: 'var(--if-bg-elevated)',
            borderColor: 'var(--if-border)',
          }}
        >
          <h3
            className="text-sm font-medium mb-3 sm:mb-4"
            style={{ color: 'var(--if-text-secondary)' }}
          >
            近 30 天報告趨勢
          </h3>
          <div style={{ height: 200 }} className="sm:h-60">
            <TimelineChart entries={timeline} />
          </div>
        </div>

        {/* Hot topics chart */}
        <div
          className="border p-4 sm:p-5"
          style={{
            backgroundColor: 'var(--if-bg-elevated)',
            borderColor: 'var(--if-border)',
          }}
        >
          <h3
            className="text-sm font-medium mb-3 sm:mb-4"
            style={{ color: 'var(--if-text-secondary)' }}
          >
            熱門主題
          </h3>
          <div style={{ minHeight: 160 }}>
            <TopicBarChart topics={topics} />
          </div>
        </div>
      </div>

      {/* Recent reports */}
      {dashboard?.recent_reports && dashboard.recent_reports.length > 0 && (
        <div>
          <h2
            className="text-base sm:text-lg font-light mb-3 sm:mb-4"
            style={{ fontFamily: 'var(--if-font-display)', color: 'var(--if-text)' }}
          >
            最近報告
          </h2>
          <div
            className="border divide-y"
            style={{
              backgroundColor: 'var(--if-bg-elevated)',
              borderColor: 'var(--if-border)',
            }}
          >
            {dashboard.recent_reports.map((report) => (
              <div
                key={report.id}
                className="flex items-start sm:items-center justify-between px-4 sm:px-5 py-3.5 gap-3"
                style={{ borderColor: 'var(--if-border)' }}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm leading-snug" style={{ color: 'var(--if-text)' }}>
                    {report.title}
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--if-text-dim)' }}>
                    {new Date(report.created_at).toLocaleDateString('zh-TW')}
                    {report.tags.length > 0 && ` · ${report.tags.slice(0, 3).join(', ')}`}
                  </p>
                </div>
                {report.skill_name && (
                  <span
                    className="shrink-0 text-[10px] px-2 py-0.5 border self-start sm:self-auto"
                    style={{
                      borderColor: 'var(--if-border)',
                      color: 'var(--if-text-dim)',
                    }}
                  >
                    {report.skill_name}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { statsApi } from '../api'
import type { DemandStats, GlobalStats, TimeSavedStats } from '../types'

export default function StatsPage() {
  const [global, setGlobal] = useState<GlobalStats | null>(null)
  const [demand, setDemand] = useState<DemandStats | null>(null)
  const [timeSaved, setTimeSaved] = useState<TimeSavedStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([statsApi.global(), statsApi.demand({ limit: 30 }), statsApi.timeSaved('90d')])
      .then(([g, d, t]) => {
        setGlobal(g)
        setDemand(d)
        setTimeSaved(t)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading)
    return (
      <div className="p-6" style={{ color: 'var(--av-text-muted)' }}>
        載入中...
      </div>
    )
  if (error)
    return (
      <div className="p-6" style={{ color: 'var(--av-fail)' }}>
        錯誤: {error}
      </div>
    )

  const maxTrend = Math.max(...(global?.trend_7d.map((d) => d.count) ?? [1]), 1)

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-semibold" style={{ color: 'var(--av-text)' }}>
        使用統計
      </h1>

      {/* ── Summary Cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="總呼叫次數"
          value={global?.total_invocations ?? 0}
          color="var(--av-info)"
        />
        <StatCard label="活躍技能數" value={global?.total_skills ?? 0} color="var(--av-accent)" />
        <StatCard
          label="成功率"
          value={`${(global?.avg_success_rate ?? 0).toFixed(1)}%`}
          color="var(--av-pass)"
        />
        <StatCard
          label="自動觸發率"
          value={`${(demand?.overall_auto_rate ?? 0).toFixed(1)}%`}
          color="var(--av-warn)"
        />
      </div>

      {/* ── 7-Day Trend ── */}
      {global && global.trend_7d.length > 0 && (
        <Card title="7 天呼叫趨勢">
          <div className="flex items-end gap-2" style={{ height: 120 }}>
            {global.trend_7d.map((d) => {
              const barH = Math.round((d.count / maxTrend) * 80)
              return (
                <div key={d.day} className="flex-1 flex flex-col items-center justify-end h-full">
                  <span className="text-[10px] mb-1" style={{ color: 'var(--av-text-muted)' }}>
                    {d.count}
                  </span>
                  <div
                    className="w-full rounded-t-sm"
                    style={{
                      height: barH > 0 ? barH : 0,
                      minHeight: d.count > 0 ? 4 : 0,
                      backgroundColor: 'var(--av-info)',
                      opacity: 0.7,
                    }}
                    title={`${d.day}: ${d.count} 次`}
                  />
                  <span className="text-[10px] mt-1" style={{ color: 'var(--av-text-muted)' }}>
                    {d.day.slice(5)}
                  </span>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* ── Demand: User vs Auto ── */}
      {demand && demand.items.length > 0 && (
        <Card
          title="主動呼叫 vs 自動觸發"
          subtitle={`整體自動率 ${demand.overall_auto_rate.toFixed(1)}% — 使用者 ${demand.total_user} / 自動 ${demand.total_auto}`}
        >
          <div className="flex gap-4 mb-3 text-[11px]">
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block w-2.5 h-2.5 rounded-sm"
                style={{ backgroundColor: 'var(--av-accent)' }}
              />
              <span style={{ color: 'var(--av-text-muted)' }}>主動呼叫 (intent)</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block w-2.5 h-2.5 rounded-sm"
                style={{ backgroundColor: 'var(--av-info)' }}
              />
              <span style={{ color: 'var(--av-text-muted)' }}>自動觸發 (invocation)</span>
            </span>
          </div>
          <div className="space-y-2.5">
            {demand.items.map((item) => (
              <DemandRow key={item.skill_name} item={item} maxTotal={demand.items[0].total_usage} />
            ))}
          </div>
        </Card>
      )}

      {/* ── Top Skills ── */}
      {global && global.top_skills.length > 0 && (
        <Card
          title="Top 10 技能"
          titleRight={
            <InfoButton text="依實際執行次數排名（PostToolUse hook 記錄）。包含所有類別（skill、command、test）。成功率 = 該技能成功執行的比例。進度條顏色：綠 ≥90%、黃 ≥70%、紅 <70%。" />
          }
        >
          <div className="space-y-2">
            {global.top_skills.map((s, i) => (
              <div key={s.skill_name} className="flex items-center gap-3 text-sm">
                <span
                  className="shrink-0 w-5 text-right text-xs"
                  style={{ color: 'var(--av-text-muted)' }}
                >
                  {i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className="font-mono text-xs truncate"
                      style={{ color: 'var(--av-text)' }}
                    >
                      {s.skill_name}
                    </span>
                    <span className="text-xs shrink-0" style={{ color: 'var(--av-text-muted)' }}>
                      {s.count} 次
                    </span>
                  </div>
                  <div
                    className="mt-1 h-1.5 rounded-full overflow-hidden"
                    style={{ backgroundColor: 'var(--av-border)' }}
                  >
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${(s.count / global.top_skills[0].count) * 100}%`,
                        backgroundColor:
                          s.success_rate >= 90
                            ? 'var(--av-pass)'
                            : s.success_rate >= 70
                              ? 'var(--av-warn)'
                              : 'var(--av-fail)',
                      }}
                    />
                  </div>
                </div>
                <span
                  className="shrink-0 text-xs"
                  style={{
                    color:
                      s.success_rate >= 90
                        ? 'var(--av-pass)'
                        : s.success_rate >= 70
                          ? 'var(--av-warn)'
                          : 'var(--av-fail)',
                  }}
                >
                  {s.success_rate.toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ── Time Saved Breakdown (only show with enough data) ── */}
      {timeSaved &&
        timeSaved.tasks_with_estimates >= 3 &&
        timeSaved.monthly_breakdown.length > 0 && (
          <Card
            title="時間節省 ROI"
            subtitle={`${timeSaved.tasks_with_estimates} 筆任務有估算 — 平均每筆省 ${timeSaved.avg_saved_per_task.toFixed(1)} min`}
          >
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {timeSaved.monthly_breakdown.map((m) => (
                <div
                  key={m.month}
                  className="rounded-md border p-3"
                  style={{
                    borderColor: 'var(--av-border)',
                    backgroundColor: 'var(--av-bg-surface)',
                  }}
                >
                  <div className="text-xs mb-1" style={{ color: 'var(--av-text-muted)' }}>
                    {m.month}
                  </div>
                  <div className="text-lg font-semibold" style={{ color: 'var(--av-warn)' }}>
                    {Math.round(m.total_saved_minutes)} min
                  </div>
                  <div className="text-[10px]" style={{ color: 'var(--av-text-muted)' }}>
                    {m.tasks_count} 筆任務
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}
    </div>
  )
}

// ── Shared Components ──

function StatCard({
  label,
  value,
  color,
}: {
  label: string
  value: string | number
  color: string
}) {
  return (
    <div
      className="rounded-lg border p-4"
      style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
    >
      <div className="text-xs mb-1" style={{ color: 'var(--av-text-muted)' }}>
        {label}
      </div>
      <div className="text-2xl font-semibold" style={{ color }}>
        {value}
      </div>
    </div>
  )
}

function Card({
  title,
  subtitle,
  titleRight,
  children,
}: {
  title: string
  subtitle?: string
  titleRight?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div
      className="rounded-lg border p-5"
      style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
    >
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-sm font-medium" style={{ color: 'var(--av-text)' }}>
          {title}
        </h2>
        {titleRight}
      </div>
      {subtitle && (
        <p className="text-xs mb-4" style={{ color: 'var(--av-text-muted)' }}>
          {subtitle}
        </p>
      )}
      {!subtitle && <div className="mb-4" />}
      {children}
    </div>
  )
}

function InfoButton({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold transition-colors"
        style={{
          color: open ? 'var(--av-accent)' : 'var(--av-text-muted)',
          backgroundColor: open ? 'var(--av-accent-alpha)' : 'transparent',
          border: `1px solid ${open ? 'var(--av-accent)' : 'var(--av-border)'}`,
        }}
      >
        i
      </button>
      {open && (
        <div
          className="absolute right-0 top-7 z-10 w-64 rounded-lg border p-3 text-xs leading-relaxed shadow-lg"
          style={{
            backgroundColor: 'var(--av-bg-surface)',
            borderColor: 'var(--av-border)',
            color: 'var(--av-text-secondary)',
          }}
        >
          {text}
        </div>
      )}
    </div>
  )
}

function DemandRow({
  item,
  maxTotal,
}: {
  item: {
    skill_name: string
    user_invocations: number
    auto_invocations: number
    total_usage: number
    auto_rate: number
  }
  maxTotal: number
}) {
  const [hovered, setHovered] = useState(false)
  const userPct = (item.user_invocations / maxTotal) * 100
  const autoPct = (item.auto_invocations / maxTotal) * 100

  return (
    <div
      className="group"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-xs truncate" style={{ color: 'var(--av-text)' }}>
          {item.skill_name}
        </span>
        <span className="text-[11px] shrink-0 ml-2" style={{ color: 'var(--av-text-muted)' }}>
          {hovered ? (
            <>
              <span style={{ color: 'var(--av-accent)' }}>主動 {item.user_invocations}</span>
              {' / '}
              <span style={{ color: 'var(--av-info)' }}>自動 {item.auto_invocations}</span>
            </>
          ) : (
            <>
              {item.total_usage} 次
              <span
                className="ml-1.5"
                style={{ color: item.auto_rate >= 50 ? 'var(--av-info)' : 'var(--av-accent)' }}
              >
                ({item.auto_rate.toFixed(0)}% auto)
              </span>
            </>
          )}
        </span>
      </div>
      <div
        className="flex h-2 rounded-full overflow-hidden"
        style={{ backgroundColor: 'var(--av-border)' }}
      >
        <div
          className="h-full"
          style={{ width: `${userPct}%`, backgroundColor: 'var(--av-accent)' }}
        />
        <div
          className="h-full"
          style={{ width: `${autoPct}%`, backgroundColor: 'var(--av-info)' }}
        />
      </div>
    </div>
  )
}

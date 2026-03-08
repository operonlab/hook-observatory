import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { lifecycleApi } from '../api'
import type { LifecycleRun, LifecycleTrends } from '../types'
import { STATUS_CONFIG, TRIGGER_LABELS } from '../types'

export default function DashboardPage() {
  const navigate = useNavigate()
  const [latestRun, setLatestRun] = useState<LifecycleRun | null>(null)
  const [trends, setTrends] = useState<LifecycleTrends | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([lifecycleApi.list({ limit: 1 }), lifecycleApi.trends(30)])
      .then(([runsData, trendsData]) => {
        setLatestRun(runsData.items[0] || null)
        setTrends(trendsData)
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

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-semibold" style={{ color: 'var(--av-text)' }}>
        技能鍛造總覽
      </h1>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="總執行次數" value={trends?.total_runs ?? 0} color="var(--av-info)" />
        <StatCard
          label="平均通過率"
          value={`${trends?.avg_pass_rate ?? 0}%`}
          color="var(--av-pass)"
        />
        <StatCard
          label="最新技能數"
          value={latestRun?.total_skills ?? 0}
          color="var(--av-accent)"
        />
        <StatCard
          label="安全阻擋"
          value={latestRun?.sec_blocked ?? 0}
          color={latestRun?.sec_blocked ? 'var(--av-fail)' : 'var(--av-pass)'}
        />
      </div>

      {/* Latest Run Card */}
      {latestRun && (
        <button
          type="button"
          className="rounded-lg border p-5 cursor-pointer hover:border-[var(--av-accent)] transition-colors w-full text-left"
          style={{
            backgroundColor: 'var(--av-bg-card)',
            borderColor: 'var(--av-border)',
          }}
          onClick={() => navigate(`/anvil/runs/${latestRun.run_id}`)}
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium" style={{ color: 'var(--av-text)' }}>
              最近一次執行
            </h2>
            <span
              className="text-xs px-2 py-1 rounded-full"
              style={{
                color: STATUS_CONFIG[latestRun.status].color,
                backgroundColor: STATUS_CONFIG[latestRun.status].bg,
              }}
            >
              {STATUS_CONFIG[latestRun.status].label}
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>
              <div style={{ color: 'var(--av-text-muted)' }}>Run ID</div>
              <div style={{ color: 'var(--av-text)' }} className="font-mono text-xs">
                {latestRun.run_id}
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--av-text-muted)' }}>觸發</div>
              <div style={{ color: 'var(--av-text)' }}>{TRIGGER_LABELS[latestRun.trigger]}</div>
            </div>
            <div>
              <div style={{ color: 'var(--av-text-muted)' }}>測試</div>
              <div>
                <span style={{ color: 'var(--av-pass)' }}>{latestRun.test_passed} pass</span>
                {latestRun.test_failed > 0 && (
                  <span style={{ color: 'var(--av-fail)' }}> / {latestRun.test_failed} fail</span>
                )}
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--av-text-muted)' }}>日期</div>
              <div style={{ color: 'var(--av-text)' }}>{latestRun.started_at?.slice(0, 10)}</div>
            </div>
          </div>
        </button>
      )}

      {/* Trend Mini Chart (simple bars) */}
      {trends && trends.points.length > 0 && (
        <div
          className="rounded-lg border p-5"
          style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
        >
          <h2 className="text-sm font-medium mb-4" style={{ color: 'var(--av-text)' }}>
            通過率趨勢 (30 天)
          </h2>
          <div className="flex items-end gap-1 h-20">
            {trends.points.map((p, i) => (
              <div
                key={i}
                className="flex-1 rounded-t-sm min-w-[4px]"
                style={{
                  height: `${p.pass_rate}%`,
                  backgroundColor:
                    p.pass_rate >= 80
                      ? 'var(--av-pass)'
                      : p.pass_rate >= 60
                        ? 'var(--av-warn)'
                        : 'var(--av-fail)',
                  opacity: 0.7,
                }}
                title={`${p.date}: ${p.pass_rate}%`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

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

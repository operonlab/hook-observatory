import { useEffect, useState } from 'react'
import { lifecycleApi } from '../api'
import type { LifecycleRun } from '../types'

export default function HealthPage() {
  const [latestRun, setLatestRun] = useState<LifecycleRun | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    lifecycleApi
      .list({ status: 'completed', limit: 1 })
      .then((data) => setLatestRun(data.items[0] || null))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading)
    return (
      <div className="p-6" style={{ color: 'var(--av-text-muted)' }}>
        載入中...
      </div>
    )
  if (!latestRun)
    return (
      <div className="p-6" style={{ color: 'var(--av-text-muted)' }}>
        尚無健康數據
      </div>
    )

  const passRate =
    latestRun.total_skills > 0
      ? ((latestRun.test_passed / latestRun.total_skills) * 100).toFixed(1)
      : '0'

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-semibold" style={{ color: 'var(--av-text)' }}>
        健康狀態
      </h1>

      <div
        className="rounded-lg border p-6 text-center"
        style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
      >
        <div
          className="text-5xl font-bold mb-2"
          style={{
            color:
              Number(passRate) >= 80
                ? 'var(--av-pass)'
                : Number(passRate) >= 60
                  ? 'var(--av-warn)'
                  : 'var(--av-fail)',
          }}
        >
          {passRate}%
        </div>
        <div className="text-sm" style={{ color: 'var(--av-text-muted)' }}>
          整體通過率 ({latestRun.test_passed}/{latestRun.total_skills})
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <StatusCard label="測試通過" value={latestRun.test_passed} color="var(--av-pass)" />
        <StatusCard label="部分通過" value={latestRun.test_partial} color="var(--av-warn)" />
        <StatusCard label="測試失敗" value={latestRun.test_failed} color="var(--av-fail)" />
      </div>

      <div className="text-xs" style={{ color: 'var(--av-text-muted)' }}>
        資料來源: {latestRun.run_id} ({latestRun.started_at?.slice(0, 10)})
      </div>
    </div>
  )
}

function StatusCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div
      className="rounded-lg border p-4 text-center"
      style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
    >
      <div className="text-2xl font-semibold" style={{ color }}>
        {value}
      </div>
      <div className="text-xs mt-1" style={{ color: 'var(--av-text-muted)' }}>
        {label}
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { lifecycleApi } from '../api'
import type { LifecycleRun } from '../types'

export default function SecurityPage() {
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
        尚無安全數據
      </div>
    )

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-xl font-semibold" style={{ color: 'var(--av-text)' }}>
        安全報告
      </h1>

      <div className="grid grid-cols-3 gap-4">
        <div
          className="rounded-lg border p-4 text-center"
          style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
        >
          <div className="text-2xl font-semibold" style={{ color: 'var(--av-pass)' }}>
            {latestRun.sec_clean}
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--av-text-muted)' }}>
            CLEAN
          </div>
        </div>
        <div
          className="rounded-lg border p-4 text-center"
          style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
        >
          <div className="text-2xl font-semibold" style={{ color: 'var(--av-warn)' }}>
            {latestRun.sec_warned}
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--av-text-muted)' }}>
            WARN
          </div>
        </div>
        <div
          className="rounded-lg border p-4 text-center"
          style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
        >
          <div className="text-2xl font-semibold" style={{ color: 'var(--av-fail)' }}>
            {latestRun.sec_blocked}
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--av-text-muted)' }}>
            BLOCKED
          </div>
        </div>
      </div>

      {/* Security details if available */}
      {latestRun.security_details && Array.isArray(latestRun.security_details) && (
        <div
          className="rounded-lg border p-5"
          style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
        >
          <h2 className="text-sm font-medium mb-3" style={{ color: 'var(--av-text)' }}>
            掃描詳情
          </h2>
          <div className="space-y-2">
            {latestRun.security_details
              .filter((s) => s.findings?.length > 0)
              .map((skill) => (
                <div key={skill.skill_name} className="text-xs">
                  <div className="font-mono font-medium" style={{ color: 'var(--av-text)' }}>
                    {skill.skill_name}
                  </div>
                  {skill.findings?.map((f, i) => (
                    <div
                      key={i}
                      className="ml-4 mt-0.5"
                      style={{ color: 'var(--av-text-secondary)' }}
                    >
                      [{f.severity}] {f.pattern} (line {f.line})
                    </div>
                  ))}
                </div>
              ))}
          </div>
        </div>
      )}

      <div className="text-xs" style={{ color: 'var(--av-text-muted)' }}>
        資料來源: {latestRun.run_id} ({latestRun.started_at?.slice(0, 10)})
      </div>
    </div>
  )
}

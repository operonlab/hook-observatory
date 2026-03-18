import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { lifecycleApi } from '../api'
import type { LifecycleRun, LifecycleRunList } from '../types'
import { STATUS_CONFIG, TRIGGER_LABELS } from '../types'

export default function RunsPage() {
  const navigate = useNavigate()
  const [data, setData] = useState<LifecycleRunList | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [loading, setLoading] = useState(true)

  const loadRuns = (status?: string) => {
    setLoading(true)
    lifecycleApi
      .list({ status: status || undefined, limit: 50 })
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadRuns(statusFilter)
  }, [statusFilter])

  const passRate = (r: LifecycleRun) => {
    const total = r.total_skills || 1
    return `${(((r.test_passed + r.test_partial) / total) * 100).toFixed(0)}%`
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold" style={{ color: 'var(--av-text)' }}>
          執行紀錄
        </h1>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-sm rounded-md border px-3 py-1.5"
          style={{
            backgroundColor: 'var(--av-bg-surface)',
            borderColor: 'var(--av-border)',
            color: 'var(--av-text)',
          }}
        >
          <option value="">全部狀態</option>
          <option value="completed">完成</option>
          <option value="failed">失敗</option>
          <option value="running">執行中</option>
          <option value="partial">部分完成</option>
        </select>
      </div>

      {loading ? (
        <div style={{ color: 'var(--av-text-muted)' }}>載入中...</div>
      ) : !data?.items.length ? (
        <div style={{ color: 'var(--av-text-muted)' }}>尚無執行紀錄</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr
                className="text-left border-b"
                style={{ borderColor: 'var(--av-border)', color: 'var(--av-text-muted)' }}
              >
                <th className="pb-2 pr-4 font-medium">Run ID</th>
                <th className="pb-2 pr-4 font-medium">狀態</th>
                <th className="pb-2 pr-4 font-medium">觸發</th>
                <th className="pb-2 pr-4 font-medium">通過率</th>
                <th className="pb-2 pr-4 font-medium">技能數</th>
                <th className="pb-2 pr-4 font-medium">安全</th>
                <th className="pb-2 font-medium">日期</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((run) => (
                <tr
                  key={run.id}
                  className="border-b cursor-pointer hover:bg-[rgba(250,179,135,0.05)] transition-colors"
                  style={{ borderColor: 'var(--av-border)' }}
                  onClick={() => navigate(`/anvil/runs/${run.run_id}`)}
                >
                  <td className="py-3 pr-4 font-mono text-xs" style={{ color: 'var(--av-text)' }}>
                    {run.run_id}
                  </td>
                  <td className="py-3 pr-4">
                    <span
                      className="text-xs px-2 py-0.5 rounded-full"
                      style={{
                        color: STATUS_CONFIG[run.status].color,
                        backgroundColor: STATUS_CONFIG[run.status].bg,
                      }}
                    >
                      {STATUS_CONFIG[run.status].label}
                    </span>
                  </td>
                  <td className="py-3 pr-4" style={{ color: 'var(--av-text-secondary)' }}>
                    {TRIGGER_LABELS[run.trigger]}
                  </td>
                  <td
                    className="py-3 pr-4"
                    style={{
                      color:
                        run.total_skills === 0
                          ? 'var(--av-text-muted)'
                          : (run.test_passed + run.test_partial) / run.total_skills >= 0.8
                            ? 'var(--av-pass)'
                            : (run.test_passed + run.test_partial) / run.total_skills >= 0.6
                              ? 'var(--av-warn)'
                              : 'var(--av-fail)',
                    }}
                  >
                    {passRate(run)}
                  </td>
                  <td className="py-3 pr-4" style={{ color: 'var(--av-text)' }}>
                    {run.total_skills}
                  </td>
                  <td className="py-3 pr-4">
                    {run.sec_blocked > 0 ? (
                      <span style={{ color: 'var(--av-fail)' }}>{run.sec_blocked} blocked</span>
                    ) : (
                      <span style={{ color: 'var(--av-pass)' }}>clean</span>
                    )}
                  </td>
                  <td className="py-3" style={{ color: 'var(--av-text-muted)' }}>
                    {run.started_at?.slice(0, 10)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > data.items.length && (
        <div className="text-xs text-center" style={{ color: 'var(--av-text-muted)' }}>
          顯示 {data.items.length} / {data.total} 筆
        </div>
      )}
    </div>
  )
}

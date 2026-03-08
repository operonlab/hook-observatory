import { Calendar, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { planApi } from '../api'
import type { DailyPlan } from '../types'
import { PLAN_STATUS_CONFIG } from '../types'

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-TW', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    weekday: 'short',
  })
}

export default function HistoryPage() {
  const [plans, setPlans] = useState<DailyPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  const loadData = useCallback((p: number) => {
    setLoading(true)
    setError(null)
    planApi
      .list({ page: p })
      .then((result) => {
        setPlans(result.items)
        setTotal(result.total)
      })
      .catch(() => setError('載入失敗'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadData(page)
  }, [loadData, page])

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--do-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto">
        <div
          className="rounded-lg border p-6 text-center"
          style={{ borderColor: 'var(--do-border)', color: 'var(--do-text-muted)' }}
        >
          <p className="text-[13px] mb-3">{error}</p>
          <button
            type="button"
            onClick={() => loadData(page)}
            className="flex items-center gap-1.5 mx-auto px-3 py-1.5 rounded-md text-[12px]"
            style={{ color: 'var(--do-accent)', backgroundColor: 'var(--do-accent-alpha)' }}
          >
            <RefreshCw size={12} />
            重試
          </button>
        </div>
      </div>
    )
  }

  const pageSize = 20
  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--do-text)' }}>
          歷史紀錄
        </h1>
        <span className="text-[12px]" style={{ color: 'var(--do-text-muted)' }}>
          共 {total} 筆
        </span>
      </div>

      {/* Plan List */}
      {plans.length === 0 ? (
        <div
          className="rounded-lg border p-8 text-center"
          style={{ borderColor: 'var(--do-border)', backgroundColor: 'var(--do-bg-elevated)' }}
        >
          <Calendar size={24} className="mx-auto mb-2" style={{ color: 'var(--do-text-muted)' }} />
          <p className="text-[13px]" style={{ color: 'var(--do-text-muted)' }}>
            尚無歷史紀錄
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {plans.map((plan) => {
            const statusConfig = PLAN_STATUS_CONFIG[plan.status]
            const doneCount = plan.items.filter((i) => i.status === 'done').length
            const totalItems = plan.items.length
            const pct = totalItems > 0 ? Math.round((doneCount / totalItems) * 100) : 0

            return (
              <div
                key={plan.id}
                className="rounded-lg border p-3 transition-colors"
                style={{
                  borderColor: 'var(--do-border)',
                  backgroundColor: 'var(--do-bg-elevated)',
                }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div>
                      <div className="text-[13px] font-medium" style={{ color: 'var(--do-text)' }}>
                        {formatDate(plan.plan_date)}
                      </div>
                      <div className="text-[11px] mt-0.5" style={{ color: 'var(--do-text-muted)' }}>
                        {doneCount}/{totalItems} 項完成
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {/* Completion Score */}
                    {plan.completion_score != null && (
                      <span
                        className="text-[12px] font-mono tabular-nums"
                        style={{
                          color:
                            pct >= 80 ? '#a6e3a1' : pct >= 50 ? '#f9e2af' : 'var(--do-text-muted)',
                        }}
                      >
                        {pct}%
                      </span>
                    )}
                    {/* Mini Progress Bar */}
                    {plan.completion_score == null && totalItems > 0 && (
                      <div
                        className="w-16 h-1.5 rounded-full overflow-hidden"
                        style={{ backgroundColor: 'var(--do-bg-surface)' }}
                      >
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${pct}%`,
                            backgroundColor: '#a6e3a1',
                          }}
                        />
                      </div>
                    )}
                    {/* Status Badge */}
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded"
                      style={{ color: statusConfig.color, backgroundColor: statusConfig.bgColor }}
                    >
                      {statusConfig.label}
                    </span>
                  </div>
                </div>
                {/* Reflection preview */}
                {plan.reflection && (
                  <p
                    className="text-[11px] mt-2 line-clamp-2"
                    style={{ color: 'var(--do-text-secondary)' }}
                  >
                    {plan.reflection}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 rounded text-[12px] transition-colors"
            style={{
              color: page === 1 ? 'var(--do-text-muted)' : 'var(--do-text-secondary)',
              backgroundColor: 'var(--do-bg-surface)',
              cursor: page === 1 ? 'default' : 'pointer',
            }}
          >
            上一頁
          </button>
          <span className="text-[12px] tabular-nums" style={{ color: 'var(--do-text-muted)' }}>
            {page} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1 rounded text-[12px] transition-colors"
            style={{
              color: page === totalPages ? 'var(--do-text-muted)' : 'var(--do-text-secondary)',
              backgroundColor: 'var(--do-bg-surface)',
              cursor: page === totalPages ? 'default' : 'pointer',
            }}
          >
            下一頁
          </button>
        </div>
      )}
    </div>
  )
}

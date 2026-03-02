import { ChevronLeft, ChevronRight, CreditCard } from 'lucide-react'
import { useEffect, useState } from 'react'
import { installmentApi } from '../api'
import type { InstallmentPlan, InstallmentStatus } from '../types'
import { fmtAmt } from '../types'

const STATUS_CONFIG: Record<InstallmentStatus, { label: string; color: string }> = {
  active: { label: '進行中', color: 'var(--fn-transfer)' },
  completed: { label: '已完成', color: 'var(--fn-income)' },
  cancelled: { label: '已取消', color: 'var(--fn-text-muted)' },
}

export default function InstallmentTracker() {
  const [plans, setPlans] = useState<InstallmentPlan[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const pageSize = 10

  useEffect(() => {
    setLoading(true)
    installmentApi
      .list(page, pageSize)
      .then((res) => {
        setPlans(res.items)
        setTotal(res.total)
      })
      .catch(() => setPlans([]))
      .finally(() => setLoading(false))
  }, [page])

  const totalPages = Math.ceil(total / pageSize)

  const totalRemaining = plans
    .filter((p) => p.status === 'active')
    .reduce((sum, p) => sum + p.remaining_amount, 0)

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div
          className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
          style={{
            borderColor: 'var(--fn-accent)',
            borderTopColor: 'transparent',
          }}
        />
      </div>
    )
  }

  if (plans.length === 0) {
    return (
      <div className="text-center py-12 text-sm" style={{ color: 'var(--fn-text-muted)' }}>
        尚無分期付款
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="px-1">
        <span className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
          未還分期總額
        </span>
        <div className="text-lg font-medium" style={{ color: 'var(--fn-expense)' }}>
          ${fmtAmt(totalRemaining)}
        </div>
      </div>

      {/* Plans */}
      <div className="space-y-2">
        {plans.map((plan) => {
          const sCfg = STATUS_CONFIG[plan.status]
          const progress =
            plan.num_installments > 0 ? (plan.paid_count / plan.num_installments) * 100 : 0

          return (
            <div
              key={plan.id}
              className="rounded-lg border p-3 space-y-2"
              style={{
                borderColor: 'var(--fn-border)',
                backgroundColor: 'var(--fn-bg-elevated)',
              }}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <CreditCard size={14} style={{ color: sCfg.color }} />
                  <span className="text-[13px] font-medium" style={{ color: 'var(--fn-text)' }}>
                    {plan.description}
                  </span>
                </div>
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded"
                  style={{
                    backgroundColor: `${sCfg.color}20`,
                    color: sCfg.color,
                  }}
                >
                  {sCfg.label}
                </span>
              </div>

              <div
                className="flex items-center justify-between text-[11px]"
                style={{ color: 'var(--fn-text-muted)' }}
              >
                <span>
                  {plan.paid_count}/{plan.num_installments} 期 · 每期 $
                  {fmtAmt(plan.installment_amount)}
                </span>
                <span>總額 ${fmtAmt(plan.total_amount)}</span>
              </div>

              {/* Progress bar */}
              <div
                className="h-1.5 rounded-full overflow-hidden"
                style={{ backgroundColor: 'var(--fn-bg-surface)' }}
              >
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${progress}%`,
                    backgroundColor: sCfg.color,
                  }}
                />
              </div>

              {plan.merchant && (
                <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
                  {plan.merchant}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="p-1 disabled:opacity-30"
            style={{ color: 'var(--fn-text-tertiary)' }}
          >
            <ChevronLeft size={16} />
          </button>
          <span className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
            {page} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="p-1 disabled:opacity-30"
            style={{ color: 'var(--fn-text-tertiary)' }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  )
}

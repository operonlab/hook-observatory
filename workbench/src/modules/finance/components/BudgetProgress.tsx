import { useEffect, useState } from 'react'
import { budgetApi } from '../api'
import type { Budget } from '../types'

interface BudgetProgressProps {
  yearMonth?: string
}

export default function BudgetProgress({ yearMonth }: BudgetProgressProps) {
  const [budgets, setBudgets] = useState<Budget[]>([])
  const [loading, setLoading] = useState(true)

  const month = yearMonth ?? new Date().toISOString().slice(0, 7)

  useEffect(() => {
    setLoading(true)
    budgetApi
      .list(month)
      .then(setBudgets)
      .catch(() => setBudgets([]))
      .finally(() => setLoading(false))
  }, [month])

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

  if (budgets.length === 0) {
    return (
      <div className="text-center py-12 text-sm" style={{ color: 'var(--fn-text-muted)' }}>
        尚未設定預算
      </div>
    )
  }

  const totalBudget = budgets.filter((b) => !b.category_id).at(0)
  const categoryBudgets = budgets.filter((b) => b.category_id)

  const getBarColor = (pct: number) => {
    if (pct >= 100) return 'var(--fn-expense)'
    if (pct >= 80) return 'var(--fn-warning)'
    return 'var(--fn-accent)'
  }

  return (
    <div className="space-y-4">
      {/* Overall budget */}
      {totalBudget && (
        <div
          className="rounded-lg border p-4 space-y-2"
          style={{
            borderColor: 'var(--fn-border)',
            backgroundColor: 'var(--fn-bg-elevated)',
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-medium" style={{ color: 'var(--fn-text)' }}>
              總預算
            </span>
            <span className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              {month}
            </span>
          </div>
          <div className="flex items-end justify-between">
            <div>
              <span
                className="text-xl font-semibold tabular-nums"
                style={{ color: 'var(--fn-text)' }}
              >
                ${totalBudget.spent_amount.toLocaleString()}
              </span>
              <span className="text-[13px] ml-1" style={{ color: 'var(--fn-text-muted)' }}>
                / ${totalBudget.budget_amount.toLocaleString()}
              </span>
            </div>
            <span
              className="text-[13px] font-medium tabular-nums"
              style={{ color: getBarColor(totalBudget.used_pct) }}
            >
              {Math.round(totalBudget.used_pct)}%
            </span>
          </div>
          <div
            className="h-2 rounded-full overflow-hidden"
            style={{ backgroundColor: 'var(--fn-bg-surface)' }}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.min(100, totalBudget.used_pct)}%`,
                backgroundColor: getBarColor(totalBudget.used_pct),
              }}
            />
          </div>
          {totalBudget.remaining_amount > 0 && (
            <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              剩餘 ${totalBudget.remaining_amount.toLocaleString()}
            </div>
          )}
        </div>
      )}

      {/* Category budgets */}
      {categoryBudgets.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-[11px] font-medium px-1" style={{ color: 'var(--fn-text-tertiary)' }}>
            分類預算
          </h3>
          {categoryBudgets.map((b) => (
            <div
              key={b.id}
              className="rounded-lg border px-3 py-2.5 space-y-1.5"
              style={{
                borderColor: 'var(--fn-border)',
                backgroundColor: 'var(--fn-bg-elevated)',
              }}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs" style={{ color: 'var(--fn-text)' }}>
                  {b.category_name ?? '未分類'}
                </span>
                <span className="text-xs tabular-nums" style={{ color: 'var(--fn-text-tertiary)' }}>
                  ${b.spent_amount.toLocaleString()} / ${b.budget_amount.toLocaleString()}
                </span>
              </div>
              <div
                className="h-1.5 rounded-full overflow-hidden"
                style={{ backgroundColor: 'var(--fn-bg-surface)' }}
              >
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.min(100, b.used_pct)}%`,
                    backgroundColor: getBarColor(b.used_pct),
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

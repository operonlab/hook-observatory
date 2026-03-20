import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Suspense, lazy, useEffect, useState } from 'react'
import { analyticsApi } from '../api'
import type { CategoryBreakdown, MonthlySummary, MonthlyTrend } from '../types'
import { fmtAmt } from '../types'

const ExpensePieChart = lazy(() => import('../components/charts/ExpensePieChart'))
const MonthlyBarChart = lazy(() => import('../components/charts/MonthlyBarChart'))
const TrendLineChart = lazy(() => import('../components/charts/TrendLineChart'))

const ChartFallback = () => <div className="animate-pulse h-64 bg-white/5 rounded" />

export default function AnalyticsPage() {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [summary, setSummary] = useState<MonthlySummary | null>(null)
  const [trends, setTrends] = useState<MonthlyTrend[]>([])
  const [breakdown, setBreakdown] = useState<CategoryBreakdown[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      analyticsApi
        .summary(month)
        .then(setSummary)
        .catch(() => setSummary(null)),
      analyticsApi
        .insights(6)
        .then(setTrends)
        .catch(() => setTrends([])),
      analyticsApi
        .categoryBreakdown(month)
        .then(setBreakdown)
        .catch(() => setBreakdown([])),
    ]).finally(() => setLoading(false))
  }, [month])

  const prevMonth = () => {
    const d = new Date(`${month}-01`)
    d.setMonth(d.getMonth() - 1)
    setMonth(d.toISOString().slice(0, 7))
  }

  const nextMonth = () => {
    const d = new Date(`${month}-01`)
    d.setMonth(d.getMonth() + 1)
    setMonth(d.toISOString().slice(0, 7))
  }

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{
            borderColor: 'var(--fn-accent)',
            borderTopColor: 'transparent',
          }}
        />
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      {/* Header + month picker */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--fn-text)' }}>
          消費分析
        </h1>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={prevMonth}
            className="p-1"
            style={{ color: 'var(--fn-text-tertiary)' }}
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-sm font-medium tabular-nums" style={{ color: 'var(--fn-text)' }}>
            {month}
          </span>
          <button
            type="button"
            onClick={nextMonth}
            className="p-1"
            style={{ color: 'var(--fn-text-tertiary)' }}
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-3 gap-3">
          <div
            className="rounded-lg border p-3"
            style={{
              borderColor: 'var(--fn-border)',
              backgroundColor: 'var(--fn-bg-elevated)',
            }}
          >
            <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              收入
            </div>
            <div
              className="text-lg font-semibold tabular-nums mt-0.5"
              style={{ color: 'var(--fn-income)' }}
            >
              ${fmtAmt(summary.total_income)}
            </div>
          </div>
          <div
            className="rounded-lg border p-3"
            style={{
              borderColor: 'var(--fn-border)',
              backgroundColor: 'var(--fn-bg-elevated)',
            }}
          >
            <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              支出
            </div>
            <div
              className="text-lg font-semibold tabular-nums mt-0.5"
              style={{ color: 'var(--fn-expense)' }}
            >
              ${fmtAmt(summary.total_expense)}
            </div>
          </div>
          <div
            className="rounded-lg border p-3"
            style={{
              borderColor: 'var(--fn-border)',
              backgroundColor: 'var(--fn-bg-elevated)',
            }}
          >
            <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              淨額
            </div>
            <div
              className="text-lg font-semibold tabular-nums mt-0.5"
              style={{
                color: summary.net >= 0 ? 'var(--fn-income)' : 'var(--fn-expense)',
              }}
            >
              ${fmtAmt(summary.net)}
            </div>
          </div>
        </div>
      )}

      {/* Charts grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Expense pie */}
        <div
          className="rounded-lg border p-4"
          style={{
            borderColor: 'var(--fn-border)',
            backgroundColor: 'var(--fn-bg-elevated)',
          }}
        >
          <h3 className="text-[13px] font-medium mb-3" style={{ color: 'var(--fn-text)' }}>
            支出分類佔比
          </h3>
          <Suspense fallback={<ChartFallback />}>
            <ExpensePieChart data={breakdown} />
          </Suspense>
        </div>

        {/* Monthly bar */}
        <div
          className="rounded-lg border p-4"
          style={{
            borderColor: 'var(--fn-border)',
            backgroundColor: 'var(--fn-bg-elevated)',
          }}
        >
          <h3 className="text-[13px] font-medium mb-3" style={{ color: 'var(--fn-text)' }}>
            月度收支對比
          </h3>
          <Suspense fallback={<ChartFallback />}>
            <MonthlyBarChart data={trends} />
          </Suspense>
        </div>

        {/* Trend line - full width */}
        <div
          className="rounded-lg border p-4 lg:col-span-2"
          style={{
            borderColor: 'var(--fn-border)',
            backgroundColor: 'var(--fn-bg-elevated)',
          }}
        >
          <h3 className="text-[13px] font-medium mb-3" style={{ color: 'var(--fn-text)' }}>
            收支趨勢
          </h3>
          <Suspense fallback={<ChartFallback />}>
            <TrendLineChart data={trends} />
          </Suspense>
        </div>
      </div>
    </div>
  )
}

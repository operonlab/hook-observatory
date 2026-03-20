import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Suspense, lazy, useEffect, useState } from 'react'
import { analyticsApi } from '../api'
import type { MonthlySummary, MonthlyTrend, NetWorthPoint } from '../types'
import { fmtAmt } from '../types'

const MonthlyBarChart = lazy(() => import('../components/charts/MonthlyBarChart'))
const NetWorthChart = lazy(() => import('../components/charts/NetWorthChart'))

const ChartFallback = () => <div className="animate-pulse h-64 bg-white/5 rounded" />

export default function ReportPage() {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [summary, setSummary] = useState<MonthlySummary | null>(null)
  const [trends, setTrends] = useState<MonthlyTrend[]>([])
  const [netWorth, setNetWorth] = useState<NetWorthPoint[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      analyticsApi
        .summary(month)
        .then(setSummary)
        .catch(() => setSummary(null)),
      analyticsApi
        .insights(12)
        .then(setTrends)
        .catch(() => setTrends([])),
      analyticsApi
        .netWorth()
        .then(setNetWorth)
        .catch(() => setNetWorth([])),
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

  const savingsRate =
    summary && summary.total_income > 0
      ? Math.round(((summary.total_income - summary.total_expense) / summary.total_income) * 100)
      : 0

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      {/* Header + month picker */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--fn-text)' }}>
          財務報告
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

      {/* KPI cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div
            className="rounded-lg border p-3"
            style={{
              borderColor: 'var(--fn-border)',
              backgroundColor: 'var(--fn-bg-elevated)',
            }}
          >
            <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              總收入
            </div>
            <div
              className="text-base font-semibold tabular-nums mt-0.5"
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
              總支出
            </div>
            <div
              className="text-base font-semibold tabular-nums mt-0.5"
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
              className="text-base font-semibold tabular-nums mt-0.5"
              style={{
                color: summary.net >= 0 ? 'var(--fn-income)' : 'var(--fn-expense)',
              }}
            >
              ${fmtAmt(summary.net)}
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
              儲蓄率
            </div>
            <div
              className="text-base font-semibold tabular-nums mt-0.5"
              style={{
                color:
                  savingsRate >= 20
                    ? 'var(--fn-income)'
                    : savingsRate >= 0
                      ? 'var(--fn-warning)'
                      : 'var(--fn-expense)',
              }}
            >
              {savingsRate}%
            </div>
          </div>
        </div>
      )}

      {/* Wallet overview */}
      {summary && summary.wallet_overview?.length > 0 && (
        <div
          className="rounded-lg border p-4"
          style={{
            borderColor: 'var(--fn-border)',
            backgroundColor: 'var(--fn-bg-elevated)',
          }}
        >
          <h3 className="text-[13px] font-medium mb-3" style={{ color: 'var(--fn-text)' }}>
            錢包異動
          </h3>
          <div className="space-y-2">
            {summary.wallet_overview?.map((w) => (
              <div key={w.wallet_id} className="flex items-center justify-between py-1">
                <span className="text-xs" style={{ color: 'var(--fn-text-secondary)' }}>
                  {w.wallet_name}
                </span>
                <div className="flex items-center gap-4">
                  <span className="text-xs tabular-nums" style={{ color: 'var(--fn-text-muted)' }}>
                    餘額 ${fmtAmt(w.current_balance)}
                  </span>
                  <span
                    className="text-xs tabular-nums"
                    style={{
                      color: w.change >= 0 ? 'var(--fn-income)' : 'var(--fn-expense)',
                    }}
                  >
                    {w.change >= 0 ? '+' : ''}${fmtAmt(w.change)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Charts */}
      <div className="space-y-6">
        <div
          className="rounded-lg border p-4"
          style={{
            borderColor: 'var(--fn-border)',
            backgroundColor: 'var(--fn-bg-elevated)',
          }}
        >
          <h3 className="text-[13px] font-medium mb-3" style={{ color: 'var(--fn-text)' }}>
            12 個月收支趨勢
          </h3>
          <Suspense fallback={<ChartFallback />}>
            <MonthlyBarChart data={trends} />
          </Suspense>
        </div>

        <div
          className="rounded-lg border p-4"
          style={{
            borderColor: 'var(--fn-border)',
            backgroundColor: 'var(--fn-bg-elevated)',
          }}
        >
          <h3 className="text-[13px] font-medium mb-3" style={{ color: 'var(--fn-text)' }}>
            淨資產走勢
          </h3>
          <Suspense fallback={<ChartFallback />}>
            <NetWorthChart data={netWorth} />
          </Suspense>
        </div>
      </div>
    </div>
  )
}

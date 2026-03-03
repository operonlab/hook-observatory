import type { PortfolioSummary } from '../types'
import { fmtAmt, fmtPct } from '../types'

interface Props {
  data: PortfolioSummary | null
  loading: boolean
}

export default function PortfolioCard({ data, loading }: Props) {
  if (loading || !data) {
    return (
      <div className="animate-pulse rounded-xl p-6" style={{ backgroundColor: 'var(--surface0)' }}>
        <div className="h-8 w-48 rounded" style={{ backgroundColor: 'var(--surface1)' }} />
      </div>
    )
  }

  const isPositive = data.total_gain >= 0

  return (
    <div className="rounded-xl p-6" style={{ backgroundColor: 'var(--surface0)' }}>
      <h2 className="mb-4 text-lg font-semibold" style={{ color: 'var(--text)' }}>
        投資組合總覽
      </h2>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div>
          <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
            總市值
          </p>
          <p className="text-xl font-bold" style={{ color: 'var(--text)' }}>
            {fmtAmt(data.total_market_value)}
          </p>
        </div>
        <div>
          <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
            總成本
          </p>
          <p className="text-xl font-bold" style={{ color: 'var(--text)' }}>
            {fmtAmt(data.total_cost)}
          </p>
        </div>
        <div>
          <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
            未實現損益
          </p>
          <p
            className="text-xl font-bold"
            style={{ color: isPositive ? 'var(--green)' : 'var(--red)' }}
          >
            {fmtAmt(data.total_gain)}
          </p>
        </div>
        <div>
          <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
            報酬率
          </p>
          <p
            className="text-xl font-bold"
            style={{ color: isPositive ? 'var(--green)' : 'var(--red)' }}
          >
            {fmtPct(data.gain_pct)}
          </p>
        </div>
      </div>
      <p className="mt-3 text-xs" style={{ color: 'var(--subtext0)' }}>
        {data.account_count} 個帳戶 · {data.position_count} 個持倉
      </p>
    </div>
  )
}

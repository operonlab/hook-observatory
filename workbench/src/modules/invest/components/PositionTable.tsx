import type { Position } from '../types'
import { ASSET_TYPE_CONFIG, fmtAmt, fmtPct } from '../types'

interface Props {
  positions: Position[]
  loading: boolean
}

export default function PositionTable({ positions, loading }: Props) {
  if (loading) {
    return (
      <div className="animate-pulse rounded-xl p-6" style={{ backgroundColor: 'var(--surface0)' }}>
        <div className="h-6 w-32 rounded" style={{ backgroundColor: 'var(--surface1)' }} />
      </div>
    )
  }

  if (positions.length === 0) {
    return (
      <div
        className="rounded-xl p-8 text-center"
        style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext0)' }}
      >
        尚無持倉記錄
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl" style={{ backgroundColor: 'var(--surface0)' }}>
      <table className="w-full text-sm">
        <thead>
          <tr style={{ borderBottom: '1px solid var(--surface1)' }}>
            <th className="p-3 text-left font-medium" style={{ color: 'var(--subtext0)' }}>
              標的
            </th>
            <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
              股數
            </th>
            <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
              均價
            </th>
            <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
              現價
            </th>
            <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
              市值
            </th>
            <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
              損益
            </th>
            <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
              報酬率
            </th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const isPositive = pos.unrealized_gain >= 0
            const config = ASSET_TYPE_CONFIG[pos.asset_type] || ASSET_TYPE_CONFIG.stock

            return (
              <tr
                key={pos.id}
                className="transition-colors hover:opacity-80"
                style={{ borderBottom: '1px solid var(--surface1)' }}
              >
                <td className="p-3">
                  <div className="flex items-center gap-2">
                    <span>{config.icon}</span>
                    <div>
                      <p className="font-medium" style={{ color: 'var(--text)' }}>
                        {pos.symbol}
                      </p>
                      {pos.exchange && (
                        <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
                          {pos.exchange}
                        </p>
                      )}
                    </div>
                  </div>
                </td>
                <td className="p-3 text-right" style={{ color: 'var(--text)' }}>
                  {fmtAmt(pos.shares)}
                </td>
                <td className="p-3 text-right" style={{ color: 'var(--text)' }}>
                  {fmtAmt(pos.avg_cost)}
                </td>
                <td className="p-3 text-right" style={{ color: 'var(--text)' }}>
                  {fmtAmt(pos.current_price)}
                </td>
                <td className="p-3 text-right font-medium" style={{ color: 'var(--text)' }}>
                  {fmtAmt(pos.market_value)}
                </td>
                <td
                  className="p-3 text-right font-medium"
                  style={{ color: isPositive ? 'var(--green)' : 'var(--red)' }}
                >
                  {fmtAmt(pos.unrealized_gain)}
                </td>
                <td
                  className="p-3 text-right font-medium"
                  style={{ color: isPositive ? 'var(--green)' : 'var(--red)' }}
                >
                  {fmtPct(pos.gain_pct)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

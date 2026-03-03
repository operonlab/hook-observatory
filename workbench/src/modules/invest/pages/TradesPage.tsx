import { useCallback, useEffect, useState } from 'react'
import { request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type { Trade } from '../types'
import { fmtAmt, TRADE_TYPE_LABELS } from '../types'

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await request<PaginatedResponse<Trade>>('/invest/trades?page=1&page_size=50')
      setTrades(res.items)
    } catch {
      // empty state
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) {
    return (
      <div className="animate-pulse rounded-xl p-6" style={{ backgroundColor: 'var(--surface0)' }}>
        <div className="h-6 w-32 rounded" style={{ backgroundColor: 'var(--surface1)' }} />
      </div>
    )
  }

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold" style={{ color: 'var(--text)' }}>
        交易紀錄
      </h2>

      {trades.length === 0 ? (
        <div
          className="rounded-xl p-8 text-center"
          style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext0)' }}
        >
          尚無交易紀錄
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl" style={{ backgroundColor: 'var(--surface0)' }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--surface1)' }}>
                <th className="p-3 text-left font-medium" style={{ color: 'var(--subtext0)' }}>
                  日期
                </th>
                <th className="p-3 text-left font-medium" style={{ color: 'var(--subtext0)' }}>
                  類型
                </th>
                <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
                  股數
                </th>
                <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
                  價格
                </th>
                <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
                  金額
                </th>
                <th className="p-3 text-right font-medium" style={{ color: 'var(--subtext0)' }}>
                  手續費
                </th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} style={{ borderBottom: '1px solid var(--surface1)' }}>
                  <td className="p-3" style={{ color: 'var(--text)' }}>
                    {new Date(t.traded_at).toLocaleDateString('zh-TW')}
                  </td>
                  <td className="p-3">
                    <span
                      className="rounded-full px-2 py-0.5 text-xs font-medium"
                      style={{
                        backgroundColor:
                          t.type === 'buy'
                            ? 'var(--red)'
                            : t.type === 'sell'
                              ? 'var(--green)'
                              : 'var(--yellow)',
                        color: 'var(--base)',
                      }}
                    >
                      {TRADE_TYPE_LABELS[t.type] || t.type}
                    </span>
                  </td>
                  <td className="p-3 text-right" style={{ color: 'var(--text)' }}>
                    {fmtAmt(t.shares)}
                  </td>
                  <td className="p-3 text-right" style={{ color: 'var(--text)' }}>
                    {fmtAmt(t.price)}
                  </td>
                  <td className="p-3 text-right font-medium" style={{ color: 'var(--text)' }}>
                    {fmtAmt(t.total_amount)}
                  </td>
                  <td className="p-3 text-right" style={{ color: 'var(--subtext0)' }}>
                    {fmtAmt(t.fee + t.tax)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

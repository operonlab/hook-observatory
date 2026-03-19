import { useEffect, useState } from 'react'
import { walletApi } from '../api'
import type { SnapshotDiff as SnapshotDiffType } from '../types'
import { fmtAmt } from '../types'

interface Props {
  walletId: string
  initialFrom?: number
  initialTo?: number
}

export default function SnapshotDiffPanel({ walletId, initialFrom, initialTo }: Props) {
  const [fromV, setFromV] = useState(initialFrom ?? 1)
  const [toV, setToV] = useState(initialTo ?? 2)
  const [diff, setDiff] = useState<SnapshotDiffType | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchDiff = () => {
    if (fromV >= toV) {
      setError('起始版本必須小於目標版本')
      return
    }
    setError('')
    setLoading(true)
    walletApi
      .snapshotDiff(walletId, fromV, toV)
      .then(setDiff)
      .catch((e) => setError(e.message || '載入失敗'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (initialFrom && initialTo) fetchDiff()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-4">
      {/* Version selector */}
      <div className="flex items-end gap-3">
        <div>
          <label className="text-[11px] block mb-1" style={{ color: 'var(--fn-text-muted)' }}>
            從版本
          </label>
          <input
            type="number"
            min={1}
            value={fromV}
            onChange={(e) => setFromV(Number(e.target.value))}
            className="w-20 px-2 py-1.5 text-xs rounded-md"
            style={{
              backgroundColor: 'var(--fn-bg-surface)',
              border: '1px solid var(--fn-border)',
              color: 'var(--fn-text)',
            }}
          />
        </div>
        <span className="text-xs pb-2" style={{ color: 'var(--fn-text-muted)' }}>
          →
        </span>
        <div>
          <label className="text-[11px] block mb-1" style={{ color: 'var(--fn-text-muted)' }}>
            到版本
          </label>
          <input
            type="number"
            min={2}
            value={toV}
            onChange={(e) => setToV(Number(e.target.value))}
            className="w-20 px-2 py-1.5 text-xs rounded-md"
            style={{
              backgroundColor: 'var(--fn-bg-surface)',
              border: '1px solid var(--fn-border)',
              color: 'var(--fn-text)',
            }}
          />
        </div>
        <button
          type="button"
          onClick={fetchDiff}
          disabled={loading}
          className="px-3 py-1.5 text-xs rounded-md transition-colors"
          style={{
            backgroundColor: 'var(--fn-accent)',
            color: '#fff',
            opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? '載入中...' : '比較'}
        </button>
      </div>

      {error && (
        <div className="text-xs" style={{ color: 'var(--fn-expense)' }}>
          {error}
        </div>
      )}

      {/* Diff display */}
      {diff && (
        <div
          className="rounded-lg border p-4 space-y-4"
          style={{
            borderColor: 'var(--fn-border)',
            backgroundColor: 'var(--fn-bg-elevated)',
          }}
        >
          {/* RPG stat comparison */}
          <div className="grid grid-cols-3 gap-4 text-center">
            {/* From */}
            <div>
              <div className="text-[10px] mb-1" style={{ color: 'var(--fn-text-muted)' }}>
                v{diff.from_version}
              </div>
              <div
                className="text-lg font-semibold tabular-nums"
                style={{ color: 'var(--fn-text)' }}
              >
                ${fmtAmt(diff.from_synced_balance)}
              </div>
              <div className="text-[10px]" style={{ color: 'var(--fn-text-muted)' }}>
                {new Date(diff.from_synced_at).toLocaleDateString('zh-TW')}
              </div>
            </div>

            {/* Delta */}
            <div className="flex flex-col items-center justify-center">
              <div
                className="text-2xl font-bold tabular-nums"
                style={{
                  color: diff.balance_delta > 0 ? 'var(--fn-income)' : diff.balance_delta < 0 ? 'var(--fn-expense)' : 'var(--fn-text-muted)',
                }}
              >
                {diff.balance_delta > 0 ? '▲' : diff.balance_delta < 0 ? '▼' : '─'}
              </div>
              <div
                className="text-sm font-semibold tabular-nums"
                style={{
                  color: diff.balance_delta > 0 ? 'var(--fn-income)' : diff.balance_delta < 0 ? 'var(--fn-expense)' : 'var(--fn-text-muted)',
                }}
              >
                ${fmtAmt(Math.abs(diff.balance_delta))}
              </div>
              <div className="text-[10px]" style={{ color: 'var(--fn-text-muted)' }}>
                {diff.delta_pct > 0 ? '+' : ''}{diff.delta_pct.toFixed(1)}% · {diff.period_days}天
              </div>
            </div>

            {/* To */}
            <div>
              <div className="text-[10px] mb-1" style={{ color: 'var(--fn-text-muted)' }}>
                v{diff.to_version}
              </div>
              <div
                className="text-lg font-semibold tabular-nums"
                style={{ color: 'var(--fn-text)' }}
              >
                ${fmtAmt(diff.to_synced_balance)}
              </div>
              <div className="text-[10px]" style={{ color: 'var(--fn-text-muted)' }}>
                {new Date(diff.to_synced_at).toLocaleDateString('zh-TW')}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

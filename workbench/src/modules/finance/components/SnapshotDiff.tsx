import { useCallback, useEffect, useState } from 'react'
import { walletApi } from '../api'
import type { SnapshotDiff as SnapshotDiffType } from '../types'
import { fmtAmt } from '../types'
import VersionRangeSelector from './VersionRangeSelector'

interface Props {
  walletId: string
  initialFrom?: number
  initialTo?: number
}

export default function SnapshotDiffPanel({ walletId, initialFrom, initialTo }: Props) {
  const [diff, setDiff] = useState<SnapshotDiffType | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchDiff = useCallback(
    (fromV: number, toV: number) => {
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
    },
    [walletId],
  )

  useEffect(() => {
    if (initialFrom && initialTo) fetchDiff(initialFrom, initialTo)
  }, [initialFrom, initialTo, fetchDiff])

  return (
    <div className="space-y-4">
      <VersionRangeSelector
        initialFrom={initialFrom}
        initialTo={initialTo}
        submitLabel="比較"
        loadingLabel="載入中..."
        loading={loading}
        error={error}
        onSubmit={fetchDiff}
      />

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
                  color:
                    diff.balance_delta > 0
                      ? 'var(--fn-income)'
                      : diff.balance_delta < 0
                        ? 'var(--fn-expense)'
                        : 'var(--fn-text-muted)',
                }}
              >
                {diff.balance_delta > 0 ? '▲' : diff.balance_delta < 0 ? '▼' : '─'}
              </div>
              <div
                className="text-sm font-semibold tabular-nums"
                style={{
                  color:
                    diff.balance_delta > 0
                      ? 'var(--fn-income)'
                      : diff.balance_delta < 0
                        ? 'var(--fn-expense)'
                        : 'var(--fn-text-muted)',
                }}
              >
                ${fmtAmt(Math.abs(diff.balance_delta))}
              </div>
              <div className="text-[10px]" style={{ color: 'var(--fn-text-muted)' }}>
                {diff.delta_pct > 0 ? '+' : ''}
                {diff.delta_pct.toFixed(1)}% · {diff.period_days}天
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

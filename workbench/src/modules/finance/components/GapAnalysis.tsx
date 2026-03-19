import { AlertTriangle, CheckCircle } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { walletApi } from '../api'
import type { GapAnalysis as GapAnalysisType } from '../types'
import { fmtAmt } from '../types'
import VersionRangeSelector from './VersionRangeSelector'

interface Props {
  walletId: string
  initialFrom?: number
  initialTo?: number
}

export default function GapAnalysisPanel({ walletId, initialFrom, initialTo }: Props) {
  const navigate = useNavigate()
  const [analysis, setAnalysis] = useState<GapAnalysisType | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchAnalysis = useCallback(
    (fromV: number, toV: number) => {
      if (fromV >= toV) {
        setError('起始版本必須小於目標版本')
        return
      }
      setError('')
      setLoading(true)
      walletApi
        .gapAnalysis(walletId, fromV, toV)
        .then(setAnalysis)
        .catch((e) => setError(e.message || '載入失敗'))
        .finally(() => setLoading(false))
    },
    [walletId],
  )

  useEffect(() => {
    if (initialFrom && initialTo) fetchAnalysis(initialFrom, initialTo)
  }, [initialFrom, initialTo, fetchAnalysis])

  return (
    <div className="space-y-4">
      <VersionRangeSelector
        initialFrom={initialFrom}
        initialTo={initialTo}
        submitLabel="夾擊對帳"
        loadingLabel="分析中..."
        loading={loading}
        error={error}
        onSubmit={fetchAnalysis}
      />

      {analysis && (
        <div className="space-y-4">
          {/* Reconciliation status */}
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs"
            style={{
              backgroundColor: analysis.is_reconciled
                ? 'rgba(166,227,161,0.1)'
                : 'rgba(243,139,168,0.1)',
              color: analysis.is_reconciled ? 'var(--fn-income)' : 'var(--fn-expense)',
            }}
          >
            {analysis.is_reconciled ? <CheckCircle size={14} /> : <AlertTriangle size={14} />}
            {analysis.is_reconciled
              ? '帳目一致 — 快照差分與交易累加吻合'
              : `存在 $${fmtAmt(Math.abs(analysis.gap))} 缺口 — 需要補齊交易記錄`}
          </div>

          {/* Three column visualization */}
          <div
            className="grid grid-cols-3 gap-px rounded-lg overflow-hidden"
            style={{ backgroundColor: 'var(--fn-border)' }}
          >
            {/* Snapshot delta */}
            <div className="p-4 text-center" style={{ backgroundColor: 'var(--fn-bg-elevated)' }}>
              <div className="text-[10px] mb-2" style={{ color: 'var(--fn-text-muted)' }}>
                快照差分 (由上而下)
              </div>
              <div
                className="text-lg font-semibold tabular-nums"
                style={{
                  color: analysis.snapshot_delta >= 0 ? 'var(--fn-income)' : 'var(--fn-expense)',
                }}
              >
                {analysis.snapshot_delta >= 0 ? '+' : ''}${fmtAmt(analysis.snapshot_delta)}
              </div>
              <div className="text-[10px] mt-1" style={{ color: 'var(--fn-text-muted)' }}>
                v{analysis.from_version} → v{analysis.to_version}
              </div>
            </div>

            {/* Gap */}
            <div className="p-4 text-center" style={{ backgroundColor: 'var(--fn-bg-elevated)' }}>
              <div className="text-[10px] mb-2" style={{ color: 'var(--fn-text-muted)' }}>
                Gap
              </div>
              <div
                className="text-lg font-bold tabular-nums"
                style={{
                  color: analysis.is_reconciled ? 'var(--fn-income)' : 'var(--fn-expense)',
                }}
              >
                ${fmtAmt(Math.abs(analysis.gap))}
              </div>
              {analysis.gap_pct !== 0 && (
                <div className="text-[10px] mt-1" style={{ color: 'var(--fn-text-muted)' }}>
                  {analysis.gap_pct > 0 ? '+' : ''}
                  {analysis.gap_pct.toFixed(1)}%
                </div>
              )}
            </div>

            {/* Transaction sum */}
            <div className="p-4 text-center" style={{ backgroundColor: 'var(--fn-bg-elevated)' }}>
              <div className="text-[10px] mb-2" style={{ color: 'var(--fn-text-muted)' }}>
                交易累加 (由下而上)
              </div>
              <div
                className="text-lg font-semibold tabular-nums"
                style={{
                  color: analysis.transaction_sum >= 0 ? 'var(--fn-income)' : 'var(--fn-expense)',
                }}
              >
                {analysis.transaction_sum >= 0 ? '+' : ''}${fmtAmt(analysis.transaction_sum)}
              </div>
              <div className="text-[10px] mt-1" style={{ color: 'var(--fn-text-muted)' }}>
                {analysis.transactions.length} 筆交易
              </div>
            </div>
          </div>

          {/* Create adjustment transaction button */}
          {!analysis.is_reconciled && (
            <button
              type="button"
              onClick={() => {
                const type = analysis.gap > 0 ? 'income' : 'expense'
                const params = new URLSearchParams({
                  prefill_type: type,
                  prefill_amount: String(Math.abs(analysis.gap)),
                  prefill_wallet: walletId,
                  prefill_desc: '對帳調整',
                })
                navigate(`/finance?${params.toString()}`)
              }}
              className="w-full py-2 text-xs rounded-md transition-colors text-center"
              style={{
                backgroundColor: 'rgba(243,139,168,0.1)',
                color: 'var(--fn-expense)',
                border: '1px solid rgba(243,139,168,0.2)',
              }}
            >
              建立調整交易 ({analysis.gap > 0 ? '收入' : '支出'} ${fmtAmt(Math.abs(analysis.gap))})
            </button>
          )}

          {/* Transaction list */}
          {analysis.transactions.length > 0 && (
            <div>
              <div className="text-[11px] mb-2" style={{ color: 'var(--fn-text-muted)' }}>
                區間內交易明細
              </div>
              <div
                className="rounded-lg border divide-y"
                style={{ borderColor: 'var(--fn-border)' }}
              >
                {analysis.transactions.slice(0, 20).map((txn) => (
                  <div
                    key={txn.id}
                    className="flex items-center justify-between px-3 py-2"
                    style={{ backgroundColor: 'var(--fn-bg-elevated)' }}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="text-[11px]"
                        style={{
                          color: txn.type === 'income' ? 'var(--fn-income)' : 'var(--fn-expense)',
                        }}
                      >
                        {txn.type === 'income' ? '+' : '-'}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--fn-text)' }}>
                        {txn.description || txn.merchant || '-'}
                      </span>
                    </div>
                    <span
                      className="text-xs tabular-nums"
                      style={{
                        color: txn.type === 'income' ? 'var(--fn-income)' : 'var(--fn-expense)',
                      }}
                    >
                      ${fmtAmt(txn.amount)}
                    </span>
                  </div>
                ))}
                {analysis.transactions.length > 20 && (
                  <div
                    className="px-3 py-2 text-center text-[11px]"
                    style={{ color: 'var(--fn-text-muted)' }}
                  >
                    ...還有 {analysis.transactions.length - 20} 筆
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

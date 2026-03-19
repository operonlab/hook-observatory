import { Camera } from 'lucide-react'
import { useEffect, useState } from 'react'
import { walletApi } from '../api'
import type { WalletSnapshot } from '../types'
import { fmtAmt } from '../types'

interface Props {
  walletId: string
  onSelectVersions?: (from: number, to: number) => void
}

export default function SnapshotTimeline({ walletId, onSelectVersions }: Props) {
  const [snapshots, setSnapshots] = useState<WalletSnapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  useEffect(() => {
    setLoading(true)
    walletApi
      .snapshots(walletId, 1, 50)
      .then((res) => setSnapshots(res.items))
      .catch(() => setSnapshots([]))
      .finally(() => setLoading(false))
  }, [walletId])

  const toggleSelect = (version: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(version)) {
        next.delete(version)
      } else {
        if (next.size >= 2) {
          // Replace oldest selection
          const arr = Array.from(next)
          next.delete(arr[0])
        }
        next.add(version)
      }
      return next
    })
  }

  const canCompare = selected.size === 2
  const handleCompare = () => {
    if (!canCompare) return
    const [a, b] = Array.from(selected).sort((x, y) => x - y)
    onSelectVersions?.(a, b)
  }

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <div
          className="h-5 w-5 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--fn-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  if (snapshots.length === 0) {
    return (
      <div className="text-center py-8 text-sm" style={{ color: 'var(--fn-text-muted)' }}>
        尚無快照記錄。同步錢包餘額後會自動產生快照。
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Compare button */}
      {canCompare && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={handleCompare}
            className="px-3 py-1.5 text-xs rounded-md transition-colors"
            style={{
              backgroundColor: 'var(--fn-accent)',
              color: '#fff',
            }}
          >
            比較選取的 2 個版本
          </button>
        </div>
      )}

      {/* Timeline */}
      <div className="relative">
        {/* Vertical line */}
        <div
          className="absolute left-4 top-0 bottom-0 w-px"
          style={{ backgroundColor: 'var(--fn-border)' }}
        />

        {snapshots.map((snap, idx) => {
          const isGlobal = !!snap.batch_id
          const isSelected = selected.has(snap.version)
          const diff = snap.synced_balance - snap.calculated_balance
          const prevSnap = idx < snapshots.length - 1 ? snapshots[idx + 1] : null
          const balanceChange = prevSnap
            ? snap.synced_balance - prevSnap.synced_balance
            : 0

          return (
            <button
              key={snap.id}
              type="button"
              onClick={() => toggleSelect(snap.version)}
              className="relative flex items-start gap-3 w-full text-left pl-8 pr-3 py-3 rounded-lg transition-colors"
              style={{
                backgroundColor: isSelected ? 'rgba(137,180,250,0.1)' : 'transparent',
                borderLeft: isSelected ? '2px solid var(--fn-accent)' : '2px solid transparent',
              }}
            >
              {/* Node */}
              <div
                className="absolute left-2.5 top-4 w-3 h-3 rounded-full border-2 z-10"
                style={{
                  borderColor: isGlobal ? 'var(--fn-accent)' : 'var(--fn-text-muted)',
                  backgroundColor: isSelected ? 'var(--fn-accent)' : 'var(--fn-bg-elevated)',
                }}
              />

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="text-xs font-mono font-medium"
                    style={{ color: 'var(--fn-text)' }}
                  >
                    v{snap.version}
                  </span>
                  {isGlobal && (
                    <span title="全域快照">
                      <Camera size={12} style={{ color: 'var(--fn-accent)' }} />
                    </span>
                  )}
                  <span className="text-[10px]" style={{ color: 'var(--fn-text-muted)' }}>
                    {new Date(snap.synced_at).toLocaleString('zh-TW')}
                  </span>
                </div>

                <div className="flex items-baseline gap-3">
                  <span
                    className="text-sm font-semibold tabular-nums"
                    style={{ color: 'var(--fn-text)' }}
                  >
                    ${fmtAmt(snap.synced_balance)}
                  </span>
                  {balanceChange !== 0 && (
                    <span
                      className="text-xs tabular-nums"
                      style={{
                        color: balanceChange > 0 ? 'var(--fn-income)' : 'var(--fn-expense)',
                      }}
                    >
                      {balanceChange > 0 ? '▲' : '▼'} ${fmtAmt(Math.abs(balanceChange))}
                    </span>
                  )}
                  {Math.abs(diff) >= 1 && (
                    <span
                      className="text-[10px] px-1 rounded"
                      style={{
                        backgroundColor: 'rgba(243,139,168,0.1)',
                        color: 'var(--fn-expense)',
                      }}
                    >
                      差異 ${fmtAmt(Math.abs(diff))}
                    </span>
                  )}
                </div>

                {snap.notes && (
                  <div className="text-[11px] mt-1" style={{ color: 'var(--fn-text-muted)' }}>
                    {snap.notes}
                  </div>
                )}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

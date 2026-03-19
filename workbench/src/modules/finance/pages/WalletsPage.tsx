import { Camera } from 'lucide-react'
import { useState } from 'react'
import { walletApi } from '../api'
import WalletForm from '../components/WalletForm'
import WalletList from '../components/WalletList'

export default function WalletsPage() {
  const [showForm, setShowForm] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [snapshotting, setSnapshotting] = useState(false)
  const [snapshotMsg, setSnapshotMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const handleGlobalSnapshot = async () => {
    setSnapshotting(true)
    setSnapshotMsg(null)
    try {
      const res = await walletApi.globalSnapshot()
      setSnapshotMsg({ ok: true, text: `快照完成 — ${res.snapshot_count} 個錢包` })
      setRefreshKey((k) => k + 1)
    } catch {
      setSnapshotMsg({ ok: false, text: '快照失敗，請稍後再試' })
    } finally {
      setSnapshotting(false)
    }
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--fn-text)' }}>
          錢包與資產
        </h1>
        <button
          type="button"
          onClick={handleGlobalSnapshot}
          disabled={snapshotting}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-colors"
          style={{
            backgroundColor: 'var(--fn-bg-surface)',
            color: 'var(--fn-text-muted)',
            border: '1px solid var(--fn-border)',
            opacity: snapshotting ? 0.6 : 1,
          }}
        >
          <Camera size={12} />
          {snapshotting ? '存檔中...' : '全域快照'}
        </button>
      </div>

      {snapshotMsg && (
        <div
          className="text-xs px-3 py-1.5 rounded-md"
          style={{
            backgroundColor: snapshotMsg.ok ? 'rgba(166,227,161,0.1)' : 'rgba(243,139,168,0.1)',
            color: snapshotMsg.ok ? 'var(--fn-income)' : 'var(--fn-expense)',
          }}
        >
          {snapshotMsg.text}
        </div>
      )}

      <WalletList
        key={refreshKey}
        onAdd={() => {
          setShowForm(true)
        }}
      />

      {showForm && (
        <WalletForm
          wallet={null}
          onClose={() => setShowForm(false)}
          onSaved={() => setRefreshKey((k) => k + 1)}
        />
      )}
    </div>
  )
}

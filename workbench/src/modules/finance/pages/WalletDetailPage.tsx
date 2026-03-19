import { ArrowLeft, Edit3 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { walletApi } from '../api'
import GapAnalysisPanel from '../components/GapAnalysis'
import SnapshotDiffPanel from '../components/SnapshotDiff'
import SnapshotTimeline from '../components/SnapshotTimeline'
import WalletForm from '../components/WalletForm'
import type { Wallet } from '../types'
import { fmtAmt, WALLET_TYPE_CONFIG } from '../types'

type Tab = 'timeline' | 'diff' | 'gap'

export default function WalletDetailPage() {
  const { walletId } = useParams<{ walletId: string }>()
  const navigate = useNavigate()
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [tab, setTab] = useState<Tab>('timeline')
  const [showForm, setShowForm] = useState(false)
  const [selectedVersions, setSelectedVersions] = useState<[number, number] | null>(null)

  useEffect(() => {
    if (!walletId) return
    walletApi.get(walletId).then(setWallet).catch(() => navigate('/finance/wallets'))
  }, [walletId, navigate])

  if (!wallet) {
    return (
      <div className="flex justify-center py-12">
        <div
          className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--fn-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  const cfg = WALLET_TYPE_CONFIG[wallet.type]
  const tabs: { key: Tab; label: string }[] = [
    { key: 'timeline', label: '快照歷史' },
    { key: 'diff', label: 'Diff 比較' },
    { key: 'gap', label: 'Gap 分析' },
  ]

  const handleSelectVersions = (from: number, to: number) => {
    setSelectedVersions([from, to])
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/finance/wallets')}
          className="p-1.5 rounded-md transition-colors"
          style={{ color: 'var(--fn-text-muted)' }}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--fn-text)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--fn-text-muted)')}
        >
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-lg">{wallet.icon || cfg.icon}</span>
            <h1 className="text-base font-medium" style={{ color: 'var(--fn-text)' }}>
              {wallet.name}
            </h1>
            <span
              className="text-[10px] px-1.5 py-0.5 rounded"
              style={{ backgroundColor: 'var(--fn-bg-surface)', color: 'var(--fn-text-muted)' }}
            >
              {cfg.label}
            </span>
          </div>
          <div
            className="text-2xl font-semibold tabular-nums mt-1"
            style={{
              color: wallet.current_balance < 0 ? 'var(--fn-expense)' : 'var(--fn-accent)',
            }}
          >
            ${fmtAmt(wallet.current_balance)}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-colors"
          style={{
            backgroundColor: 'var(--fn-bg-surface)',
            color: 'var(--fn-text-muted)',
            border: '1px solid var(--fn-border)',
          }}
        >
          <Edit3 size={12} />
          編輯
        </button>
      </div>

      {/* Tabs */}
      <div
        className="flex gap-1 p-1 rounded-lg"
        style={{ backgroundColor: 'var(--fn-bg-surface)' }}
      >
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className="flex-1 py-1.5 text-xs rounded-md transition-colors text-center"
            style={{
              backgroundColor: tab === t.key ? 'var(--fn-bg-elevated)' : 'transparent',
              color: tab === t.key ? 'var(--fn-text)' : 'var(--fn-text-muted)',
              fontWeight: tab === t.key ? 500 : 400,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === 'timeline' && (
        <SnapshotTimeline
          walletId={wallet.id}
          onSelectVersions={(from, to) => {
            handleSelectVersions(from, to)
            setTab('diff')
          }}
        />
      )}
      {tab === 'diff' && (
        <SnapshotDiffPanel
          walletId={wallet.id}
          initialFrom={selectedVersions?.[0]}
          initialTo={selectedVersions?.[1]}
        />
      )}
      {tab === 'gap' && (
        <GapAnalysisPanel
          walletId={wallet.id}
          initialFrom={selectedVersions?.[0]}
          initialTo={selectedVersions?.[1]}
        />
      )}

      {showForm && (
        <WalletForm
          wallet={wallet}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            walletApi.get(wallet.id).then(setWallet)
            setShowForm(false)
          }}
        />
      )}
    </div>
  )
}

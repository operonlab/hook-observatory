import { useState } from 'react'
import InstallmentTracker from '../components/InstallmentTracker'
import SubscriptionList from '../components/SubscriptionList'
import WalletList from '../components/WalletList'
import type { Wallet } from '../types'

type Tab = 'wallets' | 'installments' | 'subscriptions'

const TABS: { id: Tab; label: string }[] = [
  { id: 'wallets', label: '錢包' },
  { id: 'installments', label: '分期付款' },
  { id: 'subscriptions', label: '訂閱管理' },
]

export default function WalletsPage() {
  const [tab, setTab] = useState<Tab>('wallets')
  const [_editWallet, setEditWallet] = useState<Wallet | null>(null)

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <h1 className="text-base font-medium" style={{ color: 'var(--fn-text)' }}>
        錢包與資產
      </h1>

      {/* Tabs */}
      <div
        className="flex gap-1 p-1 rounded-lg"
        style={{ backgroundColor: 'var(--fn-bg-surface)' }}
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className="flex-1 py-2 text-xs rounded-md transition-colors"
            style={{
              backgroundColor: tab === t.id ? 'var(--fn-bg-elevated)' : 'transparent',
              color: tab === t.id ? 'var(--fn-accent)' : 'var(--fn-text-tertiary)',
              fontWeight: tab === t.id ? 500 : 400,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'wallets' && (
        <WalletList
          onEdit={(w) => setEditWallet(w)}
          onAdd={() => {
            /* TODO: wallet form */
          }}
        />
      )}
      {tab === 'installments' && <InstallmentTracker />}
      {tab === 'subscriptions' && <SubscriptionList />}
    </div>
  )
}

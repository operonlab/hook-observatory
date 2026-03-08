import { useState } from 'react'
import WalletForm from '../components/WalletForm'
import WalletList from '../components/WalletList'
import type { Wallet } from '../types'

export default function WalletsPage() {
  const [editWallet, setEditWallet] = useState<Wallet | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      <h1 className="text-base font-medium" style={{ color: 'var(--fn-text)' }}>
        錢包與資產
      </h1>

      <WalletList
        key={refreshKey}
        onEdit={(w) => {
          setEditWallet(w)
          setShowForm(true)
        }}
        onAdd={() => {
          setEditWallet(null)
          setShowForm(true)
        }}
      />

      {showForm && (
        <WalletForm
          wallet={editWallet}
          onClose={() => setShowForm(false)}
          onSaved={() => setRefreshKey((k) => k + 1)}
        />
      )}
    </div>
  )
}

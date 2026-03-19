import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { walletApi } from '../api'
import type { Wallet } from '../types'
import { fmtAmt } from '../types'
import WalletCard from './WalletCard'

interface WalletListProps {
  onAdd?: () => void
}

export default function WalletList({ onAdd }: WalletListProps) {
  const [wallets, setWallets] = useState<Wallet[]>([])
  const [loading, setLoading] = useState(true)

  const fetchWallets = () => {
    setLoading(true)
    walletApi
      .list()
      .then((res) => setWallets(res.items))
      .catch(() => setWallets([]))
      .finally(() => setLoading(false))
  }

  const handleDeleteWallet = async (wallet: Wallet) => {
    if (!confirm(`確定要刪除錢包「${wallet.name}」嗎？`)) return
    await walletApi.delete(wallet.id)
    setWallets((prev) => prev.filter((w) => w.id !== wallet.id))
  }

  useEffect(() => {
    fetchWallets()
  }, [])

  const totalBalance = wallets
    .filter((w) => w.is_active)
    .reduce((sum, w) => sum + Number(w.current_balance), 0)

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div
          className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
          style={{
            borderColor: 'var(--fn-accent)',
            borderTopColor: 'transparent',
          }}
        />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Total balance */}
      <div className="px-1">
        <span className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
          淨資產
        </span>
        <div
          className="text-2xl font-semibold tabular-nums"
          style={{
            color: totalBalance >= 0 ? 'var(--fn-accent)' : 'var(--fn-expense)',
          }}
        >
          ${fmtAmt(totalBalance)}
        </div>
      </div>

      {/* Wallet grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {wallets.map((w) => (
          <WalletCard key={w.id} wallet={w} onDelete={handleDeleteWallet} />
        ))}

        {/* Add wallet */}
        {onAdd && (
          <button
            type="button"
            onClick={onAdd}
            className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed py-8 transition-colors"
            style={{
              borderColor: 'var(--fn-border)',
              color: 'var(--fn-text-muted)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--fn-accent-dim)'
              e.currentTarget.style.color = 'var(--fn-accent)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--fn-border)'
              e.currentTarget.style.color = 'var(--fn-text-muted)'
            }}
          >
            <Plus size={24} />
            <span className="text-xs">新增錢包</span>
          </button>
        )}
      </div>
    </div>
  )
}

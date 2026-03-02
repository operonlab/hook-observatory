import type { Wallet } from '../types'
import { fmtAmt, WALLET_TYPE_CONFIG } from '../types'
import PrivacyToggle from './PrivacyToggle'

interface WalletCardProps {
  wallet: Wallet
  onEdit?: (wallet: Wallet) => void
  onPrivacyToggle?: (wallet: Wallet) => void
}

export default function WalletCard({ wallet, onEdit, onPrivacyToggle }: WalletCardProps) {
  const cfg = WALLET_TYPE_CONFIG[wallet.type]
  const isNegative = wallet.current_balance < 0

  return (
    <button
      type="button"
      onClick={() => onEdit?.(wallet)}
      className="w-full text-left rounded-lg border p-4 transition-colors"
      style={{
        borderColor: 'var(--fn-border)',
        backgroundColor: 'var(--fn-bg-elevated)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--fn-accent-dim)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--fn-border)'
      }}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">{wallet.icon || cfg.icon}</span>
          <div>
            <div className="text-[13px] font-medium" style={{ color: 'var(--fn-text)' }}>
              {wallet.name}
            </div>
            <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              {cfg.label}
            </div>
          </div>
        </div>
        {onPrivacyToggle && (
          <PrivacyToggle isPrivate={wallet.is_private} onToggle={() => onPrivacyToggle(wallet)} />
        )}
      </div>

      <div className="space-y-1">
        <div
          className="text-xl font-semibold tabular-nums"
          style={{ color: isNegative ? 'var(--fn-expense)' : 'var(--fn-text)' }}
        >
          ${fmtAmt(wallet.current_balance)}
        </div>

        {wallet.type === 'credit_card' && wallet.credit_limit && (
          <div className="space-y-1">
            <div
              className="flex justify-between text-[11px]"
              style={{ color: 'var(--fn-text-muted)' }}
            >
              <span>已使用</span>
              <span>
                {Math.round((Math.abs(wallet.current_balance) / wallet.credit_limit) * 100)}%
              </span>
            </div>
            <div
              className="h-1.5 rounded-full overflow-hidden"
              style={{ backgroundColor: 'var(--fn-bg-surface)' }}
            >
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(100, (Math.abs(wallet.current_balance) / wallet.credit_limit) * 100)}%`,
                  backgroundColor:
                    Math.abs(wallet.current_balance) / wallet.credit_limit > 0.8
                      ? 'var(--fn-expense)'
                      : 'var(--fn-accent)',
                }}
              />
            </div>
            <div className="text-[10px]" style={{ color: 'var(--fn-text-muted)' }}>
              額度 ${fmtAmt(wallet.credit_limit)}
            </div>
          </div>
        )}

        {!wallet.is_active && (
          <span
            className="inline-block text-[10px] px-1.5 py-0.5 rounded mt-1"
            style={{
              backgroundColor: 'var(--fn-bg-surface)',
              color: 'var(--fn-text-muted)',
            }}
          >
            已停用
          </span>
        )}
      </div>
    </button>
  )
}

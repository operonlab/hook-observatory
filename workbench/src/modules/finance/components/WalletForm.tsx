import { X } from 'lucide-react'
import { useState } from 'react'
import { walletApi } from '../api'
import type { Wallet, WalletType } from '../types'
import { WALLET_TYPE_CONFIG } from '../types'

interface WalletFormProps {
  wallet?: Wallet | null
  onClose: () => void
  onSaved: () => void
}

export default function WalletForm({ wallet, onClose, onSaved }: WalletFormProps) {
  const isEdit = !!wallet
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    name: wallet?.name ?? '',
    type: (wallet?.type ?? 'bank_account') as WalletType,
    initial_balance: wallet?.initial_balance?.toString() ?? '0',
    credit_limit: wallet?.credit_limit?.toString() ?? '',
    icon: wallet?.icon ?? '',
    color: wallet?.color ?? '',
    is_active: wallet?.is_active ?? true,
    is_private: wallet?.is_private ?? false,
    sync_balance: '',
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim()) return
    setSaving(true)
    setError(null)
    try {
      if (isEdit && wallet) {
        await walletApi.update(wallet.id, {
          name: form.name,
          icon: form.icon || undefined,
          color: form.color || undefined,
          credit_limit: form.credit_limit ? Number(form.credit_limit) : undefined,
          is_active: form.is_active,
          is_private: form.is_private,
        })
        if (form.sync_balance) {
          await walletApi.sync(wallet.id, Number(form.sync_balance))
        }
      } else {
        await walletApi.create({
          name: form.name,
          type: form.type,
          initial_balance: Number(form.initial_balance) || 0,
          credit_limit: form.credit_limit ? Number(form.credit_limit) : undefined,
          icon: form.icon || undefined,
          color: form.color || undefined,
          is_private: form.is_private,
        })
      }
      onSaved()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : '儲存失敗')
    } finally {
      setSaving(false)
    }
  }

  const fieldStyle = {
    borderColor: 'var(--fn-border)',
    backgroundColor: 'var(--fn-bg-surface)',
    color: 'var(--fn-text)',
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        className="w-full max-w-md mx-4 rounded-lg border overflow-y-auto max-h-[90vh]"
        style={{
          backgroundColor: 'var(--fn-bg-elevated)',
          borderColor: 'var(--fn-border)',
        }}
      >
        <div
          className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--fn-border)' }}
        >
          <h2 className="text-sm font-medium" style={{ color: 'var(--fn-text)' }}>
            {isEdit ? '編輯錢包' : '新增錢包'}
          </h2>
          <button type="button" onClick={onClose} style={{ color: 'var(--fn-text-muted)' }}>
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {error && (
            <div
              className="px-3 py-2 rounded text-xs"
              style={{
                backgroundColor: 'rgba(243, 139, 168, 0.1)',
                color: 'var(--fn-expense)',
              }}
            >
              {error}
            </div>
          )}

          {/* Name */}
          <label className="block space-y-1">
            <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
              名稱
            </span>
            <input
              type="text"
              required
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="w-full px-3 py-2 text-sm rounded border"
              style={fieldStyle}
            />
          </label>

          {/* Type (create only) */}
          {!isEdit && (
            <label className="block space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                類型
              </span>
              <select
                value={form.type}
                onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as WalletType }))}
                className="w-full px-3 py-2 text-sm rounded border"
                style={fieldStyle}
              >
                {Object.entries(WALLET_TYPE_CONFIG).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.icon} {v.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          {/* Initial balance (create only) */}
          {!isEdit && (
            <label className="block space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                初始餘額
              </span>
              <input
                type="number"
                step="0.01"
                value={form.initial_balance}
                onChange={(e) => setForm((f) => ({ ...f, initial_balance: e.target.value }))}
                className="w-full px-3 py-2 text-sm rounded border"
                style={fieldStyle}
              />
            </label>
          )}

          {/* Sync balance (edit only) */}
          {isEdit && (
            <label className="block space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                同步餘額（留空則不更新）
              </span>
              <input
                type="number"
                step="0.01"
                value={form.sync_balance}
                onChange={(e) => setForm((f) => ({ ...f, sync_balance: e.target.value }))}
                placeholder={wallet ? String(wallet.current_balance) : ''}
                className="w-full px-3 py-2 text-sm rounded border"
                style={fieldStyle}
              />
            </label>
          )}

          {/* Credit limit */}
          {(form.type === 'credit_card' || wallet?.type === 'credit_card') && (
            <label className="block space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                信用額度
              </span>
              <input
                type="number"
                step="0.01"
                value={form.credit_limit}
                onChange={(e) => setForm((f) => ({ ...f, credit_limit: e.target.value }))}
                className="w-full px-3 py-2 text-sm rounded border"
                style={fieldStyle}
              />
            </label>
          )}

          {/* Icon + Color */}
          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                圖示（emoji）
              </span>
              <input
                type="text"
                value={form.icon}
                onChange={(e) => setForm((f) => ({ ...f, icon: e.target.value }))}
                placeholder="🏦"
                className="w-full px-3 py-2 text-sm rounded border"
                style={fieldStyle}
              />
            </label>
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                顏色
              </span>
              <input
                type="color"
                value={form.color || '#89b4fa'}
                onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))}
                className="w-full h-9 rounded border cursor-pointer"
                style={{ borderColor: 'var(--fn-border)' }}
              />
            </label>
          </div>

          {/* Toggles */}
          <div className="flex items-center gap-6">
            {isEdit && (
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                  className="rounded"
                />
                <span className="text-xs" style={{ color: 'var(--fn-text-secondary)' }}>
                  啟用
                </span>
              </label>
            )}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.is_private}
                onChange={(e) => setForm((f) => ({ ...f, is_private: e.target.checked }))}
                className="rounded"
              />
              <span className="text-xs" style={{ color: 'var(--fn-text-secondary)' }}>
                隱私模式
              </span>
            </label>
          </div>

          {/* Submit */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs rounded"
              style={{ color: 'var(--fn-text-tertiary)' }}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 text-xs rounded font-medium disabled:opacity-50"
              style={{
                backgroundColor: 'var(--fn-accent)',
                color: 'var(--fn-bg)',
              }}
            >
              {saving ? '儲存中...' : isEdit ? '更新' : '新增'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

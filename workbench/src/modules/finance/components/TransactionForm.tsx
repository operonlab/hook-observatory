import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { categoryApi, exchangeRateApi, tagStyleApi, transactionApi, walletApi } from '../api'
import type { Category, PaymentMethod, Transaction, TransactionType, Wallet } from '../types'
import { PAYMENT_METHOD_LABELS } from '../types'
import IconUpload from './IconUpload'
import TagInput, { itemsToNames, itemsToStyles, type TagItem, tagsToItems } from './TagInput'

interface TransactionFormProps {
  transaction?: Transaction | null
  onClose: () => void
  onSaved: () => void
}

const CURRENCY_OPTIONS = [
  { value: 'TWD', label: 'TWD' },
  { value: 'USD', label: 'USD' },
  { value: 'JPY', label: 'JPY' },
  { value: 'EUR', label: 'EUR' },
  { value: 'GBP', label: 'GBP' },
  { value: 'CNY', label: 'CNY' },
  { value: 'KRW', label: 'KRW' },
  { value: 'HKD', label: 'HKD' },
  { value: 'SGD', label: 'SGD' },
]

function getInitialForm(transaction?: Transaction | null) {
  return {
    type: (transaction?.type ?? 'expense') as TransactionType,
    amount: transaction?.amount?.toString() ?? '',
    currency: transaction?.currency ?? 'TWD',
    description: transaction?.description ?? '',
    merchant: transaction?.merchant ?? '',
    payment_method: (transaction?.payment_method ?? 'credit_card') as PaymentMethod,
    payment_detail: transaction?.payment_detail ?? '',
    category_id: transaction?.category_id ?? '',
    wallet_id: transaction?.wallet_id ?? '',
    transfer_to_wallet_id: transaction?.transfer_to_wallet_id ?? '',
    transacted_at: transaction?.transacted_at
      ? new Date(transaction.transacted_at).toISOString().slice(0, 16)
      : new Date().toISOString().slice(0, 16),
  }
}

export default function TransactionForm({ transaction, onClose, onSaved }: TransactionFormProps) {
  const isEdit = !!transaction
  const [categories, setCategories] = useState<Category[]>([])
  const [wallets, setWallets] = useState<Wallet[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState(() => getInitialForm(transaction))
  const [iconUrl, setIconUrl] = useState<string | null>(transaction?.icon_url ?? null)
  const [tags, setTags] = useState<TagItem[]>([])
  const [tagStyles, setTagStyles] = useState<Record<string, string>>({})
  const [rates, setRates] = useState<Record<string, number>>({})

  useEffect(() => {
    categoryApi
      .list()
      .then(setCategories)
      .catch(() => {})
    walletApi
      .list()
      .then((r) => setWallets(r.items))
      .catch(() => {})
    exchangeRateApi
      .get()
      .then((d) => setRates(d.rates))
      .catch(() => {})
    tagStyleApi
      .get()
      .then((d) => {
        setTagStyles(d.styles)
        if (transaction?.tags) {
          setTags(tagsToItems(transaction.tags, d.styles))
        }
      })
      .catch(() => {
        if (transaction?.tags) setTags(tagsToItems(transaction.tags, {}))
      })
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      // Save tag styles
      const merged = { ...tagStyles, ...itemsToStyles(tags) }
      tagStyleApi.put(merged).catch(() => {})

      const common = {
        type: form.type,
        amount: Number(Number(form.amount).toFixed(2)),
        currency: form.currency,
        description: form.description || undefined,
        merchant: form.merchant || undefined,
        payment_method: form.payment_method,
        payment_detail: form.payment_detail || undefined,
        category_id: form.category_id || undefined,
        tags: itemsToNames(tags),
        icon_url: iconUrl ?? undefined,
        transacted_at: new Date(form.transacted_at).toISOString(),
      }
      if (isEdit && transaction) {
        await transactionApi.update(transaction.id, {
          ...common,
          wallet_id: form.wallet_id || undefined,
        })
      } else {
        await transactionApi.create({
          ...common,
          wallet_id: form.wallet_id,
          transfer_to_wallet_id:
            form.type === 'transfer' ? form.transfer_to_wallet_id || undefined : undefined,
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

  const fs = {
    borderColor: 'var(--fn-border)',
    backgroundColor: 'var(--fn-bg-surface)',
    color: 'var(--fn-text)',
  }

  const twdRate =
    form.currency !== 'TWD' && rates.TWD && rates[form.currency]
      ? rates.TWD / rates[form.currency]
      : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        className="w-full max-w-lg mx-4 rounded-lg border overflow-y-auto max-h-[90vh]"
        style={{ backgroundColor: 'var(--fn-bg-elevated)', borderColor: 'var(--fn-border)' }}
      >
        <div
          className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--fn-border)' }}
        >
          <h2 className="text-sm font-medium" style={{ color: 'var(--fn-text)' }}>
            {isEdit ? '編輯交易' : '新增交易'}
          </h2>
          <button type="button" onClick={onClose} style={{ color: 'var(--fn-text-muted)' }}>
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-3">
          {error && (
            <div
              className="px-3 py-2 rounded text-xs"
              style={{ backgroundColor: 'rgba(243,139,168,0.1)', color: 'var(--fn-expense)' }}
            >
              {error}
            </div>
          )}

          {/* Type */}
          <div className="flex gap-2">
            {(['expense', 'income', 'transfer'] as TransactionType[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setForm((f) => ({ ...f, type: t }))}
                className="flex-1 py-2 text-xs rounded border transition-colors"
                style={{
                  borderColor: form.type === t ? 'var(--fn-accent)' : 'var(--fn-border)',
                  backgroundColor: form.type === t ? 'var(--fn-accent-alpha)' : 'transparent',
                  color: form.type === t ? 'var(--fn-accent)' : 'var(--fn-text-tertiary)',
                }}
              >
                {t === 'expense' ? '支出' : t === 'income' ? '收入' : '轉帳'}
              </button>
            ))}
          </div>

          {/* Icon + Description */}
          <div className="flex items-end gap-3">
            <div className="shrink-0">
              <span className="text-[11px] block mb-1" style={{ color: 'var(--fn-text-tertiary)' }}>
                圖示
              </span>
              <IconUpload value={iconUrl} onChange={setIconUrl} size="sm" />
            </div>
            <label className="flex-1 space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                描述
              </span>
              <input
                type="text"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="午餐、交通費..."
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              />
            </label>
          </div>

          {/* Amount + Currency + Date */}
          <div className="grid grid-cols-[1fr_auto_1fr] gap-2">
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                金額
              </span>
              <input
                type="number"
                step="0.01"
                required
                value={form.amount}
                onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              />
            </label>
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                幣別
              </span>
              <select
                value={form.currency}
                onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))}
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              >
                {CURRENCY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.value}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                日期
              </span>
              <input
                type="datetime-local"
                required
                value={form.transacted_at}
                onChange={(e) => setForm((f) => ({ ...f, transacted_at: e.target.value }))}
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              />
            </label>
          </div>

          {/* Exchange rate hint */}
          {twdRate && form.amount && (
            <div
              className="flex items-center gap-2 px-3 py-2 rounded text-[11px]"
              style={{ backgroundColor: 'var(--fn-accent-alpha)', color: 'var(--fn-text-muted)' }}
            >
              <span style={{ fontSize: 14 }}>💱</span>
              <span>
                {form.currency} 1 ≈ NT${twdRate.toFixed(2)} · 換算約{' '}
                <strong style={{ color: 'var(--fn-text)' }}>
                  NT${Math.round(Number(form.amount) * twdRate).toLocaleString()}
                </strong>
              </span>
            </div>
          )}

          {/* Merchant */}
          <label className="space-y-1">
            <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
              商家
            </span>
            <input
              type="text"
              value={form.merchant}
              onChange={(e) => setForm((f) => ({ ...f, merchant: e.target.value }))}
              className="w-full px-3 py-2 text-sm rounded border"
              style={fs}
            />
          </label>

          {/* Payment + Wallet */}
          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                付款方式
              </span>
              <select
                value={form.payment_method}
                onChange={(e) =>
                  setForm((f) => ({ ...f, payment_method: e.target.value as PaymentMethod }))
                }
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              >
                {Object.entries(PAYMENT_METHOD_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                錢包
              </span>
              <select
                value={form.wallet_id}
                onChange={(e) => setForm((f) => ({ ...f, wallet_id: e.target.value }))}
                required
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              >
                <option value="">選擇錢包</option>
                {wallets.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {/* Transfer target wallet */}
          {form.type === 'transfer' && (
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                轉入錢包
              </span>
              <select
                value={form.transfer_to_wallet_id}
                onChange={(e) => setForm((f) => ({ ...f, transfer_to_wallet_id: e.target.value }))}
                required
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              >
                <option value="">選擇目標錢包</option>
                {wallets
                  .filter((w) => w.id !== form.wallet_id)
                  .map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
              </select>
            </label>
          )}

          {/* Category */}
          <label className="space-y-1">
            <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
              分類
            </span>
            <select
              value={form.category_id}
              onChange={(e) => setForm((f) => ({ ...f, category_id: e.target.value }))}
              className="w-full px-3 py-2 text-sm rounded border"
              style={fs}
            >
              <option value="">未分類</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.icon ? `${c.icon} ` : ''}
                  {c.name}
                </option>
              ))}
            </select>
          </label>

          {/* Tags */}
          <div className="space-y-1">
            <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
              標籤
            </span>
            <TagInput value={tags} onChange={setTags} placeholder="輸入後按 Enter 新增" />
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
              style={{ backgroundColor: 'var(--fn-accent)', color: 'var(--fn-bg)' }}
            >
              {saving ? '儲存中...' : isEdit ? '更新' : '新增'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

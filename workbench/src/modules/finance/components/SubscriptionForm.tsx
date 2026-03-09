import { Bell, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { categoryApi, exchangeRateApi, subscriptionApi, tagStyleApi, walletApi } from '../api'
import type {
  BillingCycle,
  Category,
  PaymentMethod,
  Subscription,
  SubscriptionStatus,
  Wallet,
} from '../types'
import { PAYMENT_METHOD_LABELS } from '../types'
import IconUpload from './IconUpload'
import TagInput, { itemsToNames, itemsToStyles, type TagItem, tagsToItems } from './TagInput'

interface SubscriptionFormProps {
  subscription?: Subscription | null
  onClose: () => void
  onSaved: () => void
}

const CYCLE_OPTIONS: { value: BillingCycle; label: string }[] = [
  { value: 'weekly', label: '每週' },
  { value: 'monthly', label: '每月' },
  { value: 'yearly', label: '每年' },
]

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

const REMINDER_OPTIONS = [
  { value: '', label: '不提醒' },
  { value: '0', label: '當天' },
  { value: '1', label: '1 天前' },
  { value: '3', label: '3 天前' },
  { value: '7', label: '7 天前' },
]

function getInitialForm(sub?: Subscription | null) {
  return {
    name: sub?.name ?? '',
    amount: sub?.amount?.toString() ?? '',
    currency: sub?.currency ?? 'TWD',
    billing_cycle: (sub?.billing_cycle ?? 'monthly') as BillingCycle,
    category_id: sub?.category_id ?? '',
    wallet_id: sub?.wallet_id ?? '',
    payment_method: (sub?.payment_method ?? 'credit_card') as PaymentMethod,
    payment_detail: sub?.payment_detail ?? '',
    start_date: sub?.start_date
      ? new Date(sub.start_date).toISOString().slice(0, 10)
      : new Date().toISOString().slice(0, 10),
    end_date: sub?.end_date ? new Date(sub.end_date).toISOString().slice(0, 10) : '',
    reminder_days: sub?.reminder_days?.toString() ?? '',
    notes: sub?.notes ?? '',
    status: (sub?.status ?? 'active') as SubscriptionStatus,
  }
}

export default function SubscriptionForm({
  subscription,
  onClose,
  onSaved,
}: SubscriptionFormProps) {
  const isEdit = !!subscription
  const [categories, setCategories] = useState<Category[]>([])
  const [wallets, setWallets] = useState<Wallet[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState(() => getInitialForm(subscription))
  const [iconUrl, setIconUrl] = useState<string | null>(subscription?.icon_url ?? null)
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
        if (subscription?.tags) {
          setTags(tagsToItems(subscription.tags, d.styles))
        }
      })
      .catch(() => {
        if (subscription?.tags) setTags(tagsToItems(subscription.tags, {}))
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

      const data = {
        name: form.name,
        amount: Number(Number(form.amount).toFixed(2)),
        currency: form.currency,
        billing_cycle: form.billing_cycle,
        category_id: form.category_id || undefined,
        wallet_id: form.wallet_id || undefined,
        payment_method: form.payment_method,
        payment_detail: form.payment_detail || undefined,
        start_date: form.start_date,
        end_date: form.end_date || undefined,
        reminder_days: form.reminder_days ? Number(form.reminder_days) : undefined,
        notes: form.notes || undefined,
        tags: itemsToNames(tags),
        icon_url: iconUrl ?? undefined,
      }
      if (isEdit && subscription) {
        await subscriptionApi.update(subscription.id, { ...data, status: form.status })
      } else {
        await subscriptionApi.create(data)
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
            {isEdit ? '編輯訂閱' : '新增訂閱'}
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

          {/* Icon + Name */}
          <div className="flex items-end gap-3">
            <div className="shrink-0">
              <span className="text-[11px] block mb-1" style={{ color: 'var(--fn-text-tertiary)' }}>
                圖示
              </span>
              <IconUpload value={iconUrl} onChange={setIconUrl} size="sm" />
            </div>
            <label className="flex-1 space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                訂閱名稱
              </span>
              <input
                type="text"
                required
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Netflix、Spotify..."
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              />
            </label>
          </div>

          {/* Amount + Currency + Cycle */}
          <div className="grid grid-cols-[1fr_auto_auto] gap-2">
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
                週期
              </span>
              <select
                value={form.billing_cycle}
                onChange={(e) =>
                  setForm((f) => ({ ...f, billing_cycle: e.target.value as BillingCycle }))
                }
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              >
                {CYCLE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
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

          {/* Start date + End date */}
          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                起始日期
              </span>
              <input
                type="date"
                required
                value={form.start_date}
                onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))}
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              />
            </label>
            <label className="space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                結束日期
              </span>
              <input
                type="date"
                value={form.end_date}
                onChange={(e) => setForm((f) => ({ ...f, end_date: e.target.value }))}
                className="w-full px-3 py-2 text-sm rounded border"
                style={fs}
              />
            </label>
          </div>

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

          {/* Reminder */}
          <label className="space-y-1">
            <span
              className="text-[11px] inline-flex items-center gap-1"
              style={{ color: 'var(--fn-text-tertiary)' }}
            >
              <Bell size={11} /> 提醒
            </span>
            <select
              value={form.reminder_days}
              onChange={(e) => setForm((f) => ({ ...f, reminder_days: e.target.value }))}
              className="w-full px-3 py-2 text-sm rounded border"
              style={fs}
            >
              {REMINDER_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          {/* Notes */}
          <label className="space-y-1">
            <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
              備註
            </span>
            <input
              type="text"
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              className="w-full px-3 py-2 text-sm rounded border"
              style={fs}
            />
          </label>

          {/* Status toggle (edit only) */}
          {isEdit && (
            <div className="flex items-center justify-between py-1">
              <span className="text-[12px]" style={{ color: 'var(--fn-text)' }}>
                {form.status === 'active'
                  ? '啟用中'
                  : form.status === 'paused'
                    ? '已暫停'
                    : '已取消'}
              </span>
              <button
                type="button"
                onClick={() =>
                  setForm((f) => ({
                    ...f,
                    status: f.status === 'active' ? 'paused' : 'active',
                  }))
                }
                className="relative w-10 h-5 rounded-full transition-colors"
                style={{
                  backgroundColor:
                    form.status === 'active' ? 'var(--fn-income)' : 'var(--fn-border)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full transition-transform"
                  style={{
                    backgroundColor: 'white',
                    transform: form.status === 'active' ? 'translateX(20px)' : 'translateX(0)',
                  }}
                />
              </button>
            </div>
          )}

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

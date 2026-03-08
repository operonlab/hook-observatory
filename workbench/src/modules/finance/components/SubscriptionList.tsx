import { Bell, ChevronLeft, ChevronRight, Pause, RefreshCw, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { categoryApi, exchangeRateApi, subscriptionApi, tagStyleApi } from '../api'
import type { BillingCycle, Subscription, SubscriptionStatus } from '../types'
import { fmtAmt } from '../types'

function daysRemaining(nextBilling: string | null): { text: string; urgent: boolean } | null {
  if (!nextBilling) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const billing = new Date(nextBilling)
  billing.setHours(0, 0, 0, 0)
  const diff = Math.ceil((billing.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
  if (diff === 0) return { text: '今天', urgent: true }
  if (diff < 0) return { text: `已過期 ${Math.abs(diff)} 天`, urgent: true }
  if (diff <= 3) return { text: `剩餘 ${diff} 天`, urgent: true }
  return { text: `剩餘 ${diff} 天`, urgent: false }
}

const CYCLE_LABELS: Record<BillingCycle, string> = {
  weekly: '每週',
  monthly: '每月',
  yearly: '每年',
}

const STATUS_CONFIG: Record<SubscriptionStatus, { label: string; color: string }> = {
  active: { label: '啟用', color: 'var(--fn-income)' },
  paused: { label: '暫停', color: 'var(--fn-warning)' },
  cancelled: { label: '已取消', color: 'var(--fn-text-muted)' },
}

interface SubscriptionListProps {
  refreshTrigger?: number
  onEdit?: (sub: Subscription) => void
}

export default function SubscriptionList({ refreshTrigger, onEdit }: SubscriptionListProps) {
  const [items, setItems] = useState<Subscription[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [catMap, setCatMap] = useState<
    Record<string, { name: string; color: string | null; icon: string | null }>
  >({})
  const [rates, setRates] = useState<Record<string, number>>({})
  const [tagColors, setTagColors] = useState<Record<string, string>>({})
  const pageSize = 20

  const fetchData = () => {
    setLoading(true)
    subscriptionApi
      .list(page, pageSize)
      .then((res) => {
        const sorted = [...res.items].sort((a, b) => {
          if (!a.next_billing && !b.next_billing) return 0
          if (!a.next_billing) return 1
          if (!b.next_billing) return -1
          return new Date(a.next_billing).getTime() - new Date(b.next_billing).getTime()
        })
        setItems(sorted)
        setTotal(res.total)
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchData()
    categoryApi
      .list()
      .then((cats) => {
        const map: Record<string, { name: string; color: string | null; icon: string | null }> = {}
        const flatten = (list: any[]) => {
          for (const c of list) {
            map[c.id] = { name: c.name, color: c.color, icon: c.icon }
            if (c.children) flatten(c.children)
          }
        }
        flatten(cats)
        setCatMap(map)
      })
      .catch(() => {})
    exchangeRateApi
      .get()
      .then((data) => setRates(data.rates))
      .catch(() => {})
    tagStyleApi
      .get()
      .then((d) => setTagColors(d.styles))
      .catch(() => {})
  }, [page, refreshTrigger])

  const totalPages = Math.ceil(total / pageSize)

  const toTWD = (amount: number, currency: string) => {
    if (currency === 'TWD' || !rates.TWD || !rates[currency]) return amount
    return amount * (rates.TWD / rates[currency])
  }

  const monthlyEquivalent = (sub: Subscription) => {
    const amt = Number(sub.amount)
    let monthly = amt
    if (sub.billing_cycle === 'yearly') monthly = amt / 12
    else if (sub.billing_cycle === 'weekly') monthly = amt * 4.33
    return Math.round(toTWD(monthly, sub.currency))
  }

  const totalMonthly = items
    .filter((s) => s.status === 'active')
    .reduce((sum, s) => sum + monthlyEquivalent(s), 0)

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="flex items-center justify-between px-1">
        <div>
          <span className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
            每月訂閱總計
          </span>
          <div className="text-lg font-medium" style={{ color: 'var(--fn-expense)' }}>
            NT${fmtAmt(totalMonthly)}
          </div>
        </div>
        <span className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
          {items.filter((s) => s.status === 'active').length} 個啟用中
        </span>
      </div>

      {/* List */}
      {loading ? (
        <div className="flex justify-center py-12">
          <div
            className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
            style={{
              borderColor: 'var(--fn-accent)',
              borderTopColor: 'transparent',
            }}
          />
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 text-sm" style={{ color: 'var(--fn-text-muted)' }}>
          尚無訂閱紀錄
        </div>
      ) : (
        <div className="space-y-1">
          {items.map((sub) => {
            const sCfg = STATUS_CONFIG[sub.status]
            return (
              <div
                key={sub.id}
                className="group flex items-center gap-1 rounded-md transition-colors"
                style={{ backgroundColor: 'transparent' }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--fn-accent-alpha)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                }}
              >
                <button
                  type="button"
                  onClick={() => onEdit?.(sub)}
                  className="flex-1 flex items-center gap-3 px-3 py-2.5 text-left min-w-0"
                >
                  {sub.icon_url && (
                    <img
                      src={`/api${sub.icon_url}`}
                      alt=""
                      className="w-9 h-9 rounded-lg shrink-0 object-cover"
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] truncate" style={{ color: 'var(--fn-text)' }}>
                        {sub.name}
                      </span>
                      <span className="shrink-0 text-right">
                        <span
                          className="text-[13px] font-medium"
                          style={{ color: 'var(--fn-expense)' }}
                        >
                          {sub.currency === 'TWD' ? 'NT$' : `${sub.currency} `}
                          {fmtAmt(sub.amount)}/{CYCLE_LABELS[sub.billing_cycle]}
                        </span>
                        {sub.currency !== 'TWD' && rates.TWD && rates[sub.currency] && (
                          <span
                            className="block text-[10px]"
                            style={{ color: 'var(--fn-text-muted)' }}
                          >
                            ≈ ${fmtAmt(Math.round(toTWD(Number(sub.amount), sub.currency)))} TWD
                          </span>
                        )}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span
                        className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded"
                        style={{
                          backgroundColor: `${sCfg.color}20`,
                          color: sCfg.color,
                        }}
                      >
                        {sub.status === 'active' && <RefreshCw size={9} />}
                        {sub.status === 'paused' && <Pause size={9} />}
                        {sub.status === 'cancelled' && <XCircle size={9} />}
                        {sCfg.label}
                      </span>
                      {(() => {
                        const dr = daysRemaining(sub.next_billing)
                        return dr ? (
                          <span
                            className="text-[11px]"
                            style={{
                              color: dr.urgent ? 'var(--fn-warning)' : 'var(--fn-text-muted)',
                            }}
                          >
                            {dr.text}
                          </span>
                        ) : null
                      })()}
                      {sub.category_id && catMap[sub.category_id] && (
                        <span
                          className="text-[10px] px-1.5 py-0.5 rounded"
                          style={{
                            backgroundColor: catMap[sub.category_id].color
                              ? `${catMap[sub.category_id].color}20`
                              : 'var(--fn-bg-surface)',
                            color: catMap[sub.category_id].color || 'var(--fn-text-tertiary)',
                          }}
                        >
                          {catMap[sub.category_id].icon ? `${catMap[sub.category_id].icon} ` : ''}
                          {catMap[sub.category_id].name}
                        </span>
                      )}
                      {sub.reminder_days != null && (
                        <span
                          className="inline-flex items-center gap-0.5 text-[10px]"
                          style={{ color: 'var(--fn-accent)' }}
                        >
                          <Bell size={9} />
                          {sub.reminder_days === 0 ? '當天' : `${sub.reminder_days}天前`}
                        </span>
                      )}
                      {sub.tags?.map((tag) => {
                        const bg = tagColors[tag]
                        return (
                          <span
                            key={tag}
                            className="text-[10px] px-1.5 py-0.5 rounded"
                            style={{
                              backgroundColor: bg || 'var(--fn-accent-alpha)',
                              color: bg ? '#fff' : 'var(--fn-accent)',
                            }}
                          >
                            {tag}
                          </span>
                        )
                      })}
                    </div>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    if (!confirm(`確定要刪除訂閱「${sub.name}」嗎？`)) return
                    await subscriptionApi.delete(sub.id)
                    setItems((prev) => prev.filter((s) => s.id !== sub.id))
                    setTotal((prev) => prev - 1)
                  }}
                  className="shrink-0 opacity-0 group-hover:opacity-100 text-[12px] px-2 py-1 rounded mr-2"
                  style={{
                    backgroundColor: 'rgba(243,139,168,0.1)',
                    color: '#f38ba8',
                    border: '1px solid rgba(243,139,168,0.2)',
                  }}
                >
                  刪除
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="p-1 disabled:opacity-30"
            style={{ color: 'var(--fn-text-tertiary)' }}
          >
            <ChevronLeft size={16} />
          </button>
          <span className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
            {page} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="p-1 disabled:opacity-30"
            style={{ color: 'var(--fn-text-tertiary)' }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  )
}

import {
  ArrowDownLeft,
  ArrowLeftRight,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { transactionApi } from '../api'
import type { Transaction, TransactionType } from '../types'
import { fmtAmt, PAYMENT_METHOD_LABELS } from '../types'

const TYPE_CONFIG: Record<
  TransactionType,
  { icon: typeof ArrowUpRight; color: string; label: string }
> = {
  income: { icon: ArrowDownLeft, color: 'var(--fn-income)', label: '收入' },
  expense: { icon: ArrowUpRight, color: 'var(--fn-expense)', label: '支出' },
  transfer: {
    icon: ArrowLeftRight,
    color: 'var(--fn-transfer)',
    label: '轉帳',
  },
}

interface TransactionListProps {
  month?: string
  walletId?: string
  onEdit?: (txn: Transaction) => void
}

export default function TransactionList({ month, walletId, onEdit }: TransactionListProps) {
  const [items, setItems] = useState<Transaction[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({ type: '', search: '' })
  const pageSize = 20

  useEffect(() => {
    setLoading(true)
    transactionApi
      .listFiltered({
        page,
        page_size: pageSize,
        month,
        wallet_id: walletId,
        type: filters.type || undefined,
        search: filters.search || undefined,
      })
      .then((res) => {
        setItems(res.items)
        setTotal(res.total)
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [page, month, walletId, filters])

  const totalPages = Math.ceil(total / pageSize)

  const formatAmount = (txn: Transaction) => {
    const sign = txn.type === 'income' ? '+' : txn.type === 'expense' ? '-' : ''
    return `${sign}$${fmtAmt(txn.amount)}`
  }

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <input
          type="text"
          placeholder="搜尋交易..."
          value={filters.search}
          onChange={(e) => {
            setFilters((f) => ({ ...f, search: e.target.value }))
            setPage(1)
          }}
          className="px-3 py-1.5 text-xs rounded border bg-transparent focus:outline-none"
          style={{ borderColor: 'var(--fn-border)', color: 'var(--fn-text)' }}
        />
        <select
          value={filters.type}
          onChange={(e) => {
            setFilters((f) => ({ ...f, type: e.target.value }))
            setPage(1)
          }}
          className="px-3 py-1.5 text-xs rounded border bg-transparent"
          style={{ borderColor: 'var(--fn-border)', color: 'var(--fn-text)' }}
        >
          <option value="">全部類型</option>
          <option value="income">收入</option>
          <option value="expense">支出</option>
          <option value="transfer">轉帳</option>
        </select>
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
          尚無交易紀錄
        </div>
      ) : (
        <div className="space-y-1">
          {items.map((txn) => {
            const cfg = TYPE_CONFIG[txn.type]
            const Icon = cfg.icon
            return (
              <button
                type="button"
                key={txn.id}
                onClick={() => onEdit?.(txn)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md transition-colors text-left"
                style={{ backgroundColor: 'transparent' }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--fn-accent-alpha)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                }}
              >
                <div
                  className="flex items-center justify-center w-8 h-8 rounded-full shrink-0"
                  style={{
                    backgroundColor: `${cfg.color}20`,
                    color: cfg.color,
                  }}
                >
                  <Icon size={14} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] truncate" style={{ color: 'var(--fn-text)' }}>
                      {txn.description || txn.merchant || cfg.label}
                    </span>
                    <span className="text-[13px] font-medium shrink-0" style={{ color: cfg.color }}>
                      {formatAmount(txn)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
                      {new Date(txn.transacted_at).toLocaleDateString('zh-TW')}
                    </span>
                    {txn.category_name && (
                      <span
                        className="text-[11px] px-1.5 py-0.5 rounded"
                        style={{
                          backgroundColor: 'var(--fn-bg-surface)',
                          color: 'var(--fn-text-tertiary)',
                        }}
                      >
                        {txn.category_name}
                      </span>
                    )}
                    <span className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
                      {PAYMENT_METHOD_LABELS[txn.payment_method]}
                    </span>
                  </div>
                </div>
              </button>
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

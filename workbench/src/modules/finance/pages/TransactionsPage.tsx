import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { analyticsApi, categoryApi } from '../api'
import CategoryTree from '../components/CategoryTree'
import TransactionForm from '../components/TransactionForm'
import TransactionList from '../components/TransactionList'
import type { Category, MonthlySummary, Transaction } from '../types'
import { fmtAmt } from '../types'

export default function TransactionsPage() {
  const [showForm, setShowForm] = useState(false)
  const [editTxn, setEditTxn] = useState<Transaction | null>(null)
  const [summary, setSummary] = useState<MonthlySummary | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [refreshKey, setRefreshKey] = useState(0)

  const currentMonth = new Date().toISOString().slice(0, 7)

  useEffect(() => {
    analyticsApi
      .summary(currentMonth)
      .then(setSummary)
      .catch(() => {})
    categoryApi
      .list()
      .then(setCategories)
      .catch(() => {})
  }, [refreshKey])

  const handleSaved = () => {
    setRefreshKey((k) => k + 1)
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--fn-text)' }}>
          交易紀錄
        </h1>
        <button
          type="button"
          onClick={() => {
            setEditTxn(null)
            setShowForm(true)
          }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md font-medium"
          style={{ backgroundColor: 'var(--fn-accent)', color: 'var(--fn-bg)' }}
        >
          <Plus size={14} />
          新增交易
        </button>
      </div>

      {/* Monthly summary cards */}
      {summary && (
        <div className="grid grid-cols-3 gap-3">
          <div
            className="rounded-lg border p-3"
            style={{
              borderColor: 'var(--fn-border)',
              backgroundColor: 'var(--fn-bg-elevated)',
            }}
          >
            <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              收入
            </div>
            <div
              className="text-lg font-semibold tabular-nums mt-0.5"
              style={{ color: 'var(--fn-income)' }}
            >
              ${fmtAmt(summary.total_income)}
            </div>
          </div>
          <div
            className="rounded-lg border p-3"
            style={{
              borderColor: 'var(--fn-border)',
              backgroundColor: 'var(--fn-bg-elevated)',
            }}
          >
            <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              支出
            </div>
            <div
              className="text-lg font-semibold tabular-nums mt-0.5"
              style={{ color: 'var(--fn-expense)' }}
            >
              ${fmtAmt(summary.total_expense)}
            </div>
          </div>
          <div
            className="rounded-lg border p-3"
            style={{
              borderColor: 'var(--fn-border)',
              backgroundColor: 'var(--fn-bg-elevated)',
            }}
          >
            <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
              淨額
            </div>
            <div
              className="text-lg font-semibold tabular-nums mt-0.5"
              style={{
                color: summary.net >= 0 ? 'var(--fn-income)' : 'var(--fn-expense)',
              }}
            >
              ${fmtAmt(summary.net)}
            </div>
          </div>
        </div>
      )}

      {/* Content: sidebar category tree (desktop) + transaction list */}
      <div className="flex gap-6">
        {/* Category sidebar (desktop only) */}
        <div className="hidden lg:block w-48 shrink-0">
          <div className="sticky top-4">
            <h3
              className="text-[11px] font-medium mb-2 px-1"
              style={{ color: 'var(--fn-text-tertiary)' }}
            >
              分類篩選
            </h3>
            <CategoryTree
              categories={categories}
              onRefresh={() => setRefreshKey((k) => k + 1)}
              editable
            />
          </div>
        </div>

        {/* Transaction list */}
        <div className="flex-1 min-w-0">
          <TransactionList
            key={refreshKey}
            month={currentMonth}
            onEdit={(txn) => {
              setEditTxn(txn)
              setShowForm(true)
            }}
          />
        </div>
      </div>

      {/* Form modal */}
      {showForm && (
        <TransactionForm
          transaction={editTxn}
          onClose={() => setShowForm(false)}
          onSaved={handleSaved}
        />
      )}
    </div>
  )
}

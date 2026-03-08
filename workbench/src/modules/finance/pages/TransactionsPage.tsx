import { Filter, Plus, Settings2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import CaptureInbox from '@/modules/capture/CaptureInbox'
import { analyticsApi, categoryApi } from '../api'
import CategoryTree from '../components/CategoryTree'
import InstallmentForm from '../components/InstallmentForm'
import InstallmentTracker from '../components/InstallmentTracker'
import SubscriptionForm from '../components/SubscriptionForm'
import SubscriptionList from '../components/SubscriptionList'
import TransactionForm from '../components/TransactionForm'
import TransactionList from '../components/TransactionList'
import type { Category, MonthlySummary, Subscription, Transaction } from '../types'
import { fmtAmt } from '../types'

type Tab = 'transactions' | 'subscriptions' | 'installments'

const TABS: { id: Tab; label: string }[] = [
  { id: 'transactions', label: '一次性' },
  { id: 'subscriptions', label: '訂閱' },
  { id: 'installments', label: '分期' },
]

const ADD_LABELS: Record<Tab, string> = {
  transactions: '新增交易',
  subscriptions: '新增訂閱',
  installments: '新增分期',
}

export default function TransactionsPage() {
  const [tab, setTab] = useState<Tab>('transactions')
  const [showForm, setShowForm] = useState(false)
  const [showCategoryModal, setShowCategoryModal] = useState(false)
  const [editTxn, setEditTxn] = useState<Transaction | null>(null)
  const [editSub, setEditSub] = useState<Subscription | null>(null)
  const [summary, setSummary] = useState<MonthlySummary | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null)
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

  const openCreate = () => {
    setEditTxn(null)
    setEditSub(null)
    setShowForm(true)
  }

  const selectedCategoryName = selectedCategoryId
    ? categories.find((c) => c.id === selectedCategoryId)?.name
    : null

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--fn-text)' }}>
          交易紀錄
        </h1>
        <div className="flex items-center gap-2">
          {/* Category management button (always visible) */}
          <button
            type="button"
            onClick={() => setShowCategoryModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border"
            style={{
              borderColor: 'var(--fn-border)',
              color: 'var(--fn-text-tertiary)',
            }}
          >
            <Settings2 size={14} />
            <span className="hidden sm:inline">分類管理</span>
          </button>
          <button
            type="button"
            onClick={openCreate}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md font-medium"
            style={{ backgroundColor: 'var(--fn-accent)', color: 'var(--fn-bg)' }}
          >
            <Plus size={14} />
            {ADD_LABELS[tab]}
          </button>
        </div>
      </div>

      {/* Sub-tabs */}
      <div
        className="flex gap-1 p-1 rounded-lg w-fit"
        style={{ backgroundColor: 'var(--fn-bg-surface)' }}
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => {
              setTab(t.id)
              setShowForm(false)
            }}
            className="px-4 py-1.5 text-[13px] rounded-md transition-colors"
            style={{
              backgroundColor: tab === t.id ? 'var(--fn-bg-elevated)' : 'transparent',
              color: tab === t.id ? 'var(--fn-accent)' : 'var(--fn-text-muted)',
              fontWeight: tab === t.id ? 500 : 400,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Monthly summary cards (transactions tab only) */}
      {tab === 'transactions' && summary && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: '收入', value: summary.total_income, color: 'var(--fn-income)' },
            { label: '支出', value: summary.total_expense, color: 'var(--fn-expense)' },
            {
              label: '淨額',
              value: summary.net,
              color: summary.net >= 0 ? 'var(--fn-income)' : 'var(--fn-expense)',
            },
          ].map((card) => (
            <div
              key={card.label}
              className="rounded-lg border p-3"
              style={{
                borderColor: 'var(--fn-border)',
                backgroundColor: 'var(--fn-bg-elevated)',
              }}
            >
              <div className="text-[11px]" style={{ color: 'var(--fn-text-muted)' }}>
                {card.label}
              </div>
              <div
                className="text-lg font-semibold tabular-nums mt-0.5"
                style={{ color: card.color }}
              >
                ${fmtAmt(card.value)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Active category filter badge (transactions tab) */}
      {tab === 'transactions' && selectedCategoryName && (
        <div className="flex items-center gap-2">
          <Filter size={12} style={{ color: 'var(--fn-text-muted)' }} />
          <span
            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md"
            style={{
              backgroundColor: 'var(--fn-accent-alpha)',
              color: 'var(--fn-accent)',
            }}
          >
            {selectedCategoryName}
            <button
              type="button"
              onClick={() => setSelectedCategoryId(null)}
              className="hover:opacity-70"
            >
              <X size={12} />
            </button>
          </span>
        </div>
      )}

      {/* Tab content */}
      {tab === 'transactions' && (
        <div className="flex gap-6">
          {/* Desktop category sidebar */}
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
                selectedId={selectedCategoryId ?? undefined}
                onSelect={(id) => setSelectedCategoryId(id)}
                onRefresh={() => setRefreshKey((k) => k + 1)}
                editable
              />
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <TransactionList
              key={refreshKey}
              month={currentMonth}
              categoryId={selectedCategoryId ?? undefined}
              onEdit={(txn) => {
                setEditTxn(txn)
                setShowForm(true)
              }}
            />
          </div>
        </div>
      )}

      {/* Capture Inbox — pending captures from MCP/CLI */}
      <CaptureInbox module="finance" entityType="transaction" onPromoted={handleSaved} />

      {tab === 'subscriptions' && (
        <SubscriptionList
          refreshTrigger={refreshKey}
          onEdit={(sub) => {
            setEditSub(sub)
            setShowForm(true)
          }}
        />
      )}

      {tab === 'installments' && <InstallmentTracker refreshTrigger={refreshKey} />}

      {/* Form modals */}
      {showForm && tab === 'transactions' && (
        <TransactionForm
          transaction={editTxn}
          onClose={() => setShowForm(false)}
          onSaved={handleSaved}
        />
      )}
      {showForm && tab === 'subscriptions' && (
        <SubscriptionForm
          subscription={editSub}
          onClose={() => setShowForm(false)}
          onSaved={handleSaved}
        />
      )}
      {showForm && tab === 'installments' && (
        <InstallmentForm onClose={() => setShowForm(false)} onSaved={handleSaved} />
      )}

      {/* Category management modal */}
      {showCategoryModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div
            className="w-full max-w-sm mx-4 rounded-lg border overflow-y-auto max-h-[80vh]"
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
                分類管理
              </h2>
              <button
                type="button"
                onClick={() => setShowCategoryModal(false)}
                style={{ color: 'var(--fn-text-muted)' }}
              >
                <X size={18} />
              </button>
            </div>
            <div className="p-4">
              <CategoryTree
                categories={categories}
                selectedId={selectedCategoryId ?? undefined}
                onSelect={(id) => {
                  setSelectedCategoryId(id)
                  setShowCategoryModal(false)
                }}
                onRefresh={() => setRefreshKey((k) => k + 1)}
                editable
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

import { ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { budgetApi } from '../api'
import BudgetProgress from '../components/BudgetProgress'
import BudgetGauge from '../components/charts/BudgetGauge'
import type { Budget, BudgetSet } from '../types'

export default function BudgetPage() {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [budgets, setBudgets] = useState<Budget[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [addForm, setAddForm] = useState({
    budget_amount: '',
    category_id: '',
  })
  const [saving, setSaving] = useState(false)

  const fetchBudgets = () => {
    budgetApi
      .list(month)
      .then(setBudgets)
      .catch(() => setBudgets([]))
  }

  useEffect(() => {
    fetchBudgets()
  }, [month])

  const prevMonth = () => {
    const d = new Date(`${month}-01`)
    d.setMonth(d.getMonth() - 1)
    setMonth(d.toISOString().slice(0, 7))
  }

  const nextMonth = () => {
    const d = new Date(`${month}-01`)
    d.setMonth(d.getMonth() + 1)
    setMonth(d.toISOString().slice(0, 7))
  }

  const handleAdd = async () => {
    if (!addForm.budget_amount) return
    setSaving(true)
    const data: BudgetSet = {
      year_month: month,
      budget_amount: Number(addForm.budget_amount),
      category_id: addForm.category_id || undefined,
    }
    try {
      await budgetApi.set(data)
      setShowAdd(false)
      setAddForm({ budget_amount: '', category_id: '' })
      fetchBudgets()
    } catch {}
    setSaving(false)
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--fn-text)' }}>
          預算管理
        </h1>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md font-medium"
          style={{ backgroundColor: 'var(--fn-accent)', color: 'var(--fn-bg)' }}
        >
          <Plus size={14} />
          設定預算
        </button>
      </div>

      {/* Month picker */}
      <div className="flex items-center justify-center gap-4">
        <button
          type="button"
          onClick={prevMonth}
          className="p-1"
          style={{ color: 'var(--fn-text-tertiary)' }}
        >
          <ChevronLeft size={18} />
        </button>
        <span className="text-sm font-medium tabular-nums" style={{ color: 'var(--fn-text)' }}>
          {month}
        </span>
        <button
          type="button"
          onClick={nextMonth}
          className="p-1"
          style={{ color: 'var(--fn-text-tertiary)' }}
        >
          <ChevronRight size={18} />
        </button>
      </div>

      {/* Gauge grid */}
      {budgets.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
          {budgets.map((b) => (
            <BudgetGauge key={b.id} budget={b} />
          ))}
        </div>
      )}

      {/* Budget progress bars */}
      <BudgetProgress yearMonth={month} />

      {/* Quick add modal */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div
            className="w-full max-w-sm mx-4 rounded-lg border p-5 space-y-4"
            style={{
              backgroundColor: 'var(--fn-bg-elevated)',
              borderColor: 'var(--fn-border)',
            }}
          >
            <h2 className="text-sm font-medium" style={{ color: 'var(--fn-text)' }}>
              設定預算
            </h2>
            <label className="block space-y-1">
              <span className="text-[11px]" style={{ color: 'var(--fn-text-tertiary)' }}>
                預算金額
              </span>
              <input
                type="number"
                required
                value={addForm.budget_amount}
                onChange={(e) => setAddForm((f) => ({ ...f, budget_amount: e.target.value }))}
                className="w-full px-3 py-2 text-sm rounded border"
                style={{
                  borderColor: 'var(--fn-border)',
                  backgroundColor: 'var(--fn-bg-surface)',
                  color: 'var(--fn-text)',
                }}
              />
            </label>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowAdd(false)}
                className="px-4 py-2 text-xs"
                style={{ color: 'var(--fn-text-tertiary)' }}
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleAdd}
                disabled={saving}
                className="px-4 py-2 text-xs rounded font-medium disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--fn-accent)',
                  color: 'var(--fn-bg)',
                }}
              >
                {saving ? '儲存中...' : '儲存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

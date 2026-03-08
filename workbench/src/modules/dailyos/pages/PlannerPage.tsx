import { ArrowRight, BookOpen, Check, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { configApi, planApi } from '../api'
import ColumnsLayout from '../components/layouts/ColumnsLayout'
import GridLayout from '../components/layouts/GridLayout'
import KanbanLayout from '../components/layouts/KanbanLayout'
import ListLayout from '../components/layouts/ListLayout'
import TimelineLayout from '../components/layouts/TimelineLayout'
import ProgressBar from '../components/ProgressBar'
import type {
  DailyPlan,
  LayoutType,
  Method,
  MethodConfig,
  MethodSelection,
  PlanItem,
} from '../types'
import { PLAN_STATUS_CONFIG } from '../types'

const NEXT_STATUS: Record<string, string> = {
  planning: 'active',
  active: 'reviewing',
  reviewing: 'completed',
}

const TRANSITION_LABELS: Record<string, string> = {
  planning: '開始執行',
  active: '進入回顧',
  reviewing: '完成今日',
}

export default function PlannerPage() {
  const navigate = useNavigate()
  const [plan, setPlan] = useState<DailyPlan | null>(null)
  const [selection, setSelection] = useState<MethodSelection | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reflection, setReflection] = useState('')
  const [savingReflection, setSavingReflection] = useState(false)

  const loadData = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([planApi.today().catch(() => null), configApi.getActive().catch(() => null)])
      .then(([todayPlan, activeSelection]) => {
        setPlan(todayPlan)
        setSelection(activeSelection)
        if (todayPlan?.reflection) setReflection(todayPlan.reflection)
      })
      .catch(() => setError('載入失敗'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const method: Method | null = selection?.method || null
  const methodConfig: MethodConfig = method?.config || {}
  const layoutType: LayoutType = method?.layout_type || 'list'

  const handleToggle = useCallback(
    (item: PlanItem) => {
      if (!plan) return
      const updatedItems = plan.items.map((i) =>
        i.id === item.id
          ? { ...i, status: (i.status === 'done' ? 'pending' : 'done') as PlanItem['status'] }
          : i,
      )
      setPlan({ ...plan, items: updatedItems })
      planApi.update(plan.id, { items: updatedItems }).catch(() => {
        // Revert on error
        setPlan(plan)
      })
    },
    [plan],
  )

  const handleAssignCategory = useCallback(
    (itemId: string, categoryId: string) => {
      if (!plan) return
      const updatedItems = plan.items.map((i) =>
        i.id === itemId ? { ...i, category: categoryId } : i,
      )
      setPlan({ ...plan, items: updatedItems })
      planApi.update(plan.id, { items: updatedItems }).catch(() => {
        // Revert on error
        setPlan(plan)
      })
    },
    [plan],
  )

  const handleMoveRight = useCallback(
    (item: PlanItem) => {
      if (!plan) return
      // 3-state: todo (pending, no category) -> doing (pending, category=doing) -> done
      let updatedItems: PlanItem[]
      if (item.category === 'doing') {
        // doing -> done
        updatedItems = plan.items.map((i) =>
          i.id === item.id
            ? { ...i, status: 'done' as PlanItem['status'], category: undefined }
            : i,
        )
      } else {
        // todo -> doing
        updatedItems = plan.items.map((i) =>
          i.id === item.id ? { ...i, category: 'doing' } : i,
        )
      }
      setPlan({ ...plan, items: updatedItems })
      planApi.update(plan.id, { items: updatedItems }).catch(() => {
        setPlan(plan)
      })
    },
    [plan],
  )

  const handleMoveLeft = useCallback(
    (item: PlanItem) => {
      if (!plan) return
      // doing -> todo: remove the "doing" category
      const updatedItems = plan.items.map((i) =>
        i.id === item.id ? { ...i, category: undefined } : i,
      )
      setPlan({ ...plan, items: updatedItems })
      planApi.update(plan.id, { items: updatedItems }).catch(() => {
        setPlan(plan)
      })
    },
    [plan],
  )

  const handleTransition = useCallback(() => {
    if (!plan) return
    const next = NEXT_STATUS[plan.status]
    if (!next) return
    planApi
      .transition(plan.id, next)
      .then((updated) => {
        setPlan(updated)
      })
      .catch(() => {})
  }, [plan])

  const handleCompleteReview = useCallback(() => {
    if (!plan) return
    setSavingReflection(true)
    planApi
      .update(plan.id, { reflection })
      .then(() => planApi.transition(plan.id, 'completed'))
      .then((updated) => {
        setPlan(updated)
      })
      .catch(() => {})
      .finally(() => setSavingReflection(false))
  }, [plan, reflection])

  // Loading state
  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--do-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto">
        <div
          className="rounded-lg border p-6 text-center"
          style={{ borderColor: 'var(--do-border)', color: 'var(--do-text-muted)' }}
        >
          <p className="text-[13px] mb-3">{error}</p>
          <button
            type="button"
            onClick={loadData}
            className="flex items-center gap-1.5 mx-auto px-3 py-1.5 rounded-md text-[12px]"
            style={{ color: 'var(--do-accent)', backgroundColor: 'var(--do-accent-alpha)' }}
          >
            <RefreshCw size={12} />
            重試
          </button>
        </div>
      </div>
    )
  }

  // No active method
  if (!selection || !method) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto">
        <div
          className="rounded-lg border p-8 text-center"
          style={{ borderColor: 'var(--do-border)', backgroundColor: 'var(--do-bg-elevated)' }}
        >
          <span className="text-3xl mb-3 block">📅</span>
          <h2 className="text-[15px] font-medium mb-2" style={{ color: 'var(--do-text)' }}>
            尚未選擇方法論
          </h2>
          <p className="text-[13px] mb-4" style={{ color: 'var(--do-text-secondary)' }}>
            選擇一個每日規劃方法來開始你的一天
          </p>
          <button
            type="button"
            onClick={() => navigate('/dailyos/methods')}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium transition-colors"
            style={{
              backgroundColor: 'var(--do-accent-alpha)',
              color: 'var(--do-accent)',
              border: '1px solid var(--do-accent-dim)',
            }}
          >
            <BookOpen size={14} />
            選擇方法論
          </button>
        </div>
      </div>
    )
  }

  const items = plan?.items || []
  const doneCount = items.filter((i) => i.status === 'done').length
  const totalCount = items.length
  const statusConfig = plan ? PLAN_STATUS_CONFIG[plan.status] : null
  const canTransition = plan && NEXT_STATUS[plan.status]

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">{method.icon || '📋'}</span>
          <div>
            <h1 className="text-base font-medium" style={{ color: 'var(--do-text)' }}>
              {method.name_zh || method.name}
            </h1>
            <span className="text-[11px]" style={{ color: 'var(--do-text-muted)' }}>
              {plan?.plan_date || '今日'}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Status Badge */}
          {statusConfig && (
            <span
              className="text-[11px] px-2 py-1 rounded font-medium"
              style={{ color: statusConfig.color, backgroundColor: statusConfig.bgColor }}
            >
              {statusConfig.icon} {statusConfig.label}
            </span>
          )}
          {/* Switch Method */}
          <button
            type="button"
            onClick={() => navigate('/dailyos/methods')}
            className="text-[11px] px-2 py-1 rounded transition-colors"
            style={{ color: 'var(--do-text-tertiary)', backgroundColor: 'var(--do-bg-surface)' }}
          >
            切換
          </button>
        </div>
      </div>

      {/* Layout Renderer */}
      <div>
        {layoutType === 'list' && (
          <ListLayout items={items} config={methodConfig} onToggle={handleToggle} />
        )}
        {layoutType === 'columns' && (
          <ColumnsLayout items={items} config={methodConfig} onToggle={handleToggle} />
        )}
        {layoutType === 'grid' && (
          <GridLayout items={items} config={methodConfig} onToggle={handleToggle} onAssignCategory={handleAssignCategory} />
        )}
        {layoutType === 'kanban' && (
          <KanbanLayout
            items={items}
            config={methodConfig}
            onMoveRight={handleMoveRight}
            onMoveLeft={handleMoveLeft}
          />
        )}
        {layoutType === 'timeline' && (
          <TimelineLayout items={items} config={methodConfig} onToggle={handleToggle} />
        )}
      </div>

      {/* Progress Bar */}
      {methodConfig.ui_hints?.show_progress_bar !== false && totalCount > 0 && (
        <ProgressBar done={doneCount} total={totalCount} />
      )}

      {/* Reflection Section (reviewing status) */}
      {plan?.status === 'reviewing' && (
        <div
          className="rounded-lg border p-4 space-y-3"
          style={{
            borderColor: 'var(--do-reviewing)',
            backgroundColor: 'rgba(249, 226, 175, 0.05)',
          }}
        >
          <div className="flex items-center gap-2">
            <span className="text-sm">🔍</span>
            <h3 className="text-[13px] font-medium" style={{ color: 'var(--do-reviewing)' }}>
              每日回顧
            </h3>
          </div>
          <textarea
            value={reflection}
            onChange={(e) => setReflection(e.target.value)}
            placeholder="今天完成了什麼？有什麼收穫或值得改進的地方？"
            rows={4}
            className="w-full rounded-md border px-3 py-2 text-[13px] resize-y focus:outline-none"
            style={{
              borderColor: 'var(--do-border)',
              backgroundColor: 'var(--do-bg-surface)',
              color: 'var(--do-text)',
            }}
          />
          <div className="flex justify-end">
            <button
              type="button"
              onClick={handleCompleteReview}
              disabled={savingReflection}
              className="flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium transition-colors disabled:opacity-50"
              style={{
                backgroundColor: 'rgba(166, 227, 161, 0.15)',
                color: 'var(--do-completed)',
                border: '1px solid rgba(166, 227, 161, 0.4)',
              }}
            >
              <Check size={14} />
              {savingReflection ? '儲存中...' : '完成回顧'}
            </button>
          </div>
        </div>
      )}

      {/* Transition Button */}
      {canTransition && plan?.status !== 'reviewing' && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={handleTransition}
            className="flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium transition-colors"
            style={{
              backgroundColor: 'var(--do-accent-alpha)',
              color: 'var(--do-accent)',
              border: '1px solid var(--do-accent-dim)',
            }}
          >
            {TRANSITION_LABELS[plan?.status] || '下一步'}
            <ArrowRight size={14} />
          </button>
        </div>
      )}
    </div>
  )
}

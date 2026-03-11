import {
  ArrowRight,
  BookOpen,
  Calendar,
  Check,
  CheckCircle,
  Eye,
  Pencil,
  Play,
  RefreshCw,
  Search,
} from 'lucide-react'
import { useCallback, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import AddItemInput from '../components/AddItemInput'
import CompositeGuide from '../components/CompositeGuide'
import { DateNavigator } from '../components/DateNavigator'
import ColumnsLayout from '../components/layouts/ColumnsLayout'
import GridLayout from '../components/layouts/GridLayout'
import KanbanLayout from '../components/layouts/KanbanLayout'
import ListLayout from '../components/layouts/ListLayout'
import TimelineLayout from '../components/layouts/TimelineLayout'
import MethodInfoPanel from '../components/MethodInfoPanel'
import MethodSwitcher from '../components/MethodSwitcher'
import ProgressBar from '../components/ProgressBar'
import { useActiveMethod } from '../hooks/useActiveMethod'
import { useDatePlan } from '../hooks/useTodayPlan'
import type { PlanItem } from '../types'
import { PLAN_STATUS_CONFIG } from '../types'

const STATUS_ICONS: Record<string, React.ComponentType<{ size?: number }>> = {
  pencil: Pencil,
  play: Play,
  eye: Eye,
  'check-circle': CheckCircle,
}

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
  const [searchParams, setSearchParams] = useSearchParams()
  const dateParam = searchParams.get('date') || undefined

  const handleDateChange = useCallback(
    (newDate: string) => {
      const today = new Date().toISOString().slice(0, 10)
      if (newDate === today) {
        setSearchParams({}, { replace: true })
      } else {
        setSearchParams({ date: newDate }, { replace: true })
      }
    },
    [setSearchParams],
  )

  const {
    selections,
    method,
    layoutType,
    config: methodConfig,
    loading: methodLoading,
    error: methodError,
    refresh: refreshMethod,
  } = useActiveMethod()

  const {
    plan,
    currentDate,
    items,
    loading: planLoading,
    addItem,
    removeItem,
    editItem,
    reorderItems,
    toggleItem,
    assignCategory,
    scheduleItem,
    moveRight,
    moveLeft,
    transitionPlan,
    completeReview,
    refresh: refreshPlan,
  } = useDatePlan(dateParam)

  const [reflection, setReflection] = useState('')
  const [savingReflection, setSavingReflection] = useState(false)

  const [reflectionSynced, setReflectionSynced] = useState(false)
  if (plan?.reflection && !reflectionSynced) {
    setReflection(plan.reflection)
    setReflectionSynced(true)
  }

  const loading = methodLoading || planLoading
  const error = methodError

  const handleRefresh = () => {
    refreshMethod()
    refreshPlan()
  }

  const handleToggle = (item: PlanItem) => toggleItem(item.id)
  const handleMoveRight = (item: PlanItem) => moveRight(item.id)
  const handleMoveLeft = (item: PlanItem) => moveLeft(item.id)
  const handleDragToColumn = (itemId: string, column: 'todo' | 'doing' | 'done') => {
    if (column === 'done') editItem(itemId, { status: 'done', category: undefined })
    else if (column === 'doing') editItem(itemId, { status: 'pending', category: 'doing' })
    else editItem(itemId, { status: 'pending', category: undefined })
  }

  const handleTransition = () => {
    if (!plan) return
    const next = NEXT_STATUS[plan.status]
    if (next) transitionPlan(next)
  }

  const handleCompleteReview = async () => {
    setSavingReflection(true)
    try {
      await completeReview(reflection)
    } finally {
      setSavingReflection(false)
    }
  }

  // Loading
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

  // Error
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
            onClick={handleRefresh}
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
  if (selections.length === 0 || !method) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-5">
        <MethodSwitcher />
        <div
          className="rounded-lg border p-8 text-center"
          style={{ borderColor: 'var(--do-border)', backgroundColor: 'var(--do-bg-elevated)' }}
        >
          <Calendar size={36} className="mx-auto mb-3" style={{ color: 'var(--do-text-muted)' }} />
          <h2 className="text-[15px] font-medium mb-2" style={{ color: 'var(--do-text)' }}>
            尚未選擇方法論
          </h2>
          <p className="text-[13px] mb-4" style={{ color: 'var(--do-text-secondary)' }}>
            點擊上方任一方法直接啟用，或前往管理頁面了解更多
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
            查看方法論詳情
          </button>
        </div>
      </div>
    )
  }

  const doneCount = items.filter((i) => i.status === 'done').length
  const totalCount = items.length
  const statusConfig = plan ? PLAN_STATUS_CONFIG[plan.status] : null
  const canTransition = plan && NEXT_STATUS[plan.status]

  const StatusIcon = statusConfig ? STATUS_ICONS[statusConfig.icon] : null

  return (
    <div className="p-4 md:p-6 lg:p-8">
      {/* Method quick-switch strip — full width */}
      <MethodSwitcher />

      {/* Date navigator — full width */}
      <div className="mt-4 px-1">
        {currentDate && <DateNavigator currentDate={currentDate} onChange={handleDateChange} />}
      </div>

      {/* Mobile compact header — visible below lg */}
      <div className="lg:hidden mt-3 flex items-center justify-between px-1">
        <div className="min-w-0">
          <h1
            className="text-[14px] font-semibold tracking-tight truncate"
            style={{ color: 'var(--do-text)' }}
          >
            {selections.length === 1
              ? method.name_zh || method.name
              : `${selections.length} 個方法組合`}
          </h1>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {statusConfig && (
            <span
              className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md font-medium"
              style={{ color: statusConfig.color, backgroundColor: statusConfig.bgColor }}
            >
              {StatusIcon && <StatusIcon size={12} />}
              {statusConfig.label}
            </span>
          )}
        </div>
      </div>

      {/* ═══ Two-column layout (lg+) ═══ */}
      <div className="mt-4 lg:mt-5 flex flex-col lg:flex-row gap-5 lg:gap-6">
        {/* ─── Main content area ─── */}
        <div className="flex-1 min-w-0 space-y-4">
          {plan && <AddItemInput onAdd={(title) => addItem(title)} />}

          <div>
            {layoutType === 'list' && (
              <ListLayout
                items={items}
                config={methodConfig}
                onToggle={handleToggle}
                onReorderItems={reorderItems}
                onEdit={editItem}
                onRemove={removeItem}
              />
            )}
            {layoutType === 'columns' && (
              <ColumnsLayout
                items={items}
                config={methodConfig}
                onToggle={handleToggle}
                onAssignCategory={assignCategory}
                onReorderItems={reorderItems}
              />
            )}
            {layoutType === 'grid' && (
              <GridLayout
                items={items}
                config={methodConfig}
                onToggle={handleToggle}
                onAssignCategory={assignCategory}
              />
            )}
            {layoutType === 'kanban' && (
              <KanbanLayout
                items={items}
                config={methodConfig}
                onMoveRight={handleMoveRight}
                onMoveLeft={handleMoveLeft}
                onDragToColumn={handleDragToColumn}
              />
            )}
            {layoutType === 'timeline' && (
              <TimelineLayout
                items={items}
                config={methodConfig}
                onToggle={handleToggle}
                onSchedule={scheduleItem}
              />
            )}
          </div>
        </div>

        {/* ─── Sidebar ─── */}
        <aside className="w-full lg:w-72 xl:w-80 shrink-0 space-y-4">
          {/* Plan summary card */}
          <div className="do-card p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h2
                className="text-[14px] font-semibold tracking-tight truncate"
                style={{ color: 'var(--do-text)' }}
              >
                {selections.length === 1
                  ? method.name_zh || method.name
                  : `${selections.length} 個方法組合`}
              </h2>
              {statusConfig && (
                <span
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md font-medium shrink-0"
                  style={{ color: statusConfig.color, backgroundColor: statusConfig.bgColor }}
                >
                  {StatusIcon && <StatusIcon size={11} />}
                  {statusConfig.label}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <span
                className="flex items-center gap-1 text-[11px]"
                style={{ color: 'var(--do-text-muted)' }}
              >
                <Calendar size={11} />
                {currentDate || '今日'}
              </span>
              {selections.length > 1 &&
                selections.map((sel) => (
                  <span
                    key={sel.id}
                    className="text-[10px] px-1.5 py-0.5 rounded"
                    style={{
                      color: 'var(--do-text-tertiary)',
                      backgroundColor: 'var(--do-bg-surface)',
                    }}
                  >
                    {sel.method?.name_zh || sel.method?.name}
                  </span>
                ))}
            </div>

            {/* Progress */}
            {methodConfig.ui_hints?.show_progress_bar !== false && totalCount > 0 && (
              <>
                <div style={{ height: '1px', backgroundColor: 'var(--do-border)', opacity: 0.4 }} />
                <ProgressBar done={doneCount} total={totalCount} />
              </>
            )}

            {/* Transition button */}
            {canTransition && plan?.status !== 'reviewing' && (
              <>
                <div style={{ height: '1px', backgroundColor: 'var(--do-border)', opacity: 0.4 }} />
                <button
                  type="button"
                  onClick={handleTransition}
                  className="w-full flex items-center justify-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium transition-colors cursor-pointer"
                  style={{
                    backgroundColor: 'var(--do-accent-alpha)',
                    color: 'var(--do-accent)',
                    border: '1px solid var(--do-accent-dim)',
                  }}
                >
                  {TRANSITION_LABELS[plan?.status] || '下一步'}
                  <ArrowRight size={14} />
                </button>
              </>
            )}
          </div>

          {/* Method info — always visible */}
          <MethodInfoPanel method={method} />

          {/* Composite guide */}
          <CompositeGuide methodCount={selections.length} />

          {/* Reflection (reviewing status) */}
          {plan?.status === 'reviewing' && (
            <div
              className="do-card p-4 space-y-3"
              style={{ borderColor: 'rgba(249, 226, 175, 0.3)' }}
            >
              <div className="flex items-center gap-2">
                <Search size={14} style={{ color: 'var(--do-reviewing)' }} />
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
              <button
                type="button"
                onClick={handleCompleteReview}
                disabled={savingReflection}
                className="w-full flex items-center justify-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium transition-colors disabled:opacity-50 cursor-pointer"
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
          )}
        </aside>
      </div>
    </div>
  )
}

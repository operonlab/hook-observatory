import { AlertCircle, ChevronDown, ChevronUp, Clock, Plus, Search, Tag, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { dashboardApi, taskApi } from '../api'
import type { Task, TaskCreate, TaskPriority, TaskSource, TaskStatus, TaskUpdate } from '../types'
import { PRIORITY_CONFIG, SOURCE_CONFIG, STATUS_CONFIG } from '../types'
import { fmtDate } from '../../../shared/utils/formatting'

// ─── Helpers ───

// ─── Status Badge ───

function StatusBadge({ status }: { status: TaskStatus }) {
  const cfg = STATUS_CONFIG[status]
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded font-medium"
      style={{
        color: cfg.color,
        backgroundColor: cfg.bgColor,
        border: `1px solid ${cfg.borderColor}`,
      }}
    >
      {cfg.icon} {cfg.label}
    </span>
  )
}

// ─── Priority Badge ───

function PriorityBadge({ priority }: { priority: TaskPriority }) {
  const cfg = PRIORITY_CONFIG[priority]
  return (
    <span
      className="inline-flex text-[10px] px-1.5 py-0.5 rounded font-medium"
      style={{ color: cfg.color, backgroundColor: cfg.bgColor }}
    >
      {cfg.label}
    </span>
  )
}

// ─── Task Create/Edit Modal ───

interface TaskModalProps {
  initial?: Task | null
  onClose: () => void
  onSave: (data: TaskCreate | TaskUpdate) => Promise<void>
}

function TaskModal({ initial, onClose, onSave }: TaskModalProps) {
  const [title, setTitle] = useState(initial?.title ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [priority, setPriority] = useState<TaskPriority>(initial?.priority ?? 'medium')
  const [source, setSource] = useState<TaskSource>(initial?.source ?? 'personal')
  const [project, setProject] = useState(initial?.project ?? '')
  const [dueDate, setDueDate] = useState(initial?.due_date?.slice(0, 10) ?? '')
  const [estimatedHours, setEstimatedHours] = useState(initial?.estimated_hours?.toString() ?? '')
  const [tagInput, setTagInput] = useState('')
  const [tags, setTags] = useState<string[]>(initial?.tags ?? [])
  const [saving, setSaving] = useState(false)

  const addTag = () => {
    const t = tagInput.trim()
    if (t && !tags.includes(t)) {
      setTags((prev) => [...prev, t])
      setTagInput('')
    }
  }

  const removeTag = (t: string) => setTags((prev) => prev.filter((x) => x !== t))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    setSaving(true)
    try {
      await onSave({
        title: title.trim(),
        description: description.trim() || undefined,
        priority,
        source,
        project: project.trim() || undefined,
        due_date: dueDate || undefined,
        estimated_hours: estimatedHours ? Number(estimatedHours) : undefined,
        tags,
      })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 cursor-default"
        style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
        onClick={onClose}
        aria-label="Close modal"
      />
      <div
        className="relative w-full max-w-lg rounded-xl border p-5 shadow-2xl"
        style={{ backgroundColor: 'var(--tf-bg-surface)', borderColor: 'var(--tf-border)' }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium" style={{ color: 'var(--tf-text)' }}>
            {initial ? '編輯任務' : '新增任務'}
          </h2>
          <button type="button" onClick={onClose} style={{ color: 'var(--tf-text-muted)' }}>
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* Title */}
          <input
            type="text"
            placeholder="任務標題 *"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="w-full rounded-md border px-3 py-2 text-[13px] outline-none focus:border-[color:var(--tf-accent)]"
            style={{
              backgroundColor: 'var(--tf-bg-elevated)',
              borderColor: 'var(--tf-border)',
              color: 'var(--tf-text)',
            }}
          />

          {/* Description */}
          <textarea
            placeholder="描述（可選）"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="w-full rounded-md border px-3 py-2 text-[13px] outline-none focus:border-[color:var(--tf-accent)] resize-none"
            style={{
              backgroundColor: 'var(--tf-bg-elevated)',
              borderColor: 'var(--tf-border)',
              color: 'var(--tf-text)',
            }}
          />

          {/* Row: Priority + Source */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label
                htmlFor="tf-field-1"
                className="text-[11px] mb-1 block"
                style={{ color: 'var(--tf-text-muted)' }}
              >
                優先級
              </label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as TaskPriority)}
                className="w-full rounded-md border px-2 py-1.5 text-[13px] outline-none"
                style={{
                  backgroundColor: 'var(--tf-bg-elevated)',
                  borderColor: 'var(--tf-border)',
                  color: 'var(--tf-text)',
                }}
              >
                {(
                  Object.entries(PRIORITY_CONFIG) as [
                    TaskPriority,
                    (typeof PRIORITY_CONFIG)[TaskPriority],
                  ][]
                ).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="tf-field-2"
                className="text-[11px] mb-1 block"
                style={{ color: 'var(--tf-text-muted)' }}
              >
                來源
              </label>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value as TaskSource)}
                className="w-full rounded-md border px-2 py-1.5 text-[13px] outline-none"
                style={{
                  backgroundColor: 'var(--tf-bg-elevated)',
                  borderColor: 'var(--tf-border)',
                  color: 'var(--tf-text)',
                }}
              >
                {(
                  Object.entries(SOURCE_CONFIG) as [
                    TaskSource,
                    (typeof SOURCE_CONFIG)[TaskSource],
                  ][]
                ).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.icon} {v.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Row: Project + Due Date */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label
                htmlFor="tf-field-3"
                className="text-[11px] mb-1 block"
                style={{ color: 'var(--tf-text-muted)' }}
              >
                專案
              </label>
              <input
                type="text"
                placeholder="專案名稱"
                value={project}
                onChange={(e) => setProject(e.target.value)}
                className="w-full rounded-md border px-2 py-1.5 text-[13px] outline-none focus:border-[color:var(--tf-accent)]"
                style={{
                  backgroundColor: 'var(--tf-bg-elevated)',
                  borderColor: 'var(--tf-border)',
                  color: 'var(--tf-text)',
                }}
              />
            </div>
            <div>
              <label
                htmlFor="tf-field-4"
                className="text-[11px] mb-1 block"
                style={{ color: 'var(--tf-text-muted)' }}
              >
                截止日
              </label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="w-full rounded-md border px-2 py-1.5 text-[13px] outline-none focus:border-[color:var(--tf-accent)]"
                style={{
                  backgroundColor: 'var(--tf-bg-elevated)',
                  borderColor: 'var(--tf-border)',
                  color: 'var(--tf-text)',
                }}
              />
            </div>
          </div>

          {/* Estimated hours */}
          <div>
            <label
              htmlFor="tf-field-5"
              className="text-[11px] mb-1 block"
              style={{ color: 'var(--tf-text-muted)' }}
            >
              預估工時（小時）
            </label>
            <input
              type="number"
              placeholder="0"
              min="0"
              step="0.5"
              value={estimatedHours}
              onChange={(e) => setEstimatedHours(e.target.value)}
              className="w-full rounded-md border px-2 py-1.5 text-[13px] outline-none focus:border-[color:var(--tf-accent)]"
              style={{
                backgroundColor: 'var(--tf-bg-elevated)',
                borderColor: 'var(--tf-border)',
                color: 'var(--tf-text)',
              }}
            />
          </div>

          {/* Tags */}
          <div>
            <label
              htmlFor="tf-field-6"
              className="text-[11px] mb-1 block"
              style={{ color: 'var(--tf-text-muted)' }}
            >
              標籤
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="輸入標籤後按 Enter"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    addTag()
                  }
                }}
                className="flex-1 rounded-md border px-2 py-1.5 text-[13px] outline-none focus:border-[color:var(--tf-accent)]"
                style={{
                  backgroundColor: 'var(--tf-bg-elevated)',
                  borderColor: 'var(--tf-border)',
                  color: 'var(--tf-text)',
                }}
              />
              <button
                type="button"
                onClick={addTag}
                className="px-2 py-1.5 rounded-md text-[13px]"
                style={{
                  backgroundColor: 'var(--tf-accent-alpha)',
                  color: 'var(--tf-accent)',
                  border: '1px solid var(--tf-accent-dim)',
                }}
              >
                <Tag size={14} />
              </button>
            </div>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {tags.map((t) => (
                  <span
                    key={t}
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full"
                    style={{
                      backgroundColor: 'var(--tf-accent-alpha)',
                      color: 'var(--tf-accent)',
                      border: '1px solid var(--tf-accent-dim)',
                    }}
                  >
                    {t}
                    <button type="button" onClick={() => removeTag(t)}>
                      <X size={10} />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-md text-[13px]"
              style={{ color: 'var(--tf-text-tertiary)' }}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving || !title.trim()}
              className="px-4 py-1.5 rounded-md text-[13px] font-medium disabled:opacity-50"
              style={{
                backgroundColor: 'var(--tf-accent)',
                color: 'var(--tf-bg)',
              }}
            >
              {saving ? '儲存中...' : '儲存'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Task Row (expandable) ───

interface TaskRowProps {
  task: Task
  onTransition: (id: string, status: TaskStatus) => Promise<void>
  onEdit: (task: Task) => void
  onDelete: (id: string) => Promise<void>
}

function TaskRow({ task, onTransition, onEdit, onDelete }: TaskRowProps) {
  const [expanded, setExpanded] = useState(false)
  const [transitioning, setTransitioning] = useState(false)

  const NEXT_STATUSES: Record<TaskStatus, TaskStatus[]> = {
    todo: ['in_progress', 'cancelled'],
    in_progress: ['review', 'done', 'blocked', 'todo'],
    review: ['done', 'in_progress', 'blocked'],
    done: ['todo'],
    blocked: ['in_progress', 'cancelled'],
    cancelled: ['todo'],
  }

  const handleTransition = async (status: TaskStatus) => {
    setTransitioning(true)
    try {
      await onTransition(task.id, status)
    } finally {
      setTransitioning(false)
    }
  }

  return (
    <div
      className="rounded-lg border transition-colors"
      style={{ borderColor: 'var(--tf-border)', backgroundColor: 'var(--tf-bg-elevated)' }}
    >
      {/* Main row */}
      <div className="flex items-start gap-3 p-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={task.status} />
            <PriorityBadge priority={task.priority} />
            <span className="text-[11px]" style={{ color: 'var(--tf-text-muted)' }}>
              {SOURCE_CONFIG[task.source].icon}
            </span>
          </div>
          <p
            className="text-[13px] font-medium mt-1 leading-snug"
            style={{
              color: 'var(--tf-text)',
              textDecoration: task.status === 'cancelled' ? 'line-through' : 'none',
            }}
          >
            {task.title}
          </p>
          {task.project && (
            <span className="text-[11px]" style={{ color: 'var(--tf-text-muted)' }}>
              📁 {task.project}
            </span>
          )}
          {task.due_date && (
            <span className="text-[11px] ml-2" style={{ color: 'var(--tf-text-muted)' }}>
              <Clock size={10} className="inline mr-0.5" />
              {fmtDate(task.due_date)}
            </span>
          )}
          {task.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {task.tags.map((t) => (
                <span
                  key={t}
                  className="text-[10px] px-1.5 py-0.5 rounded-full"
                  style={{
                    backgroundColor: 'var(--tf-accent-alpha)',
                    color: 'var(--tf-accent)',
                  }}
                >
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="shrink-0 p-1"
          style={{ color: 'var(--tf-text-muted)' }}
        >
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>

      {/* Expanded actions */}
      {expanded && (
        <div className="border-t px-3 py-2.5 space-y-2" style={{ borderColor: 'var(--tf-border)' }}>
          {task.description && (
            <p className="text-[12px]" style={{ color: 'var(--tf-text-secondary)' }}>
              {task.description}
            </p>
          )}

          {/* Status transitions */}
          <div className="flex flex-wrap gap-1.5">
            <span className="text-[11px]" style={{ color: 'var(--tf-text-muted)' }}>
              轉移：
            </span>
            {NEXT_STATUSES[task.status].map((s) => {
              const cfg = STATUS_CONFIG[s]
              return (
                <button
                  key={s}
                  type="button"
                  disabled={transitioning}
                  onClick={() => handleTransition(s)}
                  className="text-[11px] px-2 py-0.5 rounded border transition-opacity disabled:opacity-50"
                  style={{
                    color: cfg.color,
                    borderColor: cfg.borderColor,
                    backgroundColor: cfg.bgColor,
                  }}
                >
                  → {cfg.label}
                </button>
              )
            })}
          </div>

          {/* Edit / Delete */}
          <div className="flex gap-2 pt-0.5">
            <button
              type="button"
              onClick={() => onEdit(task)}
              className="text-[12px] px-2 py-1 rounded"
              style={{
                backgroundColor: 'var(--tf-accent-alpha)',
                color: 'var(--tf-accent)',
                border: '1px solid var(--tf-accent-dim)',
              }}
            >
              編輯
            </button>
            <button
              type="button"
              onClick={() => onDelete(task.id)}
              className="text-[12px] px-2 py-1 rounded"
              style={{
                backgroundColor: 'rgba(243,139,168,0.1)',
                color: 'var(--tf-blocked)',
                border: '1px solid rgba(243,139,168,0.2)',
              }}
            >
              刪除
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Main Page ───

const STATUS_OPTIONS: { value: TaskStatus | ''; label: string }[] = [
  { value: '', label: '全部狀態' },
  ...Object.entries(STATUS_CONFIG).map(([k, v]) => ({
    value: k as TaskStatus,
    label: v.label,
  })),
]

const SOURCE_OPTIONS: { value: TaskSource | ''; label: string }[] = [
  { value: '', label: '全部來源' },
  ...Object.entries(SOURCE_CONFIG).map(([k, v]) => ({
    value: k as TaskSource,
    label: `${v.icon} ${v.label}`,
  })),
]

const PRIORITY_OPTIONS: { value: TaskPriority | ''; label: string }[] = [
  { value: '', label: '全部優先級' },
  ...Object.entries(PRIORITY_CONFIG).map(([k, v]) => ({
    value: k as TaskPriority,
    label: v.label,
  })),
]

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingTask, setEditingTask] = useState<Task | null>(null)

  // Filters
  const [filterStatus, setFilterStatus] = useState<TaskStatus | ''>('')
  const [filterSource, setFilterSource] = useState<TaskSource | ''>('')
  const [filterPriority, setFilterPriority] = useState<TaskPriority | ''>('')
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')

  const loadTasks = useCallback(() => {
    setLoading(true)
    taskApi
      .listFiltered({
        page,
        page_size: 20,
        status: filterStatus || undefined,
        source: filterSource || undefined,
        priority: filterPriority || undefined,
        search: search || undefined,
        top_level: true,
      })
      .then((res) => {
        setTasks(res.items)
        setTotal(res.total)
      })
      .catch(() => {
        setTasks([])
        setTotal(0)
      })
      .finally(() => setLoading(false))
  }, [page, filterStatus, filterSource, filterPriority, search])

  useEffect(() => {
    loadTasks()
  }, [loadTasks])

  const handleCreate = async (data: TaskCreate | TaskUpdate) => {
    await taskApi.create(data as TaskCreate)
    setPage(1)
    loadTasks()
  }

  const handleEdit = async (data: TaskCreate | TaskUpdate) => {
    if (!editingTask) return
    await taskApi.update(editingTask.id, data as TaskUpdate)
    loadTasks()
  }

  const handleTransition = async (id: string, status: TaskStatus) => {
    await taskApi.transition(id, status)
    loadTasks()
  }

  const handleDelete = async (id: string) => {
    await taskApi.delete(id)
    loadTasks()
  }

  const handleSearch = () => {
    setSearch(searchInput)
    setPage(1)
  }

  const clearFilters = () => {
    setFilterStatus('')
    setFilterSource('')
    setFilterPriority('')
    setSearch('')
    setSearchInput('')
    setPage(1)
  }

  const hasFilters = filterStatus || filterSource || filterPriority || search

  const totalPages = Math.ceil(total / 20)

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--tf-text)' }}>
          任務列表 <span style={{ color: 'var(--tf-text-muted)' }}>({total})</span>
        </h1>
        <button
          type="button"
          onClick={() => {
            setEditingTask(null)
            setShowModal(true)
          }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[13px] font-medium"
          style={{
            backgroundColor: 'var(--tf-accent-alpha)',
            color: 'var(--tf-accent)',
            border: '1px solid var(--tf-accent-dim)',
          }}
        >
          <Plus size={14} />
          新增
        </button>
      </div>

      {/* Filter bar */}
      <div className="space-y-2">
        {/* Search */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2"
              style={{ color: 'var(--tf-text-muted)' }}
            />
            <input
              type="text"
              placeholder="搜尋任務..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              className="w-full rounded-md border pl-8 pr-3 py-1.5 text-[13px] outline-none focus:border-[color:var(--tf-accent)]"
              style={{
                backgroundColor: 'var(--tf-bg-elevated)',
                borderColor: 'var(--tf-border)',
                color: 'var(--tf-text)',
              }}
            />
          </div>
          <button
            type="button"
            onClick={handleSearch}
            className="px-3 py-1.5 rounded-md text-[13px]"
            style={{
              backgroundColor: 'var(--tf-accent-alpha)',
              color: 'var(--tf-accent)',
              border: '1px solid var(--tf-accent-dim)',
            }}
          >
            搜尋
          </button>
        </div>

        {/* Select filters */}
        <div className="flex gap-2 flex-wrap">
          {[
            {
              value: filterStatus,
              onChange: (v: string) => {
                setFilterStatus(v as TaskStatus | '')
                setPage(1)
              },
              options: STATUS_OPTIONS,
            },
            {
              value: filterSource,
              onChange: (v: string) => {
                setFilterSource(v as TaskSource | '')
                setPage(1)
              },
              options: SOURCE_OPTIONS,
            },
            {
              value: filterPriority,
              onChange: (v: string) => {
                setFilterPriority(v as TaskPriority | '')
                setPage(1)
              },
              options: PRIORITY_OPTIONS,
            },
          ].map((sel, i) => (
            <select
              key={i}
              value={sel.value}
              onChange={(e) => sel.onChange(e.target.value)}
              className="rounded-md border px-2 py-1.5 text-[12px] outline-none"
              style={{
                backgroundColor: 'var(--tf-bg-elevated)',
                borderColor: sel.value ? 'var(--tf-accent-dim)' : 'var(--tf-border)',
                color: sel.value ? 'var(--tf-accent)' : 'var(--tf-text-tertiary)',
              }}
            >
              {sel.options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          ))}

          {hasFilters && (
            <button
              type="button"
              onClick={clearFilters}
              className="flex items-center gap-1 text-[12px] px-2 py-1.5"
              style={{ color: 'var(--tf-text-muted)' }}
            >
              <X size={12} /> 清除
            </button>
          )}
        </div>
      </div>

      {/* Task list */}
      {loading ? (
        <div className="flex justify-center py-16">
          <div
            className="h-7 w-7 animate-spin rounded-full border-2 border-t-transparent"
            style={{ borderColor: 'var(--tf-accent)', borderTopColor: 'transparent' }}
          />
        </div>
      ) : tasks.length === 0 ? (
        <div
          className="rounded-lg border p-12 text-center"
          style={{ borderColor: 'var(--tf-border)' }}
        >
          <AlertCircle
            size={32}
            className="mx-auto mb-3"
            style={{ color: 'var(--tf-text-muted)' }}
          />
          <p className="text-[13px]" style={{ color: 'var(--tf-text-muted)' }}>
            沒有符合條件的任務
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              onTransition={handleTransition}
              onEdit={(t) => {
                setEditingTask(t)
                setShowModal(true)
              }}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="px-3 py-1.5 rounded-md text-[13px] disabled:opacity-40"
            style={{
              backgroundColor: 'var(--tf-bg-elevated)',
              color: 'var(--tf-text-tertiary)',
              border: '1px solid var(--tf-border)',
            }}
          >
            上一頁
          </button>
          <span className="text-[12px]" style={{ color: 'var(--tf-text-muted)' }}>
            {page} / {totalPages}
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className="px-3 py-1.5 rounded-md text-[13px] disabled:opacity-40"
            style={{
              backgroundColor: 'var(--tf-bg-elevated)',
              color: 'var(--tf-text-tertiary)',
              border: '1px solid var(--tf-border)',
            }}
          >
            下一頁
          </button>
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <TaskModal
          initial={editingTask}
          onClose={() => {
            setShowModal(false)
            setEditingTask(null)
          }}
          onSave={editingTask ? handleEdit : handleCreate}
        />
      )}
    </div>
  )
}

// Used only for type narrowing — keep dashboardApi imported
void dashboardApi

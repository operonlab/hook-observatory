import { Calendar, CalendarDays, CalendarPlus, Plus, Repeat, Sun, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useRecurringItems } from '../hooks/useRecurringItems'
import type { RecurringItem, RecurringItemCreate } from '../types'

// ─── Constants ───

const DAY_LABELS = ['一', '二', '三', '四', '五', '六', '日'] as const
const DAY_LABELS_FULL = ['週一', '週二', '週三', '週四', '週五', '週六', '週日'] as const
const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0'))

const RECURRENCE_TYPES = ['daily', 'weekly', 'monthly'] as const
const RECURRENCE_LABELS: Record<string, string> = {
  daily: '每日',
  weekly: '每週',
  monthly: '每月',
}

type RecurrenceType = (typeof RECURRENCE_TYPES)[number]

interface GroupConfig {
  key: RecurrenceType
  label: string
  icon: typeof Sun
}

const GROUPS: GroupConfig[] = [
  { key: 'daily', label: '每日', icon: Sun },
  { key: 'weekly', label: '每週', icon: CalendarDays },
  { key: 'monthly', label: '每月', icon: Calendar },
]

const EMPTY_FORM: RecurringItemCreate = {
  title: '',
  recurrence_type: 'daily',
}

// ─── Helpers ───

function scheduleBadge(item: RecurringItem): string | null {
  if (item.recurrence_type === 'weekly' && item.day_of_week != null) {
    return DAY_LABELS_FULL[item.day_of_week]
  }
  if (item.recurrence_type === 'monthly' && item.day_of_month != null) {
    return `每月${item.day_of_month}日`
  }
  return null
}

function timeRange(start?: string, end?: string): string | null {
  if (!start && !end) return null
  if (start && end) return `${start} - ${end}`
  if (start) return `${start} 起`
  return `至 ${end}`
}

// ─── Toggle Switch ───

function ToggleSwitch({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (val: boolean) => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="relative shrink-0 rounded-full cursor-pointer"
      style={{
        width: 36,
        height: 20,
        backgroundColor: checked ? 'var(--do-accent)' : 'var(--do-bg-surface)',
        border: `1px solid ${checked ? 'var(--do-accent-dim)' : 'var(--do-border)'}`,
        transition: 'background-color 150ms ease, border-color 150ms ease',
      }}
    >
      <span
        className="absolute top-0.5 rounded-full block"
        style={{
          width: 14,
          height: 14,
          backgroundColor: checked ? '#fff' : 'var(--do-text-muted)',
          left: checked ? 18 : 2,
          transition: 'left 150ms ease, background-color 150ms ease',
        }}
      />
    </button>
  )
}

// ─── Item Card ───

function ItemCard({
  item,
  onToggle,
  onRemove,
}: {
  item: RecurringItem
  onToggle: () => void
  onRemove: () => void
}) {
  const badge = scheduleBadge(item)
  const time = timeRange(item.start_time, item.end_time)

  return (
    <div
      className="recurring-item-card group flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-default"
      style={{
        opacity: item.is_active ? 1 : 0.5,
        transition: 'background-color 150ms ease, opacity 150ms ease',
      }}
    >
      {/* Status dot */}
      <span
        className="shrink-0 rounded-full block"
        style={{
          width: 8,
          height: 8,
          backgroundColor: item.is_active ? '#94e2d5' : 'var(--do-text-muted)',
          transition: 'background-color 150ms ease',
        }}
      />

      {/* Title */}
      <span
        className="text-[13px] font-medium min-w-0 truncate"
        style={{
          color: item.is_active ? 'var(--do-text)' : 'var(--do-text-muted)',
          textDecoration: item.is_active ? 'none' : 'line-through',
          transition: 'color 150ms ease',
        }}
      >
        {item.title}
      </span>

      {/* Schedule badge */}
      {badge && (
        <span
          className="shrink-0 text-[11px] px-1.5 py-0.5 rounded-full"
          style={{
            color: 'var(--do-text-secondary)',
            backgroundColor: 'var(--do-bg-surface)',
          }}
        >
          {badge}
        </span>
      )}

      {/* Time range */}
      {time && (
        <span className="shrink-0 text-[11px]" style={{ color: 'var(--do-text-tertiary)' }}>
          {time}
        </span>
      )}

      {/* Category pill */}
      {item.category && (
        <span
          className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full"
          style={{
            color: 'var(--do-accent)',
            backgroundColor: 'var(--do-accent-alpha)',
          }}
        >
          {item.category}
        </span>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Toggle */}
      <ToggleSwitch checked={item.is_active} onChange={onToggle} />

      {/* Delete — visible on hover via CSS group */}
      <button
        type="button"
        onClick={onRemove}
        className="shrink-0 p-1 rounded cursor-pointer opacity-0 group-hover:opacity-100 hover:!text-[#f38ba8]"
        style={{
          color: 'var(--do-text-muted)',
          transition: 'opacity 150ms ease, color 150ms ease',
        }}
        title="刪除"
      >
        <Trash2 size={14} />
      </button>
    </div>
  )
}

// ─── Group Section ───

function GroupSection({
  config,
  items,
  onToggle,
  onRemove,
}: {
  config: GroupConfig
  items: RecurringItem[]
  onToggle: (id: string) => void
  onRemove: (id: string) => void
}) {
  const Icon = config.icon
  return (
    <div className="space-y-1">
      {/* Section header */}
      <div className="flex items-center gap-2 px-1 py-1.5">
        <Icon size={14} style={{ color: 'var(--do-text-tertiary)' }} />
        <span
          className="text-[12px] font-medium uppercase tracking-wide"
          style={{ color: 'var(--do-text-tertiary)' }}
        >
          {config.label}
        </span>
        <span
          className="text-[11px] px-1.5 py-0.5 rounded-full"
          style={{
            color: 'var(--do-text-muted)',
            backgroundColor: 'var(--do-bg-surface)',
          }}
        >
          {items.length}
        </span>
      </div>

      {/* Cards */}
      <div
        className="rounded-lg border"
        style={{
          borderColor: 'var(--do-border)',
          backgroundColor: 'var(--do-bg-elevated)',
        }}
      >
        {items.map((item, idx) => (
          <div key={item.id}>
            {idx > 0 && (
              <div
                className="mx-3"
                style={{
                  height: 1,
                  backgroundColor: 'var(--do-border)',
                  opacity: 0.5,
                }}
              />
            )}
            <ItemCard
              item={item}
              onToggle={() => onToggle(item.id)}
              onRemove={() => onRemove(item.id)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Add Form ───

function AddForm({
  onSave,
  onCancel,
}: {
  onSave: (data: RecurringItemCreate) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<RecurringItemCreate>({ ...EMPTY_FORM })
  const titleRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    titleRef.current?.focus()
  }, [])

  const patch = (partial: Partial<RecurringItemCreate>) =>
    setForm((prev) => ({ ...prev, ...partial }))

  const handleSubmit = () => {
    if (!form.title.trim()) return
    onSave(form)
  }

  const selectStyle: React.CSSProperties = {
    backgroundColor: 'var(--do-bg-surface)',
    color: 'var(--do-text)',
    borderColor: 'var(--do-border)',
    borderWidth: 1,
    borderStyle: 'solid',
    borderRadius: 6,
    padding: '5px 8px',
    fontSize: 13,
    outline: 'none',
    cursor: 'pointer',
    transition: 'border-color 150ms ease',
  }

  return (
    <div
      className="rounded-lg border p-4 space-y-4"
      style={{
        borderColor: 'var(--do-accent-dim)',
        backgroundColor: 'var(--do-bg-elevated)',
        animation: 'slideDown 200ms ease-out',
      }}
    >
      <style>{`
        @keyframes slideDown {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* Title input */}
      <div>
        <input
          ref={titleRef}
          type="text"
          placeholder="行程名稱"
          value={form.title}
          onChange={(e) => patch({ title: e.target.value })}
          className="w-full bg-transparent text-[14px] font-medium pb-2 focus:outline-none"
          style={{
            color: 'var(--do-text)',
            borderBottom: '1px solid var(--do-border)',
            transition: 'border-color 150ms ease',
          }}
          onFocus={(e) => {
            ;(e.target as HTMLInputElement).style.borderBottomColor = 'var(--do-accent)'
          }}
          onBlur={(e) => {
            ;(e.target as HTMLInputElement).style.borderBottomColor = 'var(--do-border)'
          }}
        />
      </div>

      {/* Recurrence type — segment toggle */}
      <div>
        <span
          className="block text-[11px] mb-2 uppercase tracking-wide"
          style={{ color: 'var(--do-text-tertiary)' }}
        >
          {RECURRENCE_LABELS[form.recurrence_type] || '頻率'}
        </span>
        <div
          className="inline-flex rounded-lg overflow-hidden border"
          style={{ borderColor: 'var(--do-border)' }}
        >
          {RECURRENCE_TYPES.map((type) => {
            const active = form.recurrence_type === type
            return (
              <button
                key={type}
                type="button"
                onClick={() =>
                  patch({
                    recurrence_type: type,
                    day_of_week: type === 'weekly' ? (form.day_of_week ?? 6) : undefined,
                    day_of_month: type === 'monthly' ? (form.day_of_month ?? 1) : undefined,
                  })
                }
                className="px-4 py-1.5 text-[12px] font-medium cursor-pointer"
                style={{
                  backgroundColor: active ? 'var(--do-accent-alpha)' : 'transparent',
                  color: active ? 'var(--do-accent)' : 'var(--do-text-tertiary)',
                  borderRight: type !== 'monthly' ? '1px solid var(--do-border)' : 'none',
                  transition: 'background-color 150ms ease, color 150ms ease',
                }}
              >
                {RECURRENCE_LABELS[type]}
              </button>
            )
          })}
        </div>
      </div>

      {/* Day-of-week selector (weekly) */}
      {form.recurrence_type === 'weekly' && (
        <div>
          <span
            className="block text-[11px] mb-2 uppercase tracking-wide"
            style={{ color: 'var(--do-text-tertiary)' }}
          >
            星期
          </span>
          <div className="flex gap-1.5">
            {DAY_LABELS.map((label, idx) => {
              const selected = form.day_of_week === idx
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => patch({ day_of_week: idx })}
                  className="flex items-center justify-center rounded-full text-[12px] font-medium cursor-pointer"
                  style={{
                    width: 28,
                    height: 28,
                    backgroundColor: selected ? 'var(--do-accent)' : 'var(--do-bg-surface)',
                    color: selected ? '#1e1e2e' : 'var(--do-text-secondary)',
                    transition:
                      'background-color 150ms ease, color 150ms ease, transform 150ms ease',
                    transform: selected ? 'scale(1.1)' : 'scale(1)',
                  }}
                >
                  {label}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Day-of-month selector (monthly) */}
      {form.recurrence_type === 'monthly' && (
        <div>
          <span
            className="block text-[11px] mb-2 uppercase tracking-wide"
            style={{ color: 'var(--do-text-tertiary)' }}
          >
            日期
          </span>
          <select
            value={form.day_of_month ?? 1}
            onChange={(e) => patch({ day_of_month: Number(e.target.value) })}
            style={selectStyle}
          >
            {Array.from({ length: 31 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {i + 1}日
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Time range */}
      <div>
        <span
          className="block text-[11px] mb-2 uppercase tracking-wide"
          style={{ color: 'var(--do-text-tertiary)' }}
        >
          時間
        </span>
        <div className="flex items-center gap-2">
          {/* Start hour */}
          <select
            value={form.start_time?.slice(0, 2) || ''}
            onChange={(e) => {
              const m = form.start_time?.slice(3, 5) || '00'
              patch({ start_time: e.target.value ? `${e.target.value}:${m}` : undefined })
            }}
            style={selectStyle}
          >
            <option value="">--</option>
            {HOURS.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
          <span className="text-[13px]" style={{ color: 'var(--do-text-muted)' }}>
            :
          </span>
          {/* Start minute */}
          <select
            value={form.start_time?.slice(3, 5) || ''}
            onChange={(e) => {
              const h = form.start_time?.slice(0, 2) || '00'
              patch({ start_time: `${h}:${e.target.value || '00'}` })
            }}
            style={selectStyle}
          >
            <option value="">--</option>
            {MINUTES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>

          <span className="text-[13px] mx-1 font-light" style={{ color: 'var(--do-text-muted)' }}>
            &mdash;
          </span>

          {/* End hour */}
          <select
            value={form.end_time?.slice(0, 2) || ''}
            onChange={(e) => {
              const m = form.end_time?.slice(3, 5) || '00'
              patch({ end_time: e.target.value ? `${e.target.value}:${m}` : undefined })
            }}
            style={selectStyle}
          >
            <option value="">--</option>
            {HOURS.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
          <span className="text-[13px]" style={{ color: 'var(--do-text-muted)' }}>
            :
          </span>
          {/* End minute */}
          <select
            value={form.end_time?.slice(3, 5) || ''}
            onChange={(e) => {
              const h = form.end_time?.slice(0, 2) || '00'
              patch({ end_time: `${h}:${e.target.value || '00'}` })
            }}
            style={selectStyle}
          >
            <option value="">--</option>
            {MINUTES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Action row */}
      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="text-[13px] px-4 py-2 rounded-lg cursor-pointer"
          style={{
            color: 'var(--do-text-secondary)',
            backgroundColor: 'transparent',
            transition: 'background-color 150ms ease',
          }}
          onMouseEnter={(e) => {
            ;(e.currentTarget as HTMLElement).style.backgroundColor = 'var(--do-bg-surface)'
          }}
          onMouseLeave={(e) => {
            ;(e.currentTarget as HTMLElement).style.backgroundColor = 'transparent'
          }}
        >
          取消
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!form.title.trim()}
          className="text-[13px] px-4 py-2 rounded-lg font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            color: '#1e1e2e',
            backgroundColor: 'var(--do-accent)',
            transition: 'opacity 150ms ease, transform 150ms ease',
          }}
        >
          新增
        </button>
      </div>
    </div>
  )
}

// ─── Main Component ───

export default function RecurringItemsManager() {
  const { items, loading, add, update, remove } = useRecurringItems()
  const [showForm, setShowForm] = useState(false)

  const grouped = useMemo(() => {
    const map: Record<RecurrenceType, RecurringItem[]> = {
      daily: [],
      weekly: [],
      monthly: [],
    }
    for (const item of items) {
      const key = item.recurrence_type as RecurrenceType
      if (map[key]) map[key].push(item)
    }
    return map
  }, [items])

  const handleToggle = (id: string) => {
    const item = items.find((i) => i.id === id)
    if (item) update(id, { is_active: !item.is_active })
  }

  const handleRemove = (id: string) => {
    remove(id)
  }

  const handleAdd = async (data: RecurringItemCreate) => {
    await add(data)
    setShowForm(false)
  }

  const populatedGroups = GROUPS.filter((g) => grouped[g.key].length > 0)
  const hasItems = items.length > 0

  // ── Loading ──
  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <div
          className="h-7 w-7 animate-spin rounded-full border-2 border-t-transparent"
          style={{
            borderColor: 'var(--do-accent)',
            borderTopColor: 'transparent',
          }}
        />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <style>{`
        .recurring-item-card:hover {
          background-color: var(--do-bg-elevated);
        }
      `}</style>

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Repeat size={16} style={{ color: 'var(--do-accent)' }} />
          <h1 className="text-[16px] font-semibold" style={{ color: 'var(--do-text)' }}>
            固定行程
          </h1>
          {hasItems && (
            <span
              className="text-[11px] px-2 py-0.5 rounded-full font-medium"
              style={{
                color: 'var(--do-accent)',
                backgroundColor: 'var(--do-accent-alpha)',
              }}
            >
              {items.length}
            </span>
          )}
        </div>

        {!showForm && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium cursor-pointer"
            style={{
              color: 'var(--do-accent)',
              backgroundColor: 'var(--do-accent-alpha)',
              border: '1px solid var(--do-accent-dim)',
              transition: 'background-color 150ms ease, transform 150ms ease',
            }}
            onMouseEnter={(e) => {
              ;(e.currentTarget as HTMLElement).style.backgroundColor = 'rgba(203, 166, 247, 0.25)'
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLElement).style.backgroundColor = 'var(--do-accent-alpha)'
            }}
          >
            <Plus size={14} />
            新增行程
          </button>
        )}
      </div>

      {/* ── Empty state ── */}
      {!hasItems && !showForm && (
        <div
          className="rounded-lg border p-10 flex flex-col items-center gap-3"
          style={{
            borderColor: 'var(--do-border)',
            backgroundColor: 'var(--do-bg-elevated)',
          }}
        >
          <CalendarPlus size={40} strokeWidth={1.2} style={{ color: 'var(--do-text-muted)' }} />
          <p className="text-[14px] font-medium" style={{ color: 'var(--do-text-secondary)' }}>
            尚未設定固定行程
          </p>
          <p className="text-[12px] text-center max-w-xs" style={{ color: 'var(--do-text-muted)' }}>
            新增每日、每週或每月的固定行程，自動加入計畫
          </p>
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 px-4 py-2 mt-2 rounded-lg text-[13px] font-medium cursor-pointer"
            style={{
              color: '#1e1e2e',
              backgroundColor: 'var(--do-accent)',
              transition: 'opacity 150ms ease',
            }}
          >
            <Plus size={14} />
            新增固定行程
          </button>
        </div>
      )}

      {/* ── Grouped items ── */}
      {populatedGroups.map((group) => (
        <GroupSection
          key={group.key}
          config={group}
          items={grouped[group.key]}
          onToggle={handleToggle}
          onRemove={handleRemove}
        />
      ))}

      {/* ── Add form ── */}
      {showForm && <AddForm onSave={handleAdd} onCancel={() => setShowForm(false)} />}
    </div>
  )
}

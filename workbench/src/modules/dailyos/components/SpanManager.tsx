import { CalendarRange, Plus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { fmtDateRange } from '../../../shared/utils/formatting'
import { useMethodStore } from '../stores/methodStore'
import type { ActivitySpan, ActivitySpanCreate } from '../types'

// ─── Constants ───

const PRESET_COLORS = ['#89b4fa', '#a6e3a1', '#f9e2af', '#f38ba8', '#cba6f7', '#fab387']

const EMPTY_FORM: ActivitySpanCreate = {
  title: '',
  start_date: '',
  end_date: '',
  category: '',
  color: PRESET_COLORS[0],
  notes: '',
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

// ─── Span Card ───

function SpanCard({
  span,
  onToggle,
  onRemove,
}: {
  span: ActivitySpan
  onToggle: () => void
  onRemove: () => void
}) {
  return (
    <div
      className="span-item-card group flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-default"
      style={{
        opacity: span.is_active ? 1 : 0.5,
        transition: 'background-color 150ms ease, opacity 150ms ease',
      }}
    >
      {/* Color dot */}
      <span
        className="shrink-0 rounded-full block"
        style={{
          width: 10,
          height: 10,
          backgroundColor: span.color,
          boxShadow: `0 0 0 2px ${span.color}33`,
        }}
      />

      {/* Title */}
      <span
        className="text-[13px] font-medium min-w-0 truncate"
        style={{
          color: span.is_active ? 'var(--do-text)' : 'var(--do-text-muted)',
          textDecoration: span.is_active ? 'none' : 'line-through',
          transition: 'color 150ms ease',
        }}
      >
        {span.title}
      </span>

      {/* Date range */}
      <span
        className="shrink-0 text-[11px] px-1.5 py-0.5 rounded-full tabular-nums"
        style={{
          color: 'var(--do-text-secondary)',
          backgroundColor: 'var(--do-bg-surface)',
        }}
      >
        {fmtDateRange(span.start_date, span.end_date)}
      </span>

      {/* Category badge */}
      {span.category && (
        <span
          className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full"
          style={{
            color: 'var(--do-accent)',
            backgroundColor: 'var(--do-accent-alpha)',
          }}
        >
          {span.category}
        </span>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Toggle */}
      <ToggleSwitch checked={span.is_active} onChange={onToggle} />

      {/* Delete — visible on hover */}
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

// ─── Add Form ───

function AddForm({
  onSave,
  onCancel,
}: {
  onSave: (data: ActivitySpanCreate) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<ActivitySpanCreate>({ ...EMPTY_FORM })
  const titleRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    titleRef.current?.focus()
  }, [])

  const patch = (partial: Partial<ActivitySpanCreate>) =>
    setForm((prev) => ({ ...prev, ...partial }))

  const handleSubmit = () => {
    if (!form.title.trim() || !form.start_date || !form.end_date) return
    onSave({
      ...form,
      category: form.category?.trim() || undefined,
      notes: form.notes?.trim() || undefined,
    })
  }

  const inputStyle: React.CSSProperties = {
    backgroundColor: 'var(--do-bg-surface)',
    color: 'var(--do-text)',
    borderColor: 'var(--do-border)',
    borderWidth: 1,
    borderStyle: 'solid',
    borderRadius: 6,
    padding: '5px 8px',
    fontSize: 13,
    outline: 'none',
    width: '100%',
    transition: 'border-color 150ms ease',
  }

  const isValid = form.title.trim() && form.start_date && form.end_date

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

      {/* Title */}
      <div>
        <input
          ref={titleRef}
          type="text"
          placeholder="活動名稱"
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

      {/* Date range */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <span
            className="block text-[11px] mb-1.5 uppercase tracking-wide"
            style={{ color: 'var(--do-text-tertiary)' }}
          >
            開始日期
          </span>
          <input
            type="date"
            value={form.start_date}
            onChange={(e) => patch({ start_date: e.target.value })}
            style={inputStyle}
          />
        </div>
        <div>
          <span
            className="block text-[11px] mb-1.5 uppercase tracking-wide"
            style={{ color: 'var(--do-text-tertiary)' }}
          >
            結束日期
          </span>
          <input
            type="date"
            value={form.end_date}
            min={form.start_date || undefined}
            onChange={(e) => patch({ end_date: e.target.value })}
            style={inputStyle}
          />
        </div>
      </div>

      {/* Color picker */}
      <div>
        <span
          className="block text-[11px] mb-2 uppercase tracking-wide"
          style={{ color: 'var(--do-text-tertiary)' }}
        >
          顏色
        </span>
        <div className="flex gap-2">
          {PRESET_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => patch({ color: c })}
              className="rounded-full cursor-pointer"
              style={{
                width: 22,
                height: 22,
                backgroundColor: c,
                border: form.color === c ? `2px solid #fff` : '2px solid transparent',
                boxShadow: form.color === c ? `0 0 0 2px ${c}` : 'none',
                transition: 'box-shadow 150ms ease, border-color 150ms ease',
              }}
              title={c}
            />
          ))}
        </div>
      </div>

      {/* Category */}
      <div>
        <span
          className="block text-[11px] mb-1.5 uppercase tracking-wide"
          style={{ color: 'var(--do-text-tertiary)' }}
        >
          分類（選填）
        </span>
        <input
          type="text"
          placeholder="例：旅行、學習..."
          value={form.category ?? ''}
          onChange={(e) => patch({ category: e.target.value })}
          style={inputStyle}
        />
      </div>

      {/* Notes */}
      <div>
        <span
          className="block text-[11px] mb-1.5 uppercase tracking-wide"
          style={{ color: 'var(--do-text-tertiary)' }}
        >
          備註（選填）
        </span>
        <textarea
          placeholder="活動說明或備注..."
          value={form.notes ?? ''}
          onChange={(e) => patch({ notes: e.target.value })}
          rows={2}
          className="resize-y focus:outline-none"
          style={{
            ...inputStyle,
            padding: '6px 8px',
          }}
        />
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
          disabled={!isValid}
          className="text-[13px] px-4 py-2 rounded-lg font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            color: '#1e1e2e',
            backgroundColor: 'var(--do-accent)',
            transition: 'opacity 150ms ease',
          }}
        >
          新增
        </button>
      </div>
    </div>
  )
}

// ─── Main Component ───

export default function SpanManager() {
  const {
    activitySpans,
    spansLoading,
    fetchActivitySpans,
    addActivitySpan,
    updateActivitySpan,
    removeActivitySpan,
  } = useMethodStore()
  const [showForm, setShowForm] = useState(false)

  useEffect(() => {
    fetchActivitySpans()
  }, [fetchActivitySpans])

  const sorted = [...activitySpans].sort((a, b) => a.start_date.localeCompare(b.start_date))
  const hasItems = sorted.length > 0

  const handleToggle = (span: ActivitySpan) => {
    updateActivitySpan(span.id, { is_active: !span.is_active })
  }

  const handleRemove = (id: string) => {
    removeActivitySpan(id)
  }

  const handleAdd = async (data: ActivitySpanCreate) => {
    await addActivitySpan(data)
    setShowForm(false)
  }

  if (spansLoading) {
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
        .span-item-card:hover {
          background-color: var(--do-bg-elevated);
        }
      `}</style>

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <CalendarRange size={16} style={{ color: 'var(--do-accent)' }} />
          <h1 className="text-[16px] font-semibold" style={{ color: 'var(--do-text)' }}>
            多日活動
          </h1>
          {hasItems && (
            <span
              className="text-[11px] px-2 py-0.5 rounded-full font-medium"
              style={{
                color: 'var(--do-accent)',
                backgroundColor: 'var(--do-accent-alpha)',
              }}
            >
              {sorted.length}
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
              transition: 'background-color 150ms ease',
            }}
            onMouseEnter={(e) => {
              ;(e.currentTarget as HTMLElement).style.backgroundColor = 'rgba(203, 166, 247, 0.25)'
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLElement).style.backgroundColor = 'var(--do-accent-alpha)'
            }}
          >
            <Plus size={14} />
            新增活動
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
          <CalendarRange size={40} strokeWidth={1.2} style={{ color: 'var(--do-text-muted)' }} />
          <p className="text-[14px] font-medium" style={{ color: 'var(--do-text-secondary)' }}>
            尚未建立多日活動
          </p>
          <p className="text-[12px] text-center max-w-xs" style={{ color: 'var(--do-text-muted)' }}>
            建立跨越多天的活動（旅行、課程、計畫），讓日曆和規劃頁顯示進行中的活動
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
            新增多日活動
          </button>
        </div>
      )}

      {/* ── Items list ── */}
      {hasItems && (
        <div
          className="rounded-lg border"
          style={{
            borderColor: 'var(--do-border)',
            backgroundColor: 'var(--do-bg-elevated)',
          }}
        >
          {sorted.map((span, idx) => (
            <div key={span.id}>
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
              <SpanCard
                span={span}
                onToggle={() => handleToggle(span)}
                onRemove={() => handleRemove(span.id)}
              />
            </div>
          ))}
        </div>
      )}

      {/* ── Add form ── */}
      {showForm && <AddForm onSave={handleAdd} onCancel={() => setShowForm(false)} />}
    </div>
  )
}

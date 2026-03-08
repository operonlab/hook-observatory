import { AlertTriangle, ArrowUpRight, ChevronDown, ChevronUp, Clock, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type { Capture, CapturePromoteResult } from '../api'

const MODULE_COLORS: Record<string, string> = {
  finance: '#a6e3a1',
  taskflow: '#cba6f7',
  invest: '#f38ba8',
  ideagraph: '#f9e2af',
  intelflow: '#94e2d5',
}

const MODULE_LABELS: Record<string, string> = {
  finance: 'FIN',
  taskflow: 'TASK',
  invest: 'INV',
  ideagraph: 'IDEA',
  intelflow: 'INTEL',
}

interface CaptureListProps {
  captures: Capture[]
  selectedId: string | null
  onSelect: (id: string | null) => void
  onPromote: (id: string) => Promise<CapturePromoteResult>
  onDelete: (id: string) => Promise<void>
  onUpdate: (id: string, payload: Record<string, unknown>) => Promise<void>
}

function CompletionBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 90 ? 'var(--green)' : pct >= 60 ? 'var(--yellow)' : 'var(--red)'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 rounded-full" style={{ backgroundColor: 'var(--surface0)' }}>
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-[10px] tabular-nums w-7 text-right" style={{ color }}>
        {pct}%
      </span>
    </div>
  )
}

function InlineFieldEditor({
  capture,
  onSave,
  onClose,
}: {
  capture: Capture
  onSave: (payload: Record<string, unknown>) => void
  onClose: () => void
}) {
  const [fields, setFields] = useState<Record<string, string>>({})
  const missing = capture.missing_fields || []

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const payload: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(fields)) {
      if (v.trim()) payload[k] = v.trim()
    }
    if (Object.keys(payload).length > 0) onSave(payload)
  }

  return (
    <div
      className="mt-2 p-3 rounded-md border"
      style={{ backgroundColor: 'var(--base)', borderColor: 'var(--surface1)' }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-medium" style={{ color: 'var(--subtext0)' }}>
          Fill missing fields
        </span>
        <button type="button" onClick={onClose} className="hover:opacity-70">
          <X size={12} style={{ color: 'var(--overlay0)' }} />
        </button>
      </div>
      <form onSubmit={handleSubmit} className="space-y-2">
        {missing.map((field) => (
          <label key={field} className="flex items-center gap-2">
            <span className="text-[11px] w-28 shrink-0" style={{ color: 'var(--subtext1)' }}>
              {field}
            </span>
            <input
              type="text"
              value={fields[field] || ''}
              onChange={(e) => setFields((p) => ({ ...p, [field]: e.target.value }))}
              className="flex-1 text-xs px-2 py-1 rounded border bg-transparent outline-none focus:ring-1"
              style={{ borderColor: 'var(--surface1)', color: 'var(--text)' }}
              placeholder={field}
            />
          </label>
        ))}
        <button
          type="submit"
          className="text-[11px] px-3 py-1 rounded font-medium"
          style={{ backgroundColor: 'var(--blue)', color: 'var(--base)' }}
        >
          Save
        </button>
      </form>
    </div>
  )
}

function CaptureDetail({
  capture,
  isExpanded,
  editingId,
  onToggleExpand: toggleExpand,
  onSetEditing: setEditing,
  onUpdate,
}: {
  capture: Capture
  isExpanded: boolean
  editingId: string | null
  onToggleExpand: () => void
  onSetEditing: (id: string | null) => void
  onUpdate: (id: string, payload: Record<string, unknown>) => Promise<void>
}) {
  const hasMissing = capture.status === 'pending' && capture.missing_fields.length > 0

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          toggleExpand()
        }}
        className="flex items-center gap-1 text-[10px]"
        style={{ color: 'var(--overlay1)' }}
      >
        {isExpanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
        {isExpanded ? 'Hide' : 'Details'}
      </button>

      {isExpanded && (
        <div className="mt-2 space-y-1">
          {Object.entries(capture.payload).map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 text-[11px]">
              <span style={{ color: 'var(--overlay0)' }} className="w-28 shrink-0">
                {k}
              </span>
              <span style={{ color: 'var(--text)' }}>
                {typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')}
              </span>
            </div>
          ))}
          {capture.missing_fields.length > 0 && (
            <div className="flex items-center gap-2 text-[11px]">
              <span style={{ color: 'var(--overlay0)' }} className="w-28 shrink-0">
                missing
              </span>
              <span style={{ color: 'var(--yellow)' }}>{capture.missing_fields.join(', ')}</span>
            </div>
          )}
        </div>
      )}

      {hasMissing &&
        (editingId === capture.id ? (
          <InlineFieldEditor
            capture={capture}
            onSave={(payload) => {
              onUpdate(capture.id, payload)
              setEditing(null)
            }}
            onClose={() => setEditing(null)}
          />
        ) : (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setEditing(capture.id)
            }}
            className="mt-2 text-[11px] px-2 py-1 rounded border"
            style={{ borderColor: 'var(--surface1)', color: 'var(--blue)' }}
          >
            Fill {capture.missing_fields.length} field
            {capture.missing_fields.length > 1 ? 's' : ''}
          </button>
        ))}
    </div>
  )
}

function desc(c: Capture): string {
  const p = c.payload
  const d = (p.description as string) || (p.title as string) || c.raw_input || ''
  const amt = p.amount != null ? ` $${Number(p.amount).toLocaleString()}` : ''
  return `${d}${amt}`.trim() || c.entity_type
}

function timeAgo(iso: string): string {
  const d = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(d / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

function isExpiringSoon(c: Capture): boolean {
  return !!(c.expires_at && new Date(c.expires_at).getTime() - Date.now() < 3 * 24 * 60 * 60 * 1000)
}

function CaptureRow({
  capture,
  isSelected,
  isExpanded,
  editingId,
  promotingId,
  onSelect,
  onPromote,
  onDelete,
  onToggleExpand,
  onSetEditing,
  onUpdate,
}: {
  capture: Capture
  isSelected: boolean
  isExpanded: boolean
  editingId: string | null
  promotingId: string | null
  onSelect: () => void
  onPromote: () => void
  onDelete: () => void
  onToggleExpand: () => void
  onSetEditing: (id: string | null) => void
  onUpdate: (id: string, payload: Record<string, unknown>) => Promise<void>
}) {
  const moduleColor = MODULE_COLORS[capture.module] || 'var(--overlay0)'
  const expiring = isExpiringSoon(capture)

  return (
    <button
      type="button"
      className="w-full text-left px-3 py-2.5 cursor-pointer transition-colors"
      style={{
        backgroundColor: isSelected ? 'var(--surface0)' : 'transparent',
        borderColor: 'var(--surface0)',
      }}
      onClick={onSelect}
    >
      <div className="flex items-start gap-2">
        <span
          className="text-[9px] font-bold px-1.5 py-0.5 rounded shrink-0 mt-0.5"
          style={{ backgroundColor: `${moduleColor}22`, color: moduleColor }}
        >
          {MODULE_LABELS[capture.module] || capture.module.toUpperCase().slice(0, 4)}
        </span>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1">
            <span className="text-[13px] truncate" style={{ color: 'var(--text)' }}>
              {desc(capture)}
            </span>
            {expiring && <AlertTriangle size={11} style={{ color: 'var(--red)' }} />}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <div className="flex-1">
              <CompletionBar value={capture.completeness} />
            </div>
            <span
              className="text-[10px] flex items-center gap-0.5 shrink-0"
              style={{ color: 'var(--overlay0)' }}
            >
              <Clock size={9} />
              {timeAgo(capture.created_at)}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-0.5 shrink-0">
          {capture.status === 'pending' && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onPromote()
              }}
              disabled={promotingId === capture.id}
              className="p-1 rounded hover:opacity-80 transition-opacity"
              style={{ color: 'var(--green)' }}
              title="Promote"
            >
              <ArrowUpRight size={14} />
            </button>
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
            className="p-1 rounded hover:opacity-80 transition-opacity"
            style={{ color: 'var(--red)' }}
            title="Delete"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {isSelected && (
        <CaptureDetail
          capture={capture}
          isExpanded={isExpanded}
          editingId={editingId}
          onToggleExpand={onToggleExpand}
          onSetEditing={onSetEditing}
          onUpdate={onUpdate}
        />
      )}
    </button>
  )
}

export default function CaptureList({
  captures,
  selectedId,
  onSelect,
  onPromote,
  onDelete,
  onUpdate,
}: CaptureListProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [promotingId, setPromotingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handlePromote = async (id: string) => {
    setPromotingId(id)
    setError(null)
    try {
      const result = await onPromote(id)
      if (!result.success) {
        setError(result.error || `Missing: ${result.missing_fields.join(', ')}`)
      }
    } catch {
      setError('Promote failed')
    } finally {
      setPromotingId(null)
    }
  }

  if (captures.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--overlay0)' }}>
        <div className="text-center">
          <div className="text-2xl mb-2">📭</div>
          <div className="text-sm">No captures found</div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      {error && (
        <div
          className="mx-3 mt-2 px-3 py-2 text-xs rounded-md"
          style={{ backgroundColor: 'var(--red)', color: 'var(--base)' }}
        >
          {error}
          <button type="button" onClick={() => setError(null)} className="ml-2 font-bold">
            x
          </button>
        </div>
      )}

      <div className="divide-y" style={{ borderColor: 'var(--surface0)' }}>
        {captures.map((c) => (
          <CaptureRow
            key={c.id}
            capture={c}
            isSelected={selectedId === c.id}
            isExpanded={expandedId === c.id}
            editingId={editingId}
            promotingId={promotingId}
            onSelect={() => onSelect(selectedId === c.id ? null : c.id)}
            onPromote={() => handlePromote(c.id)}
            onDelete={() => onDelete(c.id)}
            onToggleExpand={() => setExpandedId(expandedId === c.id ? null : c.id)}
            onSetEditing={setEditingId}
            onUpdate={onUpdate}
          />
        ))}
      </div>
    </div>
  )
}

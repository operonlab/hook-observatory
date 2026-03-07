import { AlertCircle, ArrowUpRight, Clock, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { type Capture, type CapturePromoteResult, captureApi } from './api'

interface CaptureInboxProps {
  module: string
  entityType?: string
  onPromoted?: () => void
}

function CompletionBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 90 ? '#22c55e' : pct >= 60 ? '#f59e0b' : '#ef4444'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-gray-700">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-[10px] tabular-nums" style={{ color }}>
        {pct}%
      </span>
    </div>
  )
}

function FieldEditor({
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
    <div className="mt-2 p-2 rounded border bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-medium">Fill missing fields</span>
        <button type="button" onClick={onClose} className="p-0.5 hover:opacity-70">
          <X size={12} />
        </button>
      </div>
      <form onSubmit={handleSubmit} className="space-y-1.5">
        {missing.map((field) => (
          <label key={field} className="flex items-center gap-2">
            <span className="text-[11px] w-24 text-gray-500 shrink-0">{field}</span>
            <input
              type="text"
              value={fields[field] || ''}
              onChange={(e) => setFields((p) => ({ ...p, [field]: e.target.value }))}
              className="flex-1 text-xs px-2 py-1 rounded border bg-transparent border-gray-300 dark:border-gray-600"
              placeholder={`Enter ${field}`}
            />
          </label>
        ))}
        <button
          type="submit"
          className="text-[11px] px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-700"
        >
          Save
        </button>
      </form>
    </div>
  )
}

export default function CaptureInbox({ module, entityType, onPromoted }: CaptureInboxProps) {
  const [captures, setCaptures] = useState<Capture[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [promoting, setPromoting] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    captureApi
      .list({ module, entity_type: entityType, status: 'pending', limit: 50 })
      .then(setCaptures)
      .catch(() => {})
  }, [module, entityType])

  useEffect(() => {
    load()
  }, [load])

  if (captures.length === 0) return null

  const handlePromote = async (id: string) => {
    setPromoting(id)
    setError(null)
    try {
      const result: CapturePromoteResult = await captureApi.promote(id)
      if (result.success) {
        load()
        onPromoted?.()
      } else {
        setError(result.error || `Missing: ${result.missing_fields.join(', ')}`)
      }
    } catch {
      setError('Promote failed')
    } finally {
      setPromoting(null)
    }
  }

  const handleUpdate = async (id: string, payload: Record<string, unknown>) => {
    try {
      await captureApi.update(id, { payload })
      setEditing(null)
      load()
    } catch {
      setError('Update failed')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await captureApi.delete(id)
      load()
    } catch {
      setError('Delete failed')
    }
  }

  const desc = (c: Capture) => {
    const p = c.payload
    const d = (p.description as string) || c.raw_input || ''
    const amt = p.amount != null ? ` $${Number(p.amount).toLocaleString()}` : ''
    return `${d}${amt}`.trim() || c.entity_type
  }

  const timeAgo = (iso: string) => {
    const d = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(d / 60000)
    if (mins < 60) return `${mins}m`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h`
    return `${Math.floor(hrs / 24)}d`
  }

  return (
    <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/20 p-3">
      <div className="flex items-center gap-1.5 mb-2">
        <AlertCircle size={14} className="text-amber-500" />
        <span className="text-xs font-medium text-amber-700 dark:text-amber-400">
          Captures ({captures.length})
        </span>
      </div>

      {error && <div className="text-[11px] text-red-500 mb-2 px-1">{error}</div>}

      <div className="space-y-1.5">
        {captures.map((c) => (
          <div key={c.id}>
            <div className="flex items-center gap-2 group">
              <div className="flex-1 min-w-0">
                <div className="text-xs truncate">{desc(c)}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <CompletionBar value={c.completeness} />
                  <span className="text-[10px] text-gray-400 flex items-center gap-0.5">
                    <Clock size={9} />
                    {timeAgo(c.created_at)}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                {c.missing_fields.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setEditing(editing === c.id ? null : c.id)}
                    className="text-[10px] px-1.5 py-0.5 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700"
                    title="Fill fields"
                  >
                    Fill
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handlePromote(c.id)}
                  disabled={promoting === c.id}
                  className="p-1 rounded hover:bg-green-100 dark:hover:bg-green-900 text-green-600"
                  title="Promote"
                >
                  <ArrowUpRight size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(c.id)}
                  className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900 text-red-400"
                  title="Delete"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
            {editing === c.id && (
              <FieldEditor
                capture={c}
                onSave={(payload) => handleUpdate(c.id, payload)}
                onClose={() => setEditing(null)}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

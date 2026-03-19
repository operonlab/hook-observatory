import {
  AlertCircle,
  AlertTriangle,
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  Clock,
  Trash2,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { type Capture, type CapturePromoteResult, captureApi } from './api'
import { timeAgo } from '../../shared/utils/time'

interface CaptureInboxProps {
  module: string
  entityType?: string
  onPromoted?: () => void
}

const FIELD_LABELS: Record<string, string> = {
  wallet_id: '錢包',
  category_id: '分類',
  payment_method: '付款方式',
  amount: '金額',
  type: '類型',
  description: '描述',
  transacted_at: '交易時間',
  name: '名稱',
  billing_cycle: '帳單週期',
  start_date: '開始日期',
  account_id: '帳戶',
}

const STATIC_OPTIONS: Record<string, { id: string; name: string }[]> = {
  payment_method: [
    { id: 'credit_card', name: '信用卡' },
    { id: 'cash', name: '現金' },
    { id: 'debit_card', name: '金融卡' },
    { id: 'bank_transfer', name: '銀行轉帳' },
    { id: 'e_wallet', name: '電子錢包' },
  ],
  type: [
    { id: 'expense', name: '支出' },
    { id: 'income', name: '收入' },
    { id: 'transfer', name: '轉帳' },
  ],
  billing_cycle: [
    { id: 'monthly', name: '每月' },
    { id: 'yearly', name: '每年' },
    { id: 'weekly', name: '每週' },
  ],
}

function CompletionBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 90 ? 'var(--green)' : pct >= 60 ? 'var(--yellow)' : 'var(--red)'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full" style={{ backgroundColor: 'var(--surface0)' }}>
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-[10px] tabular-nums font-medium" style={{ color }}>
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
  const [refOptions, setRefOptions] = useState<Record<string, { id: string; name: string }[]>>({})
  const missing = capture.missing_fields || []

  useEffect(() => {
    captureApi
      .fillOptions(capture.module, capture.entity_type)
      .then(setRefOptions)
      .catch(() => {})
  }, [capture.module, capture.entity_type])

  const getOptions = (field: string) => refOptions[field] || STATIC_OPTIONS[field] || null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const payload: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(fields)) {
      if (v.trim()) payload[k] = v.trim()
    }
    if (Object.keys(payload).length > 0) onSave(payload)
  }

  const inputStyle = { borderColor: 'var(--surface1)', color: 'var(--text)' }

  return (
    <div
      className="mt-2 p-2.5 rounded-md border"
      style={{ backgroundColor: 'var(--mantle)', borderColor: 'var(--surface0)' }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-medium" style={{ color: 'var(--subtext0)' }}>
          補充缺漏欄位
        </span>
        <button type="button" onClick={onClose} className="p-0.5 hover:opacity-70">
          <X size={12} style={{ color: 'var(--overlay0)' }} />
        </button>
      </div>
      <form onSubmit={handleSubmit} className="space-y-1.5">
        {missing.map((field) => {
          const options = getOptions(field)
          const label = FIELD_LABELS[field] || field
          return (
            <label key={field} className="flex items-center gap-2">
              <span className="text-[11px] w-24 shrink-0" style={{ color: 'var(--subtext1)' }}>
                {label}
              </span>
              {options ? (
                <select
                  value={fields[field] || ''}
                  onChange={(e) => setFields((p) => ({ ...p, [field]: e.target.value }))}
                  className="flex-1 text-xs px-2 py-1 rounded border bg-transparent outline-none focus:ring-1"
                  style={inputStyle}
                >
                  <option value="">選擇{label}</option>
                  {options.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.name}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={fields[field] || ''}
                  onChange={(e) => setFields((p) => ({ ...p, [field]: e.target.value }))}
                  className="flex-1 text-xs px-2 py-1 rounded border bg-transparent outline-none focus:ring-1"
                  style={inputStyle}
                  placeholder={label}
                />
              )}
            </label>
          )
        })}
        <button
          type="submit"
          className="text-[11px] px-3 py-1 rounded font-medium"
          style={{ backgroundColor: 'var(--blue)', color: 'var(--base)' }}
        >
          儲存
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
  const [collapsed, setCollapsed] = useState(true)

  const load = useCallback(() => {
    captureApi
      .list({ module, entity_type: entityType, status: 'pending', limit: 50 })
      .then((data) => {
        setCaptures(data)
        setCollapsed((prev) => (data.length <= 3 ? false : prev))
      })
      .catch(() => {})
  }, [module, entityType])

  useEffect(() => {
    load()
  }, [load])

  if (captures.length === 0) return null

  const avgCompleteness =
    captures.length > 0
      ? Math.round((captures.reduce((s, c) => s + c.completeness, 0) / captures.length) * 100)
      : 0

  const now = Date.now()
  const expiringSoon = captures.filter(
    (c) => c.expires_at && new Date(c.expires_at).getTime() - now < 3 * 24 * 60 * 60 * 1000,
  )

  const handlePromote = async (id: string) => {
    setPromoting(id)
    setError(null)
    try {
      const result: CapturePromoteResult = await captureApi.promote(id)
      if (result.success) {
        load()
        onPromoted?.()
      } else {
        setError(result.error || `缺少：${result.missing_fields.join(', ')}`)
      }
    } catch {
      setError('提升失敗')
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
      setError('更新失敗')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await captureApi.delete(id)
      load()
    } catch {
      setError('刪除失敗')
    }
  }

  const desc = (c: Capture) => {
    const p = c.payload
    const d = (p.description as string) || c.raw_input || ''
    const amt = p.amount != null ? ` $${Number(p.amount).toLocaleString()}` : ''
    return `${d}${amt}`.trim() || c.entity_type
  }


  return (
    <div
      className="rounded-lg border p-3"
      style={{
        backgroundColor: 'var(--surface0)',
        borderColor: 'var(--surface1)',
      }}
    >
      {/* Header */}
      <button
        type="button"
        className="w-full flex items-center gap-1.5 mb-2 text-left"
        onClick={() => setCollapsed((v) => !v)}
      >
        <AlertCircle size={14} style={{ color: 'var(--yellow)' }} className="shrink-0" />
        <span className="text-xs font-medium" style={{ color: 'var(--yellow)' }}>
          Captures ({captures.length})
        </span>
        {expiringSoon.length > 0 && (
          <span
            className="flex items-center gap-0.5 text-[10px] font-medium"
            style={{ color: 'var(--red)' }}
          >
            <AlertTriangle size={11} />
            {expiringSoon.length} expiring
          </span>
        )}
        <span
          className="ml-auto flex items-center gap-1 text-[10px]"
          style={{ color: 'var(--subtext0)' }}
        >
          {collapsed && <span>avg {avgCompleteness}%</span>}
          {collapsed ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
        </span>
      </button>

      {collapsed ? (
        <div className="text-[11px] px-0.5" style={{ color: 'var(--subtext0)' }}>
          {captures.length} 筆待處理捕捉，平均完整度 {avgCompleteness}%
        </div>
      ) : (
        <>
          {error && (
            <div
              className="text-[11px] mb-2 px-2 py-1 rounded"
              style={{ color: 'var(--red)', backgroundColor: 'var(--surface1)' }}
            >
              {error}
            </div>
          )}

          <div className="space-y-1.5">
            {captures.map((c) => {
              const isExpiring =
                c.expires_at && new Date(c.expires_at).getTime() - now < 3 * 24 * 60 * 60 * 1000
              return (
                <div key={c.id}>
                  <div className="flex items-center gap-2 group">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1">
                        <span className="text-xs truncate" style={{ color: 'var(--text)' }}>
                          {desc(c)}
                        </span>
                        {isExpiring && (
                          <AlertTriangle
                            size={11}
                            style={{ color: 'var(--red)' }}
                            className="shrink-0"
                          />
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <CompletionBar value={c.completeness} />
                        <span
                          className="text-[10px] flex items-center gap-0.5"
                          style={{ color: 'var(--overlay1)' }}
                        >
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
                          className="text-[10px] px-1.5 py-0.5 rounded border transition-colors"
                          style={{
                            borderColor: 'var(--surface2)',
                            color: 'var(--blue)',
                          }}
                          title="補充欄位"
                        >
                          補充
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handlePromote(c.id)}
                        disabled={promoting === c.id}
                        className="p-1 rounded transition-colors"
                        style={{ color: 'var(--green)' }}
                        title="提升為正式紀錄"
                      >
                        <ArrowUpRight size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(c.id)}
                        className="p-1 rounded transition-colors"
                        style={{ color: 'var(--red)' }}
                        title="刪除"
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
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

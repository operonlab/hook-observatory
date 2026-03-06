import { AlertTriangle, Info, Send, Zap } from 'lucide-react'
import { useState } from 'react'
import type { SendPayload, SendResult } from '../api'
import { sendNotification } from '../api'

const CATEGORIES = ['sentinel', 'system', 'finance', 'taskflow', 'intelflow', 'agent'] as const
const SEVERITIES = [
  { value: 'info', label: 'Info', icon: Info, color: 'var(--teal)' },
  { value: 'warning', label: 'Warning', icon: AlertTriangle, color: 'var(--yellow)' },
  { value: 'critical', label: 'Critical', icon: Zap, color: 'var(--red)' },
] as const

export default function SendForm() {
  const [form, setForm] = useState<SendPayload>({
    category: 'system',
    title: '',
    body: '',
    url: '/',
    severity: 'info',
  })
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<SendResult | null>(null)
  const [error, setError] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.title.trim()) return
    setSending(true)
    setError('')
    setResult(null)
    sendNotification(form)
      .then(setResult)
      .catch((err: Error) => setError(err.message))
      .finally(() => setSending(false))
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Category */}
      <div>
        <span
          className="mb-2 block text-xs font-medium uppercase tracking-wider"
          style={{ color: 'var(--subtext1)' }}
        >
          分類
        </span>
        <div className="flex flex-wrap gap-1.5">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setForm((f) => ({ ...f, category: c }))}
              className="rounded-md px-3 py-2 text-[13px] font-medium transition-all duration-200 cursor-pointer"
              style={{
                backgroundColor: form.category === c ? 'var(--accent)' : 'var(--surface0)',
                color: form.category === c ? 'var(--crust)' : 'var(--subtext0)',
                minHeight: 38,
                border:
                  form.category === c ? '1px solid var(--accent)' : '1px solid var(--surface1)',
              }}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* Severity */}
      <div>
        <span
          className="mb-2 block text-xs font-medium uppercase tracking-wider"
          style={{ color: 'var(--subtext1)' }}
        >
          嚴重度
        </span>
        <div className="flex gap-2">
          {SEVERITIES.map((s) => {
            const active = form.severity === s.value
            const Icon = s.icon
            return (
              <button
                key={s.value}
                type="button"
                onClick={() => setForm((f) => ({ ...f, severity: s.value }))}
                className="flex items-center gap-2 rounded-md px-3 py-2 text-[13px] font-medium transition-all duration-200 cursor-pointer"
                style={{
                  backgroundColor: active
                    ? `color-mix(in srgb, ${s.color} 15%, transparent)`
                    : 'var(--surface0)',
                  color: active ? s.color : 'var(--subtext0)',
                  border: active ? `1px solid ${s.color}` : '1px solid var(--surface1)',
                  minHeight: 38,
                }}
              >
                <Icon size={14} />
                {s.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Title */}
      <label className="block">
        <span
          className="mb-2 block text-xs font-medium uppercase tracking-wider"
          style={{ color: 'var(--subtext1)' }}
        >
          標題
        </span>
        <input
          type="text"
          value={form.title}
          onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
          placeholder="通知標題"
          required
          className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors duration-200"
          style={{
            backgroundColor: 'var(--mantle)',
            borderColor: 'var(--surface0)',
            color: 'var(--text)',
            minHeight: 44,
          }}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = 'var(--accent)'
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = 'var(--surface0)'
          }}
        />
      </label>

      {/* Body */}
      <label className="block">
        <span
          className="mb-2 block text-xs font-medium uppercase tracking-wider"
          style={{ color: 'var(--subtext1)' }}
        >
          內容
        </span>
        <textarea
          value={form.body}
          onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))}
          placeholder="通知內容（選填）"
          rows={3}
          className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors duration-200"
          style={{
            backgroundColor: 'var(--mantle)',
            borderColor: 'var(--surface0)',
            color: 'var(--text)',
          }}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = 'var(--accent)'
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = 'var(--surface0)'
          }}
        />
      </label>

      {/* URL */}
      <label className="block">
        <span
          className="mb-2 block text-xs font-medium uppercase tracking-wider"
          style={{ color: 'var(--subtext1)' }}
        >
          連結
        </span>
        <input
          type="text"
          value={form.url}
          onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
          placeholder="/"
          className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors duration-200"
          style={{
            backgroundColor: 'var(--mantle)',
            borderColor: 'var(--surface0)',
            color: 'var(--text)',
            minHeight: 44,
          }}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = 'var(--accent)'
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = 'var(--surface0)'
          }}
        />
      </label>

      {/* Submit */}
      <button
        type="submit"
        disabled={sending || !form.title.trim()}
        className="flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-all duration-200 disabled:opacity-40 cursor-pointer"
        style={{
          backgroundColor: 'var(--accent)',
          color: 'var(--crust)',
          minHeight: 44,
        }}
      >
        <Send size={15} />
        {sending ? '發送中...' : '發送通知'}
      </button>

      {/* Result */}
      {result && (
        <div
          className="flex items-start gap-3 rounded-lg border px-4 py-3 text-sm"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--green) 8%, transparent)',
            borderColor: 'color-mix(in srgb, var(--green) 30%, transparent)',
            color: 'var(--green)',
          }}
        >
          <Info size={16} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">
              送達 {result.delivered} / 失敗 {result.failed}
            </div>
            <div className="mt-1 text-xs opacity-80">
              Web Push: {result.channels.web_push} | Bark: {result.channels.bark ? 'OK' : 'N/A'}
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          className="flex items-center gap-2 rounded-lg border px-4 py-3 text-sm"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--red) 8%, transparent)',
            borderColor: 'color-mix(in srgb, var(--red) 30%, transparent)',
            color: 'var(--red)',
          }}
        >
          <AlertTriangle size={15} />
          {error}
        </div>
      )}
    </form>
  )
}

import { useState } from 'react'

interface Props {
  initialFrom?: number
  initialTo?: number
  submitLabel: string
  loadingLabel: string
  loading: boolean
  error: string
  onSubmit: (fromV: number, toV: number) => void
}

export default function VersionRangeSelector({
  initialFrom,
  initialTo,
  submitLabel,
  loadingLabel,
  loading,
  error,
  onSubmit,
}: Props) {
  const [fromV, setFromV] = useState(initialFrom ?? 1)
  const [toV, setToV] = useState(initialTo ?? 2)

  const handleSubmit = () => {
    onSubmit(fromV, toV)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-end gap-3">
        <div>
          <label className="text-[11px] block mb-1" style={{ color: 'var(--fn-text-muted)' }}>
            從版本
          </label>
          <input
            type="number"
            min={1}
            value={fromV}
            onChange={(e) => setFromV(Number(e.target.value))}
            className="w-20 px-2 py-1.5 text-xs rounded-md"
            style={{
              backgroundColor: 'var(--fn-bg-surface)',
              border: '1px solid var(--fn-border)',
              color: 'var(--fn-text)',
            }}
          />
        </div>
        <span className="text-xs pb-2" style={{ color: 'var(--fn-text-muted)' }}>
          →
        </span>
        <div>
          <label className="text-[11px] block mb-1" style={{ color: 'var(--fn-text-muted)' }}>
            到版本
          </label>
          <input
            type="number"
            min={2}
            value={toV}
            onChange={(e) => setToV(Number(e.target.value))}
            className="w-20 px-2 py-1.5 text-xs rounded-md"
            style={{
              backgroundColor: 'var(--fn-bg-surface)',
              border: '1px solid var(--fn-border)',
              color: 'var(--fn-text)',
            }}
          />
        </div>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={loading}
          className="px-3 py-1.5 text-xs rounded-md transition-colors"
          style={{
            backgroundColor: 'var(--fn-accent)',
            color: '#fff',
            opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? loadingLabel : submitLabel}
        </button>
      </div>

      {error && (
        <div className="text-xs" style={{ color: 'var(--fn-expense)' }}>
          {error}
        </div>
      )}
    </div>
  )
}

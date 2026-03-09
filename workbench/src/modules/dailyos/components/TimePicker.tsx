import { useState } from 'react'

interface TimePickerProps {
  value?: string // "HH:MM"
  onChange: (time: string) => void
  onCancel?: () => void
  compact?: boolean
  className?: string
}

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0'))

export default function TimePicker({
  value,
  onChange,
  onCancel,
  compact,
  className,
}: TimePickerProps) {
  const [hour, setHour] = useState(value?.slice(0, 2) || '')
  const [minute, setMinute] = useState(value?.slice(3, 5) || '')

  const handleChange = (h: string, m: string) => {
    const newH = h || '00'
    const newM = m || '00'
    setHour(newH)
    setMinute(newM)
    onChange(`${newH}:${newM}`)
  }

  const selectStyle: React.CSSProperties = {
    backgroundColor: 'var(--do-bg-surface)',
    color: 'var(--do-text)',
    borderColor: 'var(--do-border)',
    borderWidth: '1px',
    borderStyle: 'solid',
    borderRadius: '4px',
    padding: compact ? '2px 4px' : '4px 8px',
    fontSize: compact ? '11px' : '13px',
    outline: 'none',
    cursor: 'pointer',
  }

  const selects = (
    <span className={`inline-flex items-center gap-0.5 ${className || ''}`}>
      <select
        value={hour}
        onChange={(e) => handleChange(e.target.value, minute)}
        style={selectStyle}
        aria-label="時"
      >
        <option value="" disabled>
          時
        </option>
        {HOURS.map((h) => (
          <option key={h} value={h}>
            {h}
          </option>
        ))}
      </select>
      <span className="text-[11px]" style={{ color: 'var(--do-text-muted)' }}>
        :
      </span>
      <select
        value={minute}
        onChange={(e) => handleChange(hour, e.target.value)}
        style={selectStyle}
        aria-label="分"
      >
        <option value="" disabled>
          分
        </option>
        {MINUTES.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </span>
  )

  if (compact) return selects

  return (
    <div
      className="inline-flex items-center gap-2 px-2 py-1.5 rounded-md"
      style={{ backgroundColor: 'var(--do-bg-elevated)', border: '1px solid var(--do-border)' }}
    >
      {selects}
      {onCancel && (
        <button
          type="button"
          onClick={onCancel}
          className="text-[11px] px-1.5 py-0.5 rounded transition-colors"
          style={{ color: 'var(--do-text-muted)', backgroundColor: 'var(--do-bg-surface)' }}
        >
          取消
        </button>
      )}
    </div>
  )
}

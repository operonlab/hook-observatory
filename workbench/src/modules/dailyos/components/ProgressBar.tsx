interface ProgressBarProps {
  done: number
  total: number
}

export default function ProgressBar({ done, total }: ProgressBarProps) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  const isComplete = pct === 100

  return (
    <div className="flex items-center gap-3">
      <div
        className="flex-1 h-2 rounded-full overflow-hidden"
        style={{ backgroundColor: 'var(--do-bg-surface)' }}
      >
        <div
          className={`h-full rounded-full ${isComplete ? 'progress-complete' : ''}`}
          style={{
            width: `${pct}%`,
            background: 'linear-gradient(90deg, #a6e3a1, #b8f0b2)',
            boxShadow: pct > 0 ? 'inset 0 1px 2px rgba(255,255,255,0.15)' : 'none',
            transition: 'width 500ms ease',
          }}
        />
      </div>
      <span
        className="text-[12px] shrink-0"
        style={{
          color: 'var(--do-text-secondary)',
          fontFeatureSettings: '"tnum"',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {done}/{total} ({pct}%)
      </span>
    </div>
  )
}

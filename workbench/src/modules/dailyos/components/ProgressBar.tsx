interface ProgressBarProps {
  done: number
  total: number
}

export default function ProgressBar({ done, total }: ProgressBarProps) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  return (
    <div className="flex items-center gap-3">
      <div
        className="flex-1 h-2 rounded-full overflow-hidden"
        style={{ backgroundColor: 'var(--do-bg-surface)' }}
      >
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{
            width: `${pct}%`,
            backgroundColor: '#a6e3a1',
          }}
        />
      </div>
      <span
        className="text-[12px] tabular-nums shrink-0"
        style={{ color: 'var(--do-text-secondary)' }}
      >
        {done}/{total} ({pct}%)
      </span>
    </div>
  )
}

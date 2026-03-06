interface ConfidenceMeterProps {
  value: number // 0-1
}

export default function ConfidenceMeter({ value }: ConfidenceMeterProps) {
  const pct = Math.round(value * 100)
  const color =
    pct >= 70
      ? 'var(--bf-confidence-high)'
      : pct >= 40
        ? 'var(--bf-confidence-mid)'
        : 'var(--bf-confidence-low)'

  return (
    <div className="flex items-center gap-2">
      <div
        className="h-1 w-16"
        style={{ backgroundColor: 'var(--bf-bg-surface)' }}
      >
        <div
          className="h-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-[10px] tabular-nums" style={{ color }}>
        {pct}%
      </span>
    </div>
  )
}

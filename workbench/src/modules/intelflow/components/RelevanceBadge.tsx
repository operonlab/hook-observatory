interface RelevanceBadgeProps {
  score: number
}

export default function RelevanceBadge({ score }: RelevanceBadgeProps) {
  const pct = Math.round(score * 100)

  let color: string
  let bg: string
  let label: string

  if (pct >= 80) {
    color = 'var(--if-score-high)'
    bg = 'var(--if-score-high-bg)'
    label = '高度相關'
  } else if (pct >= 50) {
    color = 'var(--if-score-mid)'
    bg = 'var(--if-score-mid-bg)'
    label = '中度相關'
  } else {
    color = 'var(--if-score-low)'
    bg = 'var(--if-score-low-bg)'
    label = '低度相關'
  }

  return (
    <span
      className="inline-flex items-center gap-1 sm:gap-1.5 px-2 py-0.5 text-[10px] sm:text-xs border shrink-0"
      style={{ backgroundColor: bg, borderColor: color, color }}
    >
      <span className="inline-block w-1.5 h-1.5 shrink-0" style={{ backgroundColor: color }} />
      <span className="hidden sm:inline">
        {pct}% {label}
      </span>
      <span className="sm:hidden">{pct}%</span>
    </span>
  )
}

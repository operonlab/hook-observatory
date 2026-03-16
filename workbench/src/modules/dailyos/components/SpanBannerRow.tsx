import type { ActivitySpan } from '../types'

interface Props {
  spans: ActivitySpan[]
  weekDates: Date[] // exactly 7 dates
}

function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

interface LayoutSpan {
  span: ActivitySpan
  startCol: number
  endCol: number // inclusive
  row: number
}

function layoutSpans(spans: ActivitySpan[], weekDates: Date[]): LayoutSpan[] {
  const weekStart = toDateStr(weekDates[0])
  const weekEnd = toDateStr(weekDates[6])

  const visible = spans.filter(
    (s) => s.is_active && s.start_date <= weekEnd && s.end_date >= weekStart,
  )

  const positioned: LayoutSpan[] = visible.map((span) => {
    const startCol = Math.max(
      0,
      weekDates.findIndex((d) => toDateStr(d) >= span.start_date),
    )
    let endCol = weekDates.findIndex((d) => toDateStr(d) > span.end_date)
    endCol = endCol === -1 ? 6 : endCol - 1

    return { span, startCol, endCol, row: 0 }
  })

  // Greedy row packing
  const rows: Array<number> = [] // tracks end col of last span in each row
  for (const item of positioned) {
    let placed = false
    for (let r = 0; r < rows.length; r++) {
      if (item.startCol > rows[r]) {
        item.row = r
        rows[r] = item.endCol
        placed = true
        break
      }
    }
    if (!placed) {
      item.row = rows.length
      rows.push(item.endCol)
    }
  }

  return positioned
}

const MAX_ROWS = 2

export default function SpanBannerRow({ spans, weekDates }: Props) {
  if (spans.length === 0 || weekDates.length !== 7) return null

  const layout = layoutSpans(spans, weekDates)
  const visibleRows = layout.filter((l) => l.row < MAX_ROWS)
  const overflow = layout.filter((l) => l.row >= MAX_ROWS).length
  const rowCount = Math.min(MAX_ROWS, Math.max(...layout.map((l) => l.row), 0) + 1)

  const weekStart = toDateStr(weekDates[0])
  const weekEnd = toDateStr(weekDates[6])

  return (
    <div className="relative" style={{ minHeight: rowCount * 24 + (overflow > 0 ? 16 : 0) }}>
      {visibleRows.map(({ span, startCol, endCol, row }) => {
        const isStart = span.start_date >= weekStart
        const isEnd = span.end_date <= weekEnd
        return (
          <div
            key={span.id}
            className="absolute text-[10px] font-medium truncate px-1.5 flex items-center"
            style={{
              left: `${(startCol / 7) * 100}%`,
              width: `${((endCol - startCol + 1) / 7) * 100}%`,
              top: row * 24,
              height: 20,
              backgroundColor: span.color + '33',
              color: span.color,
              borderRadius: `${isStart ? 4 : 0}px ${isEnd ? 4 : 0}px ${isEnd ? 4 : 0}px ${isStart ? 4 : 0}px`,
              borderLeft: isStart ? `2px solid ${span.color}` : 'none',
            }}
            title={`${span.title} (${span.start_date} ~ ${span.end_date})`}
          >
            {span.title}
          </div>
        )
      })}
      {overflow > 0 && (
        <div
          className="absolute text-[9px] right-1"
          style={{
            top: MAX_ROWS * 24,
            color: 'var(--do-text-muted)',
          }}
        >
          +{overflow}
        </div>
      )}
    </div>
  )
}

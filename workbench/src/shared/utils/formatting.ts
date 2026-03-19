/** Format number with 2 decimal places and locale grouping */
export const fmtAmt = (v: number | string): string =>
  Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Format percentage with sign: "+1.23%" or "-0.45%" */
export const fmtPct = (v: number | string): string =>
  `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`

/** Short date: "3/20" (month/day, zh-TW locale) */
export function fmtDate(dateStr: string | null): string {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-TW', { month: 'numeric', day: 'numeric' })
}

/** Long date: "2026年3月20日 (週五)" */
export function fmtDateLong(dateStr: string): string {
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString('zh-TW', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  })
}

/** Date range: "3/15 - 20" or "3/15 - 4/1" */
export function fmtDateRange(start: string, end: string): string {
  const s = new Date(`${start}T00:00:00`)
  const e = new Date(`${end}T00:00:00`)
  const sm = s.getMonth() + 1
  const sd = s.getDate()
  const em = e.getMonth() + 1
  const ed = e.getDate()
  if (sm === em) return `${sm}/${sd} - ${ed}`
  return `${sm}/${sd} - ${em}/${ed}`
}

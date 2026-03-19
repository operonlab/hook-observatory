import { ChevronRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useBriefingHistory } from '../hooks/useBriefing'
import { useBriefingStore } from '../stores'
import { fmtDateLong } from '../../../shared/utils/formatting'

export default function BriefingHistory() {
  const { briefings, total, page, loading, fetchBriefings } = useBriefingHistory()
  const { setSelectedDate } = useBriefingStore()
  const navigate = useNavigate()

  // Group by date
  const grouped = new Map<string, typeof briefings>()
  for (const b of briefings) {
    const existing = grouped.get(b.date) || []
    existing.push(b)
    grouped.set(b.date, existing)
  }
  const dates = Array.from(grouped.keys()).sort().reverse()

  const pageSize = 20
  const totalPages = Math.ceil(total / pageSize)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div
          className="h-6 w-6 animate-spin border-2 border-t-transparent"
          style={{ borderColor: 'var(--bf-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-6">
      <h1
        className="text-xl sm:text-2xl font-light"
        style={{ fontFamily: 'var(--bf-font-display)', color: 'var(--bf-text)' }}
      >
        簡報歷史
      </h1>

      {dates.length === 0 ? (
        <div
          className="border p-8 text-center text-sm"
          style={{
            backgroundColor: 'var(--bf-bg-elevated)',
            borderColor: 'var(--bf-border)',
            color: 'var(--bf-text-dim)',
          }}
        >
          尚無歷史簡報
        </div>
      ) : (
        <div className="space-y-3">
          {dates.map((date) => {
            const items = grouped.get(date)!
            const domainCount = items.length
            const completedCount = items.filter((b) => b.status === 'completed').length

            return (
              <button
                key={date}
                onClick={() => {
                  setSelectedDate(date)
                  navigate('/briefing')
                }}
                className="flex items-center justify-between w-full px-4 sm:px-5 py-4 border text-left transition-colors"
                style={{
                  backgroundColor: 'var(--bf-bg-elevated)',
                  borderColor: 'var(--bf-border)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--bf-accent)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--bf-border)'
                }}
              >
                <div>
                  <div className="text-sm font-medium" style={{ color: 'var(--bf-text)' }}>
                    {fmtDateLong(date)}
                  </div>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-xs" style={{ color: 'var(--bf-text-dim)' }}>
                      {domainCount} 領域
                    </span>
                    <span className="text-xs" style={{ color: 'var(--bf-text-dim)' }}>
                      {completedCount}/{domainCount} 完成
                    </span>
                    {items.some((b) => b.conclusion) && (
                      <span className="text-[10px]" style={{ color: 'var(--bf-confidence-high)' }}>
                        有結論
                      </span>
                    )}
                  </div>
                </div>
                <ChevronRight size={16} style={{ color: 'var(--bf-text-muted)' }} />
              </button>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
            <button
              key={p}
              onClick={() => fetchBriefings(p)}
              className="px-3 py-1.5 text-xs border transition-colors"
              style={{
                backgroundColor: p === page ? 'var(--bf-accent)' : 'transparent',
                borderColor: p === page ? 'var(--bf-accent)' : 'var(--bf-border)',
                color: p === page ? 'var(--bf-text-on-accent)' : 'var(--bf-text-tertiary)',
              }}
            >
              {p}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

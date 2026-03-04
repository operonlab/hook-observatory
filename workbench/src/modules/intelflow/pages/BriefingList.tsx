import { Calendar, ChevronLeft, ChevronRight, Newspaper } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useBriefings } from '../hooks/useIntelflow'

export default function BriefingList() {
  const { briefings, total, page, loading, fetchBriefings } = useBriefings()
  const navigate = useNavigate()

  const pageSize = 20
  const totalPages = Math.ceil(total / pageSize)

  // Group by date
  const byDate = briefings.reduce(
    (acc, b) => {
      const d = b.date
      if (!acc[d]) acc[d] = []
      acc[d].push(b)
      return acc
    },
    {} as Record<string, typeof briefings>,
  )
  const dates = Object.keys(byDate).sort((a, b) => b.localeCompare(a))

  const formatDate = (dateStr: string) =>
    new Date(dateStr + 'T00:00:00').toLocaleDateString('zh-TW', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      weekday: 'short',
    })

  const domainCount = (items: typeof briefings) => {
    const domains = new Set<string>()
    for (const b of items) {
      if (b.entries?.length) {
        b.entries.filter((e) => e.phase === 'raw').forEach((e) => domains.add(e.key))
      } else if (b.raw_data) {
        Object.keys(b.raw_data).forEach((k) => domains.add(k))
      }
    }
    return domains.size
  }

  const analystCount = (items: typeof briefings) => {
    const analysts = new Set<string>()
    for (const b of items) {
      if (b.entries?.length) {
        b.entries.filter((e) => e.phase === 'analysis').forEach((e) => analysts.add(e.key))
      } else if (b.analyses) {
        Object.keys(b.analyses).forEach((k) => analysts.add(k))
      }
    }
    return analysts.size
  }

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1
            className="text-2xl sm:text-3xl font-light"
            style={{ fontFamily: 'var(--if-font-display)', color: 'var(--if-text)' }}
          >
            每日簡報
          </h1>
          <p className="text-xs mt-1" style={{ color: 'var(--if-text-dim)' }}>
            三 CLI 分析師交叉辯論 · 每日自動生成
          </p>
        </div>
      </div>

      {/* List */}
      <div className="space-y-3">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div
              className="h-5 w-5 animate-spin border-2 border-t-transparent"
              style={{ borderColor: 'var(--if-accent)', borderTopColor: 'transparent' }}
            />
          </div>
        ) : dates.length > 0 ? (
          dates.map((dateStr) => {
            const items = byDate[dateStr]
            const hasDebate = items.some(
              (b) => (b.entries?.length && b.entries.some((e) => e.phase === 'debate')) || b.debate,
            )
            const status = items[0]?.status
            return (
              <button
                key={dateStr}
                onClick={() => navigate(`/intelflow/briefings/${dateStr}`)}
                className="w-full text-left border p-4 sm:p-5 transition-colors"
                style={{
                  backgroundColor: 'var(--if-bg-elevated)',
                  borderColor: 'var(--if-border)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--if-accent)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--if-border)'
                }}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <Calendar size={14} style={{ color: 'var(--if-accent)' }} />
                      <span
                        className="text-base sm:text-lg font-light"
                        style={{
                          fontFamily: 'var(--if-font-display)',
                          color: 'var(--if-text)',
                        }}
                      >
                        {formatDate(dateStr)}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 mt-2">
                      <span className="text-xs" style={{ color: 'var(--if-text-dim)' }}>
                        {domainCount(items)} 領域
                      </span>
                      <span className="text-xs" style={{ color: 'var(--if-text-dim)' }}>
                        {analystCount(items)} 分析師
                      </span>
                      {hasDebate && (
                        <span
                          className="text-[10px] px-1.5 py-0.5 border"
                          style={{
                            borderColor: 'var(--if-accent)',
                            color: 'var(--if-accent)',
                          }}
                        >
                          交叉辯論
                        </span>
                      )}
                      {status && status !== 'completed' && (
                        <span
                          className="text-[10px] px-1.5 py-0.5 border animate-pulse"
                          style={{
                            borderColor: 'var(--if-text-dim)',
                            color: 'var(--if-text-dim)',
                          }}
                        >
                          {status}
                        </span>
                      )}
                    </div>
                  </div>
                  <Newspaper size={18} style={{ color: 'var(--if-text-muted)', flexShrink: 0 }} />
                </div>
              </button>
            )
          })
        ) : (
          <div
            className="border p-8 text-center text-sm"
            style={{
              backgroundColor: 'var(--if-bg-elevated)',
              borderColor: 'var(--if-border)',
              color: 'var(--if-text-dim)',
            }}
          >
            尚無簡報資料
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-xs" style={{ color: 'var(--if-text-tertiary)' }}>
            共 {total} 筆，第 {page}/{totalPages} 頁
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => fetchBriefings(page - 1)}
              disabled={page <= 1}
              className="p-2.5 border disabled:opacity-30 min-w-[44px] min-h-[44px] flex items-center justify-center"
              style={{ borderColor: 'var(--if-border)', color: 'var(--if-text-secondary)' }}
            >
              <ChevronLeft size={14} />
            </button>
            <button
              onClick={() => fetchBriefings(page + 1)}
              disabled={page >= totalPages}
              className="p-2.5 border disabled:opacity-30 min-w-[44px] min-h-[44px] flex items-center justify-center"
              style={{ borderColor: 'var(--if-border)', color: 'var(--if-text-secondary)' }}
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

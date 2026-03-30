import { ChevronLeft, ChevronRight, Plus, Search } from 'lucide-react'
import { useState } from 'react'
import ReportRow from '../components/ReportRow'
import TagBadge from '../components/TagBadge'
import { useReports } from '../hooks/useIntelflow'

type SortMode = 'date-desc' | 'date-asc' | 'title-asc'

const SORT_OPTIONS: { mode: SortMode; label: string }[] = [
  { mode: 'date-desc', label: '最新' },
  { mode: 'date-asc', label: '最舊' },
  { mode: 'title-asc', label: '標題' },
]

const MAX_VISIBLE_TAGS = 10

export default function ReportList() {
  const {
    reports,
    total,
    page,
    pageSize,
    loading,
    activeTag,
    allTags,
    setPage,
    deleteReport,
    setActiveTag,
  } = useReports()

  const [deleteError, setDeleteError] = useState<string | null>(null)

  const handleDelete = async (id: string) => {
    if (!window.confirm('確定要刪除這份報告嗎？')) return
    try {
      await deleteReport(id)
      setDeleteError(null)
    } catch {
      setDeleteError('刪除失敗，請稍後再試')
    }
  }
  const [searchText, setSearchText] = useState('')
  const [tagsExpanded, setTagsExpanded] = useState(false)
  const [sortMode, setSortMode] = useState<SortMode>('date-desc')

  const totalPages = Math.ceil(total / pageSize)

  const filtered = searchText
    ? reports.filter(
        (r) =>
          r.title.toLowerCase().includes(searchText.toLowerCase()) ||
          r.tags.some((t) => t.toLowerCase().includes(searchText.toLowerCase())),
      )
    : reports

  // Client-side sort
  const sorted = [...filtered].sort((a, b) => {
    switch (sortMode) {
      case 'date-desc':
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      case 'date-asc':
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      case 'title-asc':
        return a.title.localeCompare(b.title, 'zh-TW')
      default:
        return 0
    }
  })

  const visibleTags = tagsExpanded ? allTags : allTags.slice(0, MAX_VISIBLE_TAGS)
  const hiddenCount = allTags.length - MAX_VISIBLE_TAGS

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      {/* Delete error */}
      {deleteError && (
        <div
          className="px-4 py-3 text-sm"
          style={{
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: 'rgb(252, 165, 165)',
          }}
        >
          {deleteError}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <h1
          className="text-2xl sm:text-3xl font-light"
          style={{ fontFamily: 'var(--if-font-display)', color: 'var(--if-text)' }}
        >
          研究報告
        </h1>
        <button
          type="button"
          className="flex items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-2 text-xs sm:text-sm border shrink-0 min-h-[44px]"
          style={{
            borderColor: 'var(--if-accent)',
            color: 'var(--if-accent)',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = 'var(--if-accent)'
            e.currentTarget.style.color = 'var(--if-text-on-accent)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent'
            e.currentTarget.style.color = 'var(--if-accent)'
          }}
        >
          <Plus size={14} />
          <span className="hidden xs:inline">新增報告</span>
          <span className="xs:hidden">新增</span>
        </button>
      </div>

      {/* Search + Sort — stacked on mobile, side-by-side on sm+ */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
        <div
          className="flex items-center gap-3 border px-4 py-3 flex-1"
          style={{
            backgroundColor: 'var(--if-bg-elevated)',
            borderColor: 'var(--if-border)',
          }}
        >
          <Search size={16} style={{ color: 'var(--if-text-muted)' }} />
          <input
            type="text"
            placeholder="搜尋報告標題或標籤..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--if-text-dim)]"
            style={{ color: 'var(--if-text)' }}
          />
        </div>
        <div className="flex shrink-0">
          {SORT_OPTIONS.map(({ mode, label }, i) => (
            <button
              type="button"
              key={mode}
              onClick={() => setSortMode(mode)}
              className={`flex-1 sm:flex-none px-3 py-3 text-xs border-y border-r ${i === 0 ? 'border-l' : ''} min-h-[44px]`}
              style={{
                borderColor: 'var(--if-border)',
                backgroundColor: sortMode === mode ? 'var(--if-accent)' : 'var(--if-bg-elevated)',
                color: sortMode === mode ? 'var(--if-text-on-accent)' : 'var(--if-text-secondary)',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Tag filters */}
      {allTags.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <TagBadge tag="全部" active={!activeTag} onClick={() => setActiveTag(null)} />
          {visibleTags.map((tag) => (
            <TagBadge
              key={tag}
              tag={tag}
              active={activeTag === tag}
              onClick={() => setActiveTag(activeTag === tag ? null : tag)}
            />
          ))}
          {hiddenCount > 0 && (
            <button
              type="button"
              onClick={() => setTagsExpanded(!tagsExpanded)}
              className="shrink-0 text-xs px-2.5 py-2 border transition-colors min-h-[36px]"
              style={{
                borderColor: 'var(--if-border)',
                color: 'var(--if-text-dim)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--if-accent)'
                e.currentTarget.style.color = 'var(--if-accent)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--if-border)'
                e.currentTarget.style.color = 'var(--if-text-dim)'
              }}
            >
              {tagsExpanded ? '收合' : `+${hiddenCount}`}
            </button>
          )}
        </div>
      )}

      {/* Report list */}
      <div
        className="border"
        style={{
          backgroundColor: 'var(--if-bg-elevated)',
          borderColor: 'var(--if-border)',
        }}
      >
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div
              className="h-5 w-5 animate-spin border-2 border-t-transparent"
              style={{ borderColor: 'var(--if-accent)', borderTopColor: 'transparent' }}
            />
          </div>
        ) : sorted.length > 0 ? (
          sorted.map((report) => (
            <ReportRow key={report.id} report={report} onDelete={handleDelete} />
          ))
        ) : (
          <div className="p-8 text-center text-sm" style={{ color: 'var(--if-text-dim)' }}>
            {searchText ? '無搜尋結果' : '尚無報告'}
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
              type="button"
              onClick={() => setPage(page - 1)}
              disabled={page <= 1}
              className="p-2.5 border disabled:opacity-30 min-w-[44px] min-h-[44px] flex items-center justify-center"
              style={{ borderColor: 'var(--if-border)', color: 'var(--if-text-secondary)' }}
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              onClick={() => setPage(page + 1)}
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

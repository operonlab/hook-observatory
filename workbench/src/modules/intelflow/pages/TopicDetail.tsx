import { ArrowLeft, ChevronLeft, ChevronRight, Hash } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { intelflowApi } from '../api/client'
import ReportRow from '../components/ReportRow'
import type { Report, Topic } from '../types'

export default function TopicDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [topic, setTopic] = useState<Topic | null>(null)
  const [reports, setReports] = useState<Report[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const pageSize = 20

  const fetchReports = useCallback(
    async (p: number) => {
      if (!id) return
      setLoading(true)
      try {
        const res = await intelflowApi.listByTopic(id, p, pageSize)
        setReports(res.items)
        setTotal(res.total)
        setPage(p)
      } catch {
        // ignore
      } finally {
        setLoading(false)
      }
    },
    [id],
  )

  useEffect(() => {
    // Find topic info from the topics list
    async function loadTopic() {
      const res = await intelflowApi.listTopics(1, 200)
      const found = res.items.find((t) => t.id === id)
      if (found) setTopic(found)
    }
    loadTopic()
    fetchReports(1)
  }, [id, fetchReports])

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      {/* Back + Header */}
      <div className="space-y-3">
        <button
          onClick={() => navigate('/intelflow/topics')}
          className="flex items-center gap-1.5 text-xs transition-colors min-h-[44px] sm:min-h-0"
          style={{ color: 'var(--if-text-dim)' }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = 'var(--if-text-secondary)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = 'var(--if-text-dim)'
          }}
        >
          <ArrowLeft size={13} />
          主題總覽
        </button>

        <div className="flex items-center gap-2 sm:gap-3">
          <Hash size={18} style={{ color: 'var(--if-accent)', flexShrink: 0 }} />
          <h1
            className="text-2xl sm:text-3xl font-light leading-tight"
            style={{
              fontFamily: 'var(--if-font-display)',
              color: 'var(--if-text)',
            }}
          >
            {topic?.display_name || topic?.name || '...'}
          </h1>
        </div>

        <p className="text-sm" style={{ color: 'var(--if-text-tertiary)' }}>
          {total} 篇相關報告
        </p>
      </div>

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
              style={{
                borderColor: 'var(--if-accent)',
                borderTopColor: 'transparent',
              }}
            />
          </div>
        ) : reports.length > 0 ? (
          reports.map((report) => <ReportRow key={report.id} report={report} />)
        ) : (
          <div className="p-8 text-center text-sm" style={{ color: 'var(--if-text-dim)' }}>
            此主題尚無報告
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
              onClick={() => fetchReports(page - 1)}
              disabled={page <= 1}
              className="p-2.5 border disabled:opacity-30 min-w-[44px] min-h-[44px] flex items-center justify-center"
              style={{
                borderColor: 'var(--if-border)',
                color: 'var(--if-text-secondary)',
              }}
            >
              <ChevronLeft size={14} />
            </button>
            <button
              onClick={() => fetchReports(page + 1)}
              disabled={page >= totalPages}
              className="p-2.5 border disabled:opacity-30 min-w-[44px] min-h-[44px] flex items-center justify-center"
              style={{
                borderColor: 'var(--if-border)',
                color: 'var(--if-text-secondary)',
              }}
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

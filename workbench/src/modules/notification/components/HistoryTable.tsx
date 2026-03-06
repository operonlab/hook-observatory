import { Inbox } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { PaginatedResponse } from '@/types'
import type { NotificationLog } from '../api'
import { listHistory } from '../api'
import CategoryBadge from './CategoryBadge'

const CATEGORY_TABS = [
  { value: '', label: '全部' },
  { value: 'sentinel', label: 'sentinel' },
  { value: 'system', label: 'system' },
  { value: 'finance', label: 'finance' },
  { value: 'taskflow', label: 'taskflow' },
  { value: 'intelflow', label: 'intelflow' },
  { value: 'agent', label: 'agent' },
]

const PAGE_SIZE = 20

export default function HistoryTable() {
  const [data, setData] = useState<PaginatedResponse<NotificationLog> | null>(null)
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    listHistory({
      page,
      page_size: PAGE_SIZE,
      category: category || undefined,
    })
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [page, category])

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0

  return (
    <div>
      {/* Category filter */}
      <div
        className="mb-4 flex gap-1 overflow-x-auto rounded-lg p-1"
        style={{ backgroundColor: 'var(--surface0)' }}
      >
        {CATEGORY_TABS.map((tab) => (
          <button
            type="button"
            key={tab.value}
            onClick={() => {
              setCategory(tab.value)
              setPage(1)
            }}
            className="whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors duration-200 cursor-pointer"
            style={{
              backgroundColor: category === tab.value ? 'var(--mantle)' : 'transparent',
              color: category === tab.value ? 'var(--text)' : 'var(--subtext1)',
              minHeight: 36,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div
          className="mb-4 rounded-lg border px-4 py-3 text-sm"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--red) 8%, transparent)',
            borderColor: 'color-mix(in srgb, var(--red) 30%, transparent)',
            color: 'var(--red)',
          }}
        >
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-hidden rounded-xl border" style={{ borderColor: 'var(--surface0)' }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ backgroundColor: 'var(--surface0)' }}>
              <th
                className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider sm:px-4"
                style={{ color: 'var(--subtext1)' }}
              >
                時間
              </th>
              <th
                className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider sm:px-4"
                style={{ color: 'var(--subtext1)' }}
              >
                分類
              </th>
              <th
                className="px-3 py-3 text-left text-xs font-medium uppercase tracking-wider sm:px-4"
                style={{ color: 'var(--subtext1)' }}
              >
                標題
              </th>
              <th
                className="hidden px-4 py-3 text-right text-xs font-medium uppercase tracking-wider sm:table-cell"
                style={{ color: 'var(--subtext1)' }}
              >
                送達
              </th>
            </tr>
          </thead>
          <tbody>
            {loading && !data ? (
              <tr>
                <td colSpan={4} className="px-4 py-12 text-center">
                  <div
                    className="mx-auto h-5 w-5 animate-spin rounded-full border-2 border-t-transparent"
                    style={{ borderColor: 'var(--accent)', borderTopColor: 'transparent' }}
                  />
                </td>
              </tr>
            ) : data?.items.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-12 text-center">
                  <Inbox size={32} className="mx-auto mb-2" style={{ color: 'var(--surface2)' }} />
                  <span className="text-sm" style={{ color: 'var(--subtext1)' }}>
                    尚無通知記錄
                  </span>
                </td>
              </tr>
            ) : (
              data?.items.map((log) => (
                <tr
                  key={log.id}
                  className="border-t transition-colors duration-150"
                  style={{
                    borderColor: 'var(--surface0)',
                    backgroundColor: 'var(--mantle)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--surface0)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--mantle)'
                  }}
                >
                  <td
                    className="whitespace-nowrap px-3 py-3 text-[13px] sm:px-4"
                    style={{ color: 'var(--subtext0)' }}
                  >
                    {new Date(log.created_at).toLocaleString('zh-TW', {
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="px-3 py-3 sm:px-4">
                    <CategoryBadge category={log.category} />
                  </td>
                  <td className="px-3 py-3 sm:px-4">
                    <div className="text-[13px] font-medium" style={{ color: 'var(--text)' }}>
                      {log.title}
                    </div>
                    {log.body && (
                      <div
                        className="mt-0.5 line-clamp-1 text-xs"
                        style={{ color: 'var(--subtext1)' }}
                      >
                        {log.body}
                      </div>
                    )}
                  </td>
                  <td
                    className="hidden whitespace-nowrap px-4 py-3 text-right text-[13px] sm:table-cell"
                    style={{ color: 'var(--subtext0)' }}
                  >
                    <span style={{ color: log.delivered > 0 ? 'var(--green)' : 'var(--subtext1)' }}>
                      {log.delivered}
                    </span>
                    <span style={{ color: 'var(--surface2)' }}> / {log.recipients}</span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between">
          <span className="text-xs" style={{ color: 'var(--subtext1)' }}>
            {data?.total} 筆通知
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="rounded-md px-3 py-1.5 text-[13px] transition-colors duration-200 disabled:opacity-30 cursor-pointer"
              style={{
                backgroundColor: 'var(--surface0)',
                color: 'var(--text)',
                minHeight: 36,
              }}
            >
              上一頁
            </button>
            <span className="px-3 text-xs" style={{ color: 'var(--subtext1)' }}>
              {page} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="rounded-md px-3 py-1.5 text-[13px] transition-colors duration-200 disabled:opacity-30 cursor-pointer"
              style={{
                backgroundColor: 'var(--surface0)',
                color: 'var(--text)',
                minHeight: 36,
              }}
            >
              下一頁
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

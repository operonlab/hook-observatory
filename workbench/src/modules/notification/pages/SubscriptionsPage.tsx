import { Monitor, RefreshCw, Smartphone } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { Subscription } from '../api'
import { deleteSubscription, listSubscriptions } from '../api'

function getScopeLabel(appScope: string): string {
  const map: Record<string, string> = {
    '/': '主應用',
    '/notification/': '通知中心',
    '/finance/': '財務',
    '/taskflow/': '任務流',
    '/ideagraph/': '知識圖',
    '/briefing/': '每日簡報',
  }
  return map[appScope] ?? appScope
}

function isMobileScope(appScope: string): boolean {
  // heuristic: non-root scopes tend to be PWA installs (often mobile)
  return appScope !== '/'
}

export default function SubscriptionsPage() {
  const [subs, setSubs] = useState<Subscription[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())

  const fetchSubs = useCallback(() => {
    setLoading(true)
    setError('')
    listSubscriptions()
      .then(setSubs)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetchSubs()
  }, [fetchSubs])

  const handleUnsubscribe = (sub: Subscription) => {
    setDeletingIds((prev) => new Set(prev).add(sub.id))
    deleteSubscription(sub.endpoint)
      .then(() => {
        setSubs((prev) => prev.filter((s) => s.id !== sub.id))
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => {
        setDeletingIds((prev) => {
          const next = new Set(prev)
          next.delete(sub.id)
          return next
        })
      })
  }

  return (
    <div className="p-4 sm:p-6 md:p-8">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-lg font-semibold" style={{ color: 'var(--text)' }}>
          訂閱裝置
        </h1>
        <button
          type="button"
          onClick={fetchSubs}
          disabled={loading}
          className="flex items-center gap-1.5 text-[12px] px-2.5 py-1.5 rounded transition-colors disabled:opacity-40 cursor-pointer"
          style={{
            backgroundColor: 'var(--surface0)',
            color: 'var(--subtext1)',
            border: '1px solid var(--surface1)',
          }}
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          重新整理
        </button>
      </div>
      <p className="mb-6 text-sm" style={{ color: 'var(--subtext1)' }}>
        已註冊推播通知的裝置列表
      </p>

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

      {loading && subs.length === 0 ? (
        <div className="text-sm" style={{ color: 'var(--subtext1)' }}>
          載入中...
        </div>
      ) : subs.length === 0 ? (
        <div
          className="rounded-lg border px-6 py-10 text-center text-sm"
          style={{
            backgroundColor: 'var(--mantle)',
            borderColor: 'var(--surface0)',
            color: 'var(--subtext1)',
          }}
        >
          目前沒有已訂閱的裝置
        </div>
      ) : (
        <div className="space-y-2">
          {subs.map((sub) => {
            const isMobile = isMobileScope(sub.app_scope)
            const Icon = isMobile ? Smartphone : Monitor
            const isDeleting = deletingIds.has(sub.id)
            const enabledChannels = Object.entries(sub.preferences)
              .filter(([, v]) => v)
              .map(([k]) => k)
            return (
              <div
                key={sub.id}
                className="flex items-center gap-3 rounded-lg border px-4 py-3"
                style={{
                  backgroundColor: 'var(--mantle)',
                  borderColor: 'var(--surface0)',
                }}
              >
                <Icon size={16} style={{ color: 'var(--subtext1)', flexShrink: 0 }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>
                      {getScopeLabel(sub.app_scope)}
                    </span>
                    {!sub.active && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded"
                        style={{
                          backgroundColor: 'color-mix(in srgb, var(--red) 10%, transparent)',
                          color: 'var(--red)',
                          border: '1px solid color-mix(in srgb, var(--red) 25%, transparent)',
                        }}
                      >
                        已停用
                      </span>
                    )}
                  </div>
                  <div
                    className="text-[11px] truncate mt-0.5"
                    style={{ color: 'var(--subtext1)' }}
                    title={sub.endpoint}
                  >
                    {sub.endpoint.length > 60 ? `${sub.endpoint.slice(0, 60)}...` : sub.endpoint}
                  </div>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    {enabledChannels.length > 0 ? (
                      enabledChannels.map((ch) => (
                        <span
                          key={ch}
                          className="text-[10px] px-1.5 py-0.5 rounded"
                          style={{
                            backgroundColor: 'color-mix(in srgb, var(--accent) 10%, transparent)',
                            color: 'var(--accent)',
                            border: '1px solid color-mix(in srgb, var(--accent) 25%, transparent)',
                          }}
                        >
                          {ch}
                        </span>
                      ))
                    ) : (
                      <span className="text-[11px]" style={{ color: 'var(--overlay0)' }}>
                        無啟用通知類別
                      </span>
                    )}
                    <span className="text-[11px]" style={{ color: 'var(--overlay0)' }}>
                      · {new Date(sub.created_at).toLocaleString('zh-TW')}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleUnsubscribe(sub)}
                  disabled={isDeleting}
                  className="text-[12px] px-2 py-1 rounded shrink-0 disabled:opacity-40 cursor-pointer"
                  style={{
                    backgroundColor: 'rgba(243,139,168,0.1)',
                    color: '#f38ba8',
                    border: '1px solid rgba(243,139,168,0.2)',
                  }}
                >
                  {isDeleting ? '處理中...' : '取消訂閱'}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

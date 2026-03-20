import { Archive, ArrowRight, Clock, Sparkles, XCircle } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { type Capture, type CaptureStats, captureApi } from './api'

const MODULE_COLORS: Record<string, string> = {
  finance: '#a6e3a1',
  taskflow: '#89b4fa',
  invest: '#f9e2af',
  ideagraph: '#cba6f7',
  intelflow: '#fab387',
}

export default function CaptureBadge() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<CaptureStats | null>(null)
  const [open, setOpen] = useState(false)
  const [recentItems, setRecentItems] = useState<Capture[]>([])
  const ref = useRef<HTMLDivElement>(null)

  const refresh = useCallback(() => {
    captureApi
      .stats()
      .then(setStats)
      .catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
    const es = new EventSource('/api/captures/events/stream')
    es.addEventListener('changed', () => refresh())
    let retryTimer: ReturnType<typeof setTimeout>
    es.onerror = () => {
      es.close()
      retryTimer = setTimeout(refresh, 10000)
    }
    return () => {
      es.close()
      clearTimeout(retryTimer)
    }
  }, [refresh])

  // Fetch recent pending items when popover opens
  useEffect(() => {
    if (open) {
      captureApi
        .list({ status: 'pending', limit: 5 })
        .then(setRecentItems)
        .catch(() => {})
    }
  }, [open])

  // Click outside to close
  useEffect(() => {
    if (!open) return
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const pending = stats?.by_status?.pending ?? 0
  const promoted = stats?.by_status?.promoted ?? 0
  const expired = stats?.by_status?.expired ?? 0

  if (pending === 0 && !open) return null

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        className="relative p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        onClick={() => setOpen((v) => !v)}
        title={`${pending} pending captures`}
      >
        <Archive
          size={18}
          className="text-gray-500 dark:text-gray-400"
          style={open ? { color: 'rgba(255, 255, 255, 0.9)' } : undefined}
        />
        {pending > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[16px] h-4 flex items-center justify-center text-[10px] font-bold text-white bg-amber-500 rounded-full px-1">
            {pending > 99 ? '99+' : pending}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-10 z-50 flex flex-col overflow-hidden shadow-2xl"
          style={{
            background: 'rgba(10, 10, 14, 0.97)',
            backdropFilter: 'blur(20px)',
            WebkitBackdropFilter: 'blur(20px)',
            border: '1px solid rgba(255, 255, 255, 0.06)',
            minWidth: 280,
            maxWidth: 340,
            borderRadius: '2px',
          }}
        >
          {/* Header */}
          <div
            className="px-4 pt-3 pb-2 flex items-center justify-between"
            style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.04)' }}
          >
            <span
              className="text-[10px] uppercase tracking-wider"
              style={{ color: 'rgba(255, 255, 255, 0.2)', letterSpacing: '0.15em' }}
            >
              Captures
            </span>
            <div className="flex items-center gap-2">
              {promoted > 0 && (
                <span className="flex items-center gap-1 text-[10px]" style={{ color: '#a6e3a1' }}>
                  <Sparkles size={10} />
                  {promoted}
                </span>
              )}
              {expired > 0 && (
                <span className="flex items-center gap-1 text-[10px]" style={{ color: '#f38ba8' }}>
                  <XCircle size={10} />
                  {expired}
                </span>
              )}
            </div>
          </div>

          {/* Recent pending items */}
          <div className="py-1">
            {recentItems.length === 0 ? (
              <div
                className="px-4 py-3 text-xs text-center"
                style={{ color: 'rgba(255, 255, 255, 0.3)' }}
              >
                No pending captures
              </div>
            ) : (
              recentItems.map((item) => {
                const color = MODULE_COLORS[item.module] ?? 'rgba(255, 255, 255, 0.4)'
                return (
                  <button
                    key={item.id}
                    type="button"
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors"
                    style={{ backgroundColor: 'transparent' }}
                    onClick={() => {
                      navigate('/capture')
                      setOpen(false)
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.04)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = 'transparent'
                    }}
                  >
                    {/* Module tag */}
                    <span
                      className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                      style={{ backgroundColor: `${color}18`, color }}
                    >
                      {item.module}
                    </span>
                    {/* Entity type */}
                    <span
                      className="flex-1 truncate text-xs"
                      style={{ color: 'rgba(255, 255, 255, 0.55)' }}
                    >
                      {item.entity_type}
                    </span>
                    {/* Completeness */}
                    <span
                      className="shrink-0 text-[10px]"
                      style={{
                        color:
                          item.completeness >= 80
                            ? '#a6e3a1'
                            : item.completeness >= 50
                              ? '#f9e2af'
                              : 'rgba(255, 255, 255, 0.3)',
                      }}
                    >
                      {Math.round(item.completeness)}%
                    </span>
                  </button>
                )
              })
            )}
          </div>

          {/* Footer */}
          <div
            className="px-4 py-2.5 flex items-center justify-between"
            style={{ borderTop: '1px solid rgba(255, 255, 255, 0.04)' }}
          >
            <span className="flex items-center gap-1 text-[10px]" style={{ color: '#f9e2af' }}>
              <Clock size={10} />
              {pending} pending
            </span>
            <button
              type="button"
              onClick={() => {
                navigate('/capture')
                setOpen(false)
              }}
              className="flex items-center gap-1 text-[11px] transition-colors"
              style={{ color: 'rgba(255, 255, 255, 0.25)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'rgba(255, 255, 255, 0.5)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'rgba(255, 255, 255, 0.25)'
              }}
            >
              查看全部 <ArrowRight size={11} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

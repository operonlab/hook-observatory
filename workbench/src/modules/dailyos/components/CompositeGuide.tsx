import { BookOpen, ChevronDown, Loader2, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { configApi } from '../api'

interface CompositeGuideProps {
  methodCount: number
}

export default function CompositeGuide({ methodCount }: CompositeGuideProps) {
  const [guide, setGuide] = useState<string | null>(null)
  const [methodNames, setMethodNames] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(true)

  const loadGuide = useCallback(() => {
    if (methodCount === 0) return
    setLoading(true)
    configApi
      .getGuide()
      .then((resp) => {
        setGuide(resp.guide)
        setMethodNames(resp.method_names)
      })
      .catch(() => setGuide(null))
      .finally(() => setLoading(false))
  }, [methodCount])

  useEffect(() => {
    loadGuide()
  }, [loadGuide])

  if (methodCount === 0) return null

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{ borderColor: 'var(--do-border)', backgroundColor: 'var(--do-bg-elevated)' }}
    >
      {/* Toggle header */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 text-left cursor-pointer"
        style={{
          backgroundColor: 'var(--do-bg-elevated)',
          transition: 'background-color 150ms ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = 'var(--do-bg-surface)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = 'var(--do-bg-elevated)'
        }}
      >
        <div className="flex items-center gap-2">
          <BookOpen size={14} style={{ color: 'var(--do-accent)' }} />
          <span className="text-[13px] font-medium" style={{ color: 'var(--do-text)' }}>
            今日方法指南
          </span>
          {methodNames.length > 0 && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded"
              style={{ color: 'var(--do-accent)', backgroundColor: 'var(--do-accent-alpha)' }}
            >
              {methodNames.join(' + ')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {guide && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setGuide(null)
                loadGuide()
              }}
              className="p-1 rounded cursor-pointer"
              style={{
                color: 'var(--do-text-muted)',
                transition: 'color 150ms ease, background-color 150ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'var(--do-accent)'
                e.currentTarget.style.backgroundColor = 'var(--do-accent-alpha)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--do-text-muted)'
                e.currentTarget.style.backgroundColor = 'transparent'
              }}
              title="重新生成"
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            </button>
          )}
          <ChevronDown
            size={14}
            style={{
              color: 'var(--do-text-muted)',
              transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 200ms ease',
            }}
          />
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4">
          {loading && !guide ? (
            <div className="flex items-center gap-2 py-3">
              <Loader2 size={16} className="animate-spin" style={{ color: 'var(--do-accent)' }} />
              <span className="text-[12px]" style={{ color: 'var(--do-text-muted)' }}>
                正在生成今日指南...
              </span>
            </div>
          ) : guide ? (
            <p
              className="text-[13px] whitespace-pre-line"
              style={{
                color: 'var(--do-text-secondary)',
                lineHeight: '1.6',
              }}
            >
              {guide}
            </p>
          ) : (
            <p className="text-[12px] py-2" style={{ color: 'var(--do-text-muted)' }}>
              無法生成指南
            </p>
          )}
        </div>
      )}
    </div>
  )
}

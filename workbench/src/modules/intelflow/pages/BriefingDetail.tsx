import { ArrowLeft, ChevronDown, ChevronUp, Database, MessageSquare, Users } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useNavigate, useParams } from 'react-router-dom'
import remarkGfm from 'remark-gfm'
import { useBriefingDetail } from '../hooks/useIntelflow'

const ANALYST_META: Record<string, { label: string; color: string }> = {
  claude: { label: 'Claude', color: '#c4a7e7' },
  codex: { label: 'Codex', color: '#9ccfd8' },
  gemini: { label: 'Gemini', color: '#f6c177' },
}

type TabId = 'analyses' | 'debate' | 'raw'

function CollapsibleSection({
  title,
  icon,
  defaultOpen = false,
  children,
}: {
  title: string
  icon: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div
      className="border"
      style={{ backgroundColor: 'var(--if-bg-elevated)', borderColor: 'var(--if-border)' }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full px-4 sm:px-5 py-3 text-left"
      >
        <h3
          className="text-xs uppercase tracking-widest flex items-center gap-2"
          style={{ color: 'var(--if-text-tertiary)' }}
        >
          {icon}
          {title}
        </h3>
        <span style={{ color: 'var(--if-text-muted)' }}>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>
      {open && <div className="px-4 sm:px-5 pb-4 sm:pb-5">{children}</div>}
    </div>
  )
}

function MarkdownBlock({ content }: { content: string }) {
  return (
    <article
      className="prose prose-invert max-w-none text-sm leading-relaxed"
      style={{ color: 'var(--if-text-secondary)', fontFamily: 'var(--if-font-ui)' }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1
              className="text-xl font-light mt-6 mb-3"
              style={{ fontFamily: 'var(--if-font-display)', color: 'var(--if-text)' }}
            >
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2
              className="text-lg font-light mt-5 mb-2"
              style={{ fontFamily: 'var(--if-font-display)', color: 'var(--if-text)' }}
            >
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-base font-medium mt-4 mb-2" style={{ color: 'var(--if-text)' }}>
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p
              className="text-sm leading-relaxed my-3"
              style={{ color: 'var(--if-text-secondary)' }}
            >
              {children}
            </p>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
              style={{ color: 'var(--if-accent)' }}
            >
              {children}
            </a>
          ),
          code: ({ className, children, ...props }) => {
            const isBlock = className?.includes('language-')
            if (isBlock) {
              return (
                <pre
                  className="overflow-x-auto p-3 my-4 text-xs"
                  style={{
                    backgroundColor: 'var(--if-bg)',
                    borderLeft: '2px solid var(--if-accent)',
                    fontFamily: 'var(--if-font-mono)',
                  }}
                >
                  <code>{children}</code>
                </pre>
              )
            }
            return (
              <code
                className="px-1 py-0.5 text-xs"
                style={{
                  backgroundColor: 'var(--if-bg-surface)',
                  color: 'var(--if-accent)',
                  fontFamily: 'var(--if-font-mono)',
                }}
                {...props}
              >
                {children}
              </code>
            )
          },
          blockquote: ({ children }) => (
            <blockquote
              className="pl-4 my-4 text-sm"
              style={{ borderLeft: '2px solid var(--if-accent)', color: 'var(--if-text-tertiary)' }}
            >
              {children}
            </blockquote>
          ),
          ul: ({ children }) => (
            <ul className="list-disc pl-5 space-y-1.5 my-3 text-sm">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 space-y-1.5 my-3 text-sm">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="leading-relaxed" style={{ color: 'var(--if-text-secondary)' }}>
              {children}
            </li>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </article>
  )
}

export default function BriefingDetail() {
  const { date } = useParams<{ date: string }>()
  const navigate = useNavigate()
  const { briefings, loading } = useBriefingDetail(date)
  const [activeTab, setActiveTab] = useState<TabId>('analyses')

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div
          className="h-6 w-6 animate-spin border-2 border-t-transparent"
          style={{ borderColor: 'var(--if-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  if (!briefings.length) {
    return (
      <div className="p-4 sm:p-6 xl:p-8 space-y-5">
        <button
          onClick={() => navigate('/intelflow/briefings')}
          className="flex items-center gap-2 text-sm min-h-[44px]"
          style={{ color: 'var(--if-text-tertiary)' }}
        >
          <ArrowLeft size={14} />
          每日簡報
        </button>
        <div
          className="border p-8 text-center text-sm"
          style={{
            backgroundColor: 'var(--if-bg-elevated)',
            borderColor: 'var(--if-border)',
            color: 'var(--if-text-dim)',
          }}
        >
          找不到 {date} 的簡報資料
        </div>
      </div>
    )
  }

  // Collect entries across all briefings, with JSONB fallback for old data
  const mergedRaw: Record<string, string> = {}
  const mergedAnalyses: Record<string, string> = {}
  let mergedDebate = ''

  for (const b of briefings) {
    // Prefer normalized entries if available
    if (b.entries && b.entries.length > 0) {
      for (const e of b.entries) {
        if (e.phase === 'raw') mergedRaw[e.key] = e.content
        else if (e.phase === 'analysis') mergedAnalyses[e.key] = e.content
        else if (e.phase === 'debate') mergedDebate += (mergedDebate ? '\n\n' : '') + e.content
      }
    } else {
      // Fallback to legacy JSONB blobs
      if (b.raw_data) Object.assign(mergedRaw, b.raw_data)
      if (b.analyses) Object.assign(mergedAnalyses, b.analyses)
      if (b.debate) mergedDebate += (mergedDebate ? '\n\n' : '') + b.debate
    }
  }

  const rawDomains = Object.keys(mergedRaw).sort()
  const analysts = Object.keys(mergedAnalyses).sort()

  const formatDate = (dateStr: string) =>
    new Date(dateStr + 'T00:00:00').toLocaleDateString('zh-TW', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      weekday: 'short',
    })

  const tabs: { id: TabId; label: string; icon: React.ReactNode; disabled?: boolean }[] = [
    { id: 'analyses', label: '分析師觀點', icon: <Users size={14} /> },
    { id: 'debate', label: '交叉辯論', icon: <MessageSquare size={14} />, disabled: !mergedDebate },
    {
      id: 'raw',
      label: '原始資料',
      icon: <Database size={14} />,
      disabled: rawDomains.length === 0,
    },
  ]

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      {/* Breadcrumb */}
      <button
        onClick={() => navigate('/intelflow/briefings')}
        className="flex items-center gap-2 text-sm min-h-[44px] sm:min-h-0"
        style={{ color: 'var(--if-text-tertiary)' }}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = 'var(--if-accent)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = 'var(--if-text-tertiary)'
        }}
      >
        <ArrowLeft size={14} />
        每日簡報
      </button>

      {/* Title */}
      <div>
        <div className="flex items-center gap-3">
          <h1
            className="text-xl sm:text-2xl xl:text-3xl font-light"
            style={{ fontFamily: 'var(--if-font-display)', color: 'var(--if-text)' }}
          >
            {formatDate(date!)}
          </h1>
          {briefings[0]?.status && briefings[0].status !== 'completed' && (
            <span
              className="text-[10px] px-2 py-0.5 border animate-pulse"
              style={{ borderColor: 'var(--if-accent)', color: 'var(--if-accent)' }}
            >
              {briefings[0].status}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 mt-2">
          <span className="text-xs" style={{ color: 'var(--if-text-dim)' }}>
            {rawDomains.length} 領域
          </span>
          <span className="text-xs" style={{ color: 'var(--if-text-dim)' }}>
            {analysts.length} 分析師
          </span>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex border-b" style={{ borderColor: 'var(--if-border)' }}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => !tab.disabled && setActiveTab(tab.id)}
            disabled={tab.disabled}
            className="flex items-center gap-1.5 px-4 py-3 text-xs transition-colors disabled:opacity-30"
            style={{
              color: activeTab === tab.id ? 'var(--if-accent)' : 'var(--if-text-tertiary)',
              borderBottom:
                activeTab === tab.id ? '2px solid var(--if-accent)' : '2px solid transparent',
            }}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'analyses' && (
        <div className="space-y-4">
          {analysts.length > 0 ? (
            analysts.map((key) => {
              const meta = ANALYST_META[key] || { label: key, color: 'var(--if-accent)' }
              return (
                <div
                  key={key}
                  className="border"
                  style={{
                    backgroundColor: 'var(--if-bg-elevated)',
                    borderColor: 'var(--if-border)',
                    borderLeftWidth: 3,
                    borderLeftColor: meta.color,
                  }}
                >
                  <div
                    className="px-4 sm:px-5 py-3 border-b"
                    style={{ borderColor: 'var(--if-border)' }}
                  >
                    <span className="text-sm font-medium" style={{ color: meta.color }}>
                      {meta.label}
                    </span>
                  </div>
                  <div className="px-4 sm:px-5 py-4">
                    <MarkdownBlock content={mergedAnalyses[key]} />
                  </div>
                </div>
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
              無分析資料
            </div>
          )}
        </div>
      )}

      {activeTab === 'debate' && (
        <div
          className="border p-4 sm:p-6"
          style={{ backgroundColor: 'var(--if-bg-elevated)', borderColor: 'var(--if-border)' }}
        >
          <MarkdownBlock content={mergedDebate} />
        </div>
      )}

      {activeTab === 'raw' && (
        <div className="space-y-3">
          {rawDomains.map((domain) => (
            <CollapsibleSection key={domain} title={domain} icon={<Database size={12} />}>
              <MarkdownBlock content={mergedRaw[domain]} />
            </CollapsibleSection>
          ))}
        </div>
      )}
    </div>
  )
}

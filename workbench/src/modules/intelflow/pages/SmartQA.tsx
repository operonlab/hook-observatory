import { FileText, MessageCircle, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import RelevanceBadge from '../components/RelevanceBadge'
import { useSearch } from '../hooks/useIntelflow'

export default function SmartQA() {
  const navigate = useNavigate()
  const { query, results, loading, setQuery, search, clear } = useSearch()
  const [inputValue, setInputValue] = useState('')
  const hasResults = results.length > 0

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (inputValue.trim()) {
      search(inputValue.trim())
    }
  }

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-6 sm:space-y-8">
      {/* Header */}
      <div>
        <h1
          className="text-2xl sm:text-3xl font-light"
          style={{ fontFamily: 'var(--if-font-display)', color: 'var(--if-text)' }}
        >
          智能問答
        </h1>
        <p className="text-sm mt-1 sm:mt-2" style={{ color: 'var(--if-text-tertiary)' }}>
          基於語意搜尋，從研究報告中找到最相關的答案
        </p>
      </div>

      {/* Search input */}
      <form onSubmit={handleSubmit}>
        <div
          className="flex items-center gap-2 sm:gap-3 border px-3 sm:px-4 py-3"
          style={{
            backgroundColor: 'var(--if-bg-elevated)',
            borderColor: hasResults ? 'var(--if-accent)' : 'var(--if-border)',
          }}
        >
          <MessageCircle size={16} style={{ color: 'var(--if-text-muted)', flexShrink: 0 }} />
          <input
            type="text"
            placeholder="輸入你的問題..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--if-text-dim)] min-w-0"
            style={{ color: 'var(--if-text)' }}
          />
          <button
            type="submit"
            disabled={loading || !inputValue.trim()}
            className="flex items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-2 text-sm disabled:opacity-40 shrink-0 min-h-[36px]"
            style={{
              backgroundColor: 'var(--if-accent)',
              color: 'var(--if-text-on-accent)',
            }}
          >
            {loading ? (
              <div
                className="h-3.5 w-3.5 animate-spin border border-t-transparent"
                style={{ borderColor: 'var(--if-text-on-accent)', borderTopColor: 'transparent' }}
              />
            ) : (
              <Sparkles size={13} />
            )}
            <span className="hidden xs:inline">提問</span>
          </button>
        </div>
      </form>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center h-32">
          <div className="flex items-center gap-3">
            <div
              className="h-5 w-5 animate-spin border-2 border-t-transparent"
              style={{ borderColor: 'var(--if-accent)', borderTopColor: 'transparent' }}
            />
            <span className="text-sm" style={{ color: 'var(--if-text-tertiary)' }}>
              正在搜尋報告庫...
            </span>
          </div>
        </div>
      )}

      {hasResults && !loading && (
        <div className="space-y-5 sm:space-y-6">
          {/* AI answer summary */}
          <div
            className="border p-4 sm:p-6"
            style={{
              backgroundColor: 'var(--if-ai-bg)',
              borderColor: 'var(--if-ai-border)',
            }}
          >
            <div className="flex items-start gap-2 sm:gap-3">
              <Sparkles
                size={15}
                style={{ color: 'var(--if-score-high)', marginTop: 2, flexShrink: 0 }}
              />
              <div className="space-y-1.5 sm:space-y-2 min-w-0">
                <p className="text-sm" style={{ color: 'var(--if-text-secondary)' }}>
                  找到 <strong style={{ color: 'var(--if-text)' }}>{results.length}</strong>{' '}
                  篇相關報告
                  {query && (
                    <span>
                      ，基於查詢「<span style={{ color: 'var(--if-accent)' }}>{query}</span>」
                    </span>
                  )}
                </p>
                <p className="text-xs" style={{ color: 'var(--if-text-dim)' }}>
                  基於 {results.length} 篇報告的語意分析
                </p>
              </div>
            </div>
          </div>

          {/* Results heading */}
          <div className="flex items-center justify-between">
            <h2
              className="text-base sm:text-lg font-light"
              style={{ fontFamily: 'var(--if-font-display)', color: 'var(--if-text)' }}
            >
              參考報告
            </h2>
            <button
              onClick={() => {
                clear()
                setInputValue('')
              }}
              className="text-xs min-h-[36px] px-2"
              style={{ color: 'var(--if-text-dim)' }}
            >
              清除搜尋
            </button>
          </div>

          {/* Results list */}
          <div className="space-y-2 sm:space-y-3">
            {results.map((result) => (
              <button
                key={result.report.id}
                onClick={() => navigate(`/intelflow/reports/${result.report.id}`)}
                className="flex w-full items-start gap-3 sm:gap-4 border p-4 text-left transition-colors min-h-[72px]"
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
                <FileText
                  size={15}
                  style={{ color: 'var(--if-text-muted)', marginTop: 2, flexShrink: 0 }}
                />
                <div className="flex-1 min-w-0 space-y-1.5 sm:space-y-2">
                  {/* Title + badge — wrap on mobile */}
                  <div className="flex items-start justify-between gap-2">
                    <span
                      className="text-sm font-medium leading-snug"
                      style={{ color: 'var(--if-text)' }}
                    >
                      {result.report.title}
                    </span>
                    <RelevanceBadge score={result.score} />
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs" style={{ color: 'var(--if-text-dim)' }}>
                      {new Date(result.report.created_at).toLocaleDateString('zh-TW')}
                    </span>
                    {result.report.tags.slice(0, 3).map((tag) => (
                      <span
                        key={tag}
                        className="text-[10px] px-1.5 py-0.5 border"
                        style={{
                          borderColor: 'var(--if-border)',
                          color: 'var(--if-text-tertiary)',
                        }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!hasResults && !loading && query && (
        <div
          className="flex flex-col items-center justify-center py-12 border"
          style={{
            backgroundColor: 'var(--if-bg-elevated)',
            borderColor: 'var(--if-border)',
          }}
        >
          <p className="text-sm" style={{ color: 'var(--if-text-dim)' }}>
            沒有找到與「{query}」相關的報告
          </p>
        </div>
      )}
    </div>
  )
}

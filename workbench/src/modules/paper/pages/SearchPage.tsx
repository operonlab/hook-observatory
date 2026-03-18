import { BookOpen, Search as SearchIcon, X } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import RelevanceBadge from '../components/RelevanceBadge'
import { useSearch } from '../hooks/usePaper'

export default function SearchPage() {
  const { query, results, loading, search, clear } = useSearch()
  const [input, setInput] = useState(query)
  const navigate = useNavigate()

  const handleSearch = () => {
    if (input.trim()) search(input.trim())
  }

  const handleClear = () => {
    setInput('')
    clear()
  }

  return (
    <div style={{ padding: 'clamp(20px, 4vw, 40px)', maxWidth: 1100, margin: '0 auto' }}>
      {/* Page header */}
      <header style={{ marginBottom: 28 }}>
        <h1
          style={{
            fontFamily: 'var(--pp-font-display)',
            fontSize: 'clamp(1.5rem, 3vw, 2rem)',
            fontWeight: 500,
            color: 'var(--pp-text)',
            letterSpacing: '-0.01em',
            marginBottom: 4,
          }}
        >
          語意搜尋
        </h1>
        <p style={{ fontSize: '12px', color: 'var(--pp-text-muted)' }}>
          向量相似度搜尋 — 以語意概念而非關鍵詞匹配
        </p>
      </header>

      {/* Search input */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 0,
          border: '1px solid var(--pp-border)',
          backgroundColor: 'var(--pp-bg-surface)',
          marginBottom: 24,
          transition: 'border-color 0.15s',
        }}
        onFocusCapture={(e) => {
          e.currentTarget.style.borderColor = 'var(--pp-accent)'
        }}
        onBlurCapture={(e) => {
          e.currentTarget.style.borderColor = 'var(--pp-border)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', padding: '0 14px' }}>
          <SearchIcon size={15} style={{ color: 'var(--pp-text-muted)', flexShrink: 0 }} />
        </div>
        <input
          type="text"
          placeholder="輸入研究主題、關鍵概念或問題..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          style={{
            flex: 1,
            padding: '12px 0',
            fontSize: '13px',
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: 'var(--pp-text)',
            fontFamily: 'var(--pp-font-ui)',
          }}
        />
        {(input || results.length > 0) && (
          <button
            onClick={handleClear}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 10px',
              color: 'var(--pp-text-dim)',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              transition: 'color 0.12s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--pp-text-secondary)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--pp-text-dim)')}
          >
            <X size={14} />
          </button>
        )}
        <button
          onClick={handleSearch}
          disabled={loading || !input.trim()}
          style={{
            padding: '12px 20px',
            fontSize: '12px',
            border: 'none',
            borderLeft: '1px solid var(--pp-border)',
            backgroundColor: input.trim() ? 'var(--pp-accent-alpha)' : 'transparent',
            color: input.trim() ? 'var(--pp-accent)' : 'var(--pp-text-dim)',
            cursor: input.trim() && !loading ? 'pointer' : 'not-allowed',
            fontFamily: 'var(--pp-font-ui)',
            letterSpacing: '0.04em',
            transition: 'background-color 0.12s, color 0.12s',
            whiteSpace: 'nowrap',
          }}
        >
          {loading ? '搜尋中...' : '搜尋'}
        </button>
      </div>

      {/* Loading state */}
      {loading && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '40px 0',
            color: 'var(--pp-text-muted)',
            fontSize: '12px',
          }}
        >
          <div
            style={{
              width: 18,
              height: 18,
              border: '2px solid var(--pp-accent)',
              borderTopColor: 'transparent',
              animation: 'spin 0.8s linear infinite',
            }}
          />
          向量索引搜尋中...
        </div>
      )}

      {/* Results */}
      {!loading && results.length > 0 && (
        <div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 12,
              paddingBottom: 8,
              borderBottom: '1px solid var(--pp-border)',
            }}
          >
            <p
              style={{
                fontSize: '11px',
                color: 'var(--pp-text-muted)',
                letterSpacing: '0.06em',
              }}
            >
              找到 {results.length} 篇相關論文
            </p>
            <span
              style={{
                fontSize: '10px',
                color: 'var(--pp-text-dim)',
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
              }}
            >
              按相似度排序
            </span>
          </div>

          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 0,
              border: '1px solid var(--pp-border)',
            }}
          >
            {results.map((r, idx) => {
              const scoreLabel = `${Math.round(r.score * 100)}%`
              const articleDate = r.article.created_at
                ? new Date(r.article.created_at).toLocaleDateString('zh-TW', {
                    year: 'numeric',
                    month: '2-digit',
                  })
                : null

              return (
                <button
                  key={r.article.id}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 0,
                    borderBottom: idx < results.length - 1 ? '1px solid var(--pp-border)' : 'none',
                    backgroundColor: 'var(--pp-bg-elevated)',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'background-color 0.12s',
                    border: 'none',
                    width: '100%',
                  }}
                  onClick={() => navigate(`/paper/articles/${r.article.id}`)}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--pp-bg-surface)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--pp-bg-elevated)'
                  }}
                >
                  {/* Score indicator bar */}
                  <div
                    style={{
                      width: 3,
                      alignSelf: 'stretch',
                      flexShrink: 0,
                      backgroundColor: `rgba(137, 180, 250, ${r.score})`,
                    }}
                  />

                  {/* Content */}
                  <div style={{ flex: 1, padding: '13px 14px 12px', minWidth: 0 }}>
                    <p
                      style={{
                        fontFamily: 'var(--pp-font-display)',
                        fontSize: '0.975rem',
                        fontWeight: 500,
                        color: 'var(--pp-text)',
                        lineHeight: 1.4,
                        letterSpacing: '0.005em',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        marginBottom: 7,
                      }}
                    >
                      {r.article.title}
                    </p>

                    {/* Digest one-liner */}
                    {r.digest_one_liner && (
                      <p
                        style={{
                          fontSize: '12px',
                          lineHeight: 1.55,
                          color: 'var(--pp-text-muted)',
                          marginBottom: 8,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                        }}
                      >
                        {r.digest_one_liner}
                      </p>
                    )}

                    <div
                      style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}
                    >
                      {articleDate && (
                        <span style={{ fontSize: '11px', color: 'var(--pp-text-dim)' }}>
                          {articleDate}
                        </span>
                      )}
                      {r.article.categories.slice(0, 2).map((cat) => (
                        <span
                          key={cat}
                          style={{
                            fontSize: '10px',
                            padding: '1px 6px',
                            border: '1px solid var(--pp-border)',
                            color: 'var(--pp-text-dim)',
                          }}
                        >
                          {cat}
                        </span>
                      ))}
                      {r.workshop_relevance && <RelevanceBadge relevance={r.workshop_relevance} />}
                    </div>
                  </div>

                  {/* Score badge */}
                  <div
                    style={{
                      padding: '13px 14px',
                      alignSelf: 'center',
                      flexShrink: 0,
                      textAlign: 'right',
                    }}
                  >
                    <span
                      style={{
                        fontSize: '13px',
                        fontFamily: 'var(--pp-font-mono)',
                        color: 'var(--pp-accent)',
                        opacity: 0.7 + r.score * 0.3,
                      }}
                    >
                      {scoreLabel}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* No results */}
      {!loading && results.length === 0 && query && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '64px 20px',
            gap: 10,
            border: '1px solid var(--pp-border)',
            color: 'var(--pp-text-dim)',
          }}
        >
          <SearchIcon size={24} />
          <p style={{ fontSize: '13px' }}>沒有找到相關論文</p>
          <p style={{ fontSize: '11px', color: 'var(--pp-text-dim)' }}>
            嘗試使用不同的概念或主題描述
          </p>
        </div>
      )}

      {/* Empty / initial state */}
      {!loading && results.length === 0 && !query && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '64px 20px',
            gap: 14,
            color: 'var(--pp-text-dim)',
          }}
        >
          <BookOpen size={32} style={{ opacity: 0.4 }} />
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: '13px', marginBottom: 5 }}>輸入研究主題進行語意搜尋</p>
            <p style={{ fontSize: '11px', color: 'var(--pp-text-dim)' }}>
              支援自然語言 — 如「多智能體協調機制」、「transformer 注意力效率優化」
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

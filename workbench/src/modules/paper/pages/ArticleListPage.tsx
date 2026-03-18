import { ChevronLeft, ChevronRight, Filter, SortDesc } from 'lucide-react'
import { useState } from 'react'
import ArticleCard from '../components/ArticleCard'
import { useArticles } from '../hooks/usePaper'

const SORT_OPTIONS = [
  { mode: 'date-desc' as const, label: '最新' },
  { mode: 'date-asc' as const, label: '最早' },
  { mode: 'title-asc' as const, label: '標題' },
]

export default function ArticleListPage() {
  const {
    articles,
    total,
    page,
    pageSize,
    loading,
    activeCategory,
    activeTag,
    allCategories,
    allTags,
    fetchArticles,
    deleteArticle,
    setActiveCategory,
    setActiveTag,
  } = useArticles()

  const [searchText, setSearchText] = useState('')
  const [sortMode, setSortMode] = useState<'date-desc' | 'date-asc' | 'title-asc'>('date-desc')
  const [showTagFilter, setShowTagFilter] = useState(false)

  const filtered = searchText
    ? articles.filter((a) => a.title.toLowerCase().includes(searchText.toLowerCase()))
    : articles

  const sorted = [...filtered].sort((a, b) => {
    switch (sortMode) {
      case 'date-desc':
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      case 'date-asc':
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      case 'title-asc':
        return a.title.localeCompare(b.title, 'zh-TW')
    }
  })

  const totalPages = Math.ceil(total / pageSize)

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '40vh',
          gap: 10,
          color: 'var(--pp-text-muted)',
          fontSize: '12px',
        }}
      >
        <div
          style={{
            width: 20,
            height: 20,
            border: '2px solid var(--pp-accent)',
            borderTopColor: 'transparent',
            animation: 'spin 0.8s linear infinite',
          }}
        />
        載入中...
      </div>
    )
  }

  return (
    <div style={{ padding: 'clamp(20px, 4vw, 40px)', maxWidth: 1100, margin: '0 auto' }}>
      {/* Page header */}
      <header style={{ marginBottom: 24 }}>
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
          論文庫
        </h1>
        <p style={{ fontSize: '12px', color: 'var(--pp-text-muted)' }}>共 {total} 篇</p>
      </header>

      {/* Toolbar */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          marginBottom: 16,
          flexWrap: 'wrap',
        }}
      >
        {/* Search input */}
        <input
          type="text"
          placeholder="搜尋論文標題..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          style={{
            flex: '1 1 200px',
            padding: '8px 12px',
            fontSize: '12.5px',
            border: '1px solid var(--pp-border)',
            backgroundColor: 'var(--pp-bg-surface)',
            color: 'var(--pp-text)',
            outline: 'none',
            fontFamily: 'var(--pp-font-ui)',
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--pp-accent)')}
          onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--pp-border)')}
        />

        {/* Sort buttons */}
        <div style={{ display: 'flex', gap: 1 }}>
          <span
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '0 10px',
              fontSize: '11px',
              color: 'var(--pp-text-dim)',
              border: '1px solid var(--pp-border)',
              borderRight: 'none',
              backgroundColor: 'var(--pp-bg-elevated)',
            }}
          >
            <SortDesc size={11} />
            排序
          </span>
          {SORT_OPTIONS.map(({ mode, label }) => (
            <button
              key={mode}
              onClick={() => setSortMode(mode)}
              style={{
                padding: '8px 12px',
                fontSize: '11px',
                border: '1px solid var(--pp-border)',
                borderLeft: mode === SORT_OPTIONS[0].mode ? '1px solid var(--pp-border)' : 'none',
                backgroundColor:
                  sortMode === mode ? 'var(--pp-accent-alpha)' : 'var(--pp-bg-surface)',
                color: sortMode === mode ? 'var(--pp-accent)' : 'var(--pp-text-tertiary)',
                cursor: 'pointer',
                fontFamily: 'var(--pp-font-ui)',
                transition: 'color 0.12s, background-color 0.12s',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Tag filter toggle */}
        {allTags.length > 0 && (
          <button
            onClick={() => setShowTagFilter(!showTagFilter)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 12px',
              fontSize: '11px',
              border: `1px solid ${showTagFilter ? 'var(--pp-accent)' : 'var(--pp-border)'}`,
              backgroundColor: showTagFilter ? 'var(--pp-accent-alpha)' : 'transparent',
              color: showTagFilter ? 'var(--pp-accent)' : 'var(--pp-text-tertiary)',
              cursor: 'pointer',
              fontFamily: 'var(--pp-font-ui)',
            }}
          >
            <Filter size={11} />
            標籤
            {activeTag && (
              <span
                style={{
                  width: 5,
                  height: 5,
                  backgroundColor: 'var(--pp-accent)',
                  display: 'inline-block',
                }}
              />
            )}
          </button>
        )}
      </div>

      {/* Category filter row */}
      {allCategories.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            marginBottom: 12,
            flexWrap: 'wrap',
          }}
        >
          <span
            style={{
              fontSize: '10px',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--pp-text-dim)',
              flexShrink: 0,
            }}
          >
            分類
          </span>
          {[null, ...allCategories].map((cat) => {
            const isActive = cat === null ? !activeCategory : activeCategory === cat
            return (
              <button
                key={cat ?? '__all__'}
                onClick={() => setActiveCategory(cat)}
                style={{
                  padding: '3px 10px',
                  fontSize: '11px',
                  border: `1px solid ${isActive ? 'var(--pp-accent)' : 'var(--pp-border)'}`,
                  backgroundColor: isActive ? 'var(--pp-accent)' : 'transparent',
                  color: isActive ? 'var(--pp-text-on-accent)' : 'var(--pp-text-secondary)',
                  cursor: 'pointer',
                  fontFamily: 'var(--pp-font-ui)',
                  letterSpacing: '0.02em',
                  transition: 'all 0.12s',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.borderColor = 'var(--pp-accent)'
                    e.currentTarget.style.color = 'var(--pp-accent)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.borderColor = 'var(--pp-border)'
                    e.currentTarget.style.color = 'var(--pp-text-secondary)'
                  }
                }}
              >
                {cat ?? '全部'}
              </button>
            )
          })}
        </div>
      )}

      {/* Tag filter row */}
      {showTagFilter && allTags.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            marginBottom: 12,
            padding: '10px 12px',
            border: '1px solid var(--pp-border)',
            backgroundColor: 'var(--pp-bg-elevated)',
            flexWrap: 'wrap',
          }}
        >
          <span
            style={{
              fontSize: '10px',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--pp-text-dim)',
              flexShrink: 0,
            }}
          >
            標籤
          </span>
          {allTags.map((tag) => {
            const isActive = activeTag === tag
            return (
              <button
                key={tag}
                onClick={() => setActiveTag(isActive ? null : tag)}
                style={{
                  padding: '2px 8px',
                  fontSize: '10px',
                  border: `1px solid ${isActive ? 'var(--pp-accent)' : 'var(--pp-border)'}`,
                  backgroundColor: isActive ? 'var(--pp-accent-alpha)' : 'transparent',
                  color: isActive ? 'var(--pp-accent)' : 'var(--pp-text-tertiary)',
                  cursor: 'pointer',
                  fontFamily: 'var(--pp-font-ui)',
                }}
              >
                #{tag}
              </button>
            )
          })}
        </div>
      )}

      {/* Article list */}
      {sorted.length === 0 ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '64px 20px',
            border: '1px solid var(--pp-border)',
            color: 'var(--pp-text-muted)',
            fontSize: '13px',
          }}
        >
          {searchText ? '沒有符合的論文' : '尚無論文'}
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
            gap: 1,
          }}
        >
          {sorted.map((article) => (
            <ArticleCard
              key={article.id}
              article={article}
              onDelete={() => deleteArticle(article.id)}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginTop: 20,
          }}
        >
          <button
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '7px 14px',
              fontSize: '12px',
              border: '1px solid var(--pp-border)',
              backgroundColor: 'transparent',
              color: page <= 1 ? 'var(--pp-text-dim)' : 'var(--pp-text-secondary)',
              cursor: page <= 1 ? 'not-allowed' : 'pointer',
              fontFamily: 'var(--pp-font-ui)',
            }}
            disabled={page <= 1}
            onClick={() => fetchArticles(page - 1)}
          >
            <ChevronLeft size={13} /> 上一頁
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              style={{
                fontSize: '11px',
                color: 'var(--pp-text-muted)',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {page} / {totalPages}
            </span>
          </div>

          <button
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '7px 14px',
              fontSize: '12px',
              border: '1px solid var(--pp-border)',
              backgroundColor: 'transparent',
              color: page >= totalPages ? 'var(--pp-text-dim)' : 'var(--pp-text-secondary)',
              cursor: page >= totalPages ? 'not-allowed' : 'pointer',
              fontFamily: 'var(--pp-font-ui)',
            }}
            disabled={page >= totalPages}
            onClick={() => fetchArticles(page + 1)}
          >
            下一頁 <ChevronRight size={13} />
          </button>
        </div>
      )}
    </div>
  )
}

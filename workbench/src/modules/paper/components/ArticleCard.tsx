import { Trash2, Users } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { Article, ArticleBrief } from '../types'
import RelevanceBadge from './RelevanceBadge'

interface ArticleCardProps {
  article: Article | ArticleBrief
  onDelete?: (id: string) => void
}

export default function ArticleCard({ article, onDelete }: ArticleCardProps) {
  const navigate = useNavigate()

  const year = article.year
  const hasDigest = 'digest' in article && (article as Article).digest != null
  const digestRelevance = hasDigest ? (article as Article).digest?.workshop_relevance : null
  const firstTwoAuthors = article.authors.slice(0, 2)
  const extraAuthors = article.authors.length - 2

  return (
    <div
      className="group"
      style={{
        display: 'flex',
        flexDirection: 'column',
        border: '1px solid var(--pp-border)',
        borderLeft: `3px solid ${hasDigest ? 'var(--pp-accent)' : 'var(--pp-border)'}`,
        backgroundColor: 'var(--pp-bg-elevated)',
        cursor: 'pointer',
        transition: 'background-color 0.12s, border-color 0.15s',
        height: '100%',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = 'var(--pp-bg-surface)'
        e.currentTarget.style.borderColor = 'var(--pp-accent)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'var(--pp-bg-elevated)'
        e.currentTarget.style.borderColor = 'var(--pp-border)'
        e.currentTarget.style.borderLeftColor = hasDigest ? 'var(--pp-accent)' : 'var(--pp-border)'
      }}
      onClick={() => navigate(`/paper/articles/${article.id}`)}
    >
      {/* Content */}
      <div style={{ flex: 1, padding: '14px 14px 10px' }}>
        {/* Title — allow 2 lines */}
        <p
          style={{
            fontFamily: 'var(--pp-font-display)',
            fontSize: '0.95rem',
            fontWeight: 500,
            color: 'var(--pp-text)',
            lineHeight: 1.45,
            letterSpacing: '0.005em',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
            marginBottom: 8,
          }}
        >
          {article.title}
        </p>

        {/* Authors */}
        {firstTwoAuthors.length > 0 && (
          <p
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              fontSize: '11px',
              color: 'var(--pp-text-tertiary)',
              marginBottom: 8,
            }}
          >
            <Users size={10} style={{ flexShrink: 0 }} />
            {firstTwoAuthors.map((a) => a.name).join(', ')}
            {extraAuthors > 0 && ` +${extraAuthors}`}
          </p>
        )}

        {/* Category pills */}
        {article.categories.length > 0 && (
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {article.categories.slice(0, 3).map((cat) => (
              <span
                key={cat}
                style={{
                  fontSize: '10px',
                  padding: '1px 7px',
                  border: '1px solid var(--pp-border)',
                  color: 'var(--pp-text-dim)',
                  letterSpacing: '0.03em',
                }}
              >
                {cat}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Footer — year + relevance + actions */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 14px',
          borderTop: '1px solid var(--pp-border)',
        }}
      >
        {year && (
          <span
            style={{
              fontSize: '11px',
              color: 'var(--pp-text-muted)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {year}
          </span>
        )}

        {hasDigest && digestRelevance && <RelevanceBadge relevance={digestRelevance} />}

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 4 }}>
          {onDelete && (
            <button
              className="opacity-0 group-hover:opacity-100"
              style={{
                padding: '4px',
                color: 'var(--pp-text-dim)',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                transition: 'color 0.12s, opacity 0.12s',
              }}
              onClick={(e) => {
                e.stopPropagation()
                onDelete(article.id)
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'var(--pp-score-low)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--pp-text-dim)'
              }}
            >
              <Trash2 size={12} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

import {
  ArrowLeft,
  BookOpen,
  Calendar,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileText,
  Info,
  MessageSquare,
  Send,
  Tag,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import DigestPanel from '../components/DigestPanel'
import { useArticleDetail } from '../hooks/usePaper'
import type { AnnotationCreate } from '../types'

const ANNOTATION_TYPES = [
  { value: 'note', label: '筆記' },
  { value: 'highlight', label: '重點' },
  { value: 'question', label: '疑問' },
  { value: 'synthesis', label: '綜合' },
  { value: 'action-taken', label: '已行動' },
] as const

const ANNOTATION_TYPE_COLORS: Record<string, string> = {
  note: 'var(--pp-accent)',
  highlight: '#f9e2af',
  question: '#fab387',
  synthesis: '#cba6f7',
  'action-taken': '#a6e3a1',
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        fontSize: '10px',
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        color: 'var(--pp-text-dim)',
        fontFamily: 'var(--pp-font-ui)',
      }}
    >
      {children}
    </span>
  )
}

export default function ArticleDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { article, loading, digest, digestLoading, annotations, addAnnotation } =
    useArticleDetail(id)

  const [newAnnotation, setNewAnnotation] = useState('')
  const [annotationType, setAnnotationType] = useState<AnnotationCreate['annotation_type']>('note')
  const [showFullText, setShowFullText] = useState(false)
  const [showMobileInfo, setShowMobileInfo] = useState(false)

  const handleSubmitAnnotation = async () => {
    if (!newAnnotation.trim()) return
    await addAnnotation({ note: newAnnotation.trim(), annotation_type: annotationType })
    setNewAnnotation('')
  }

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

  if (!article) {
    return (
      <div style={{ padding: 'clamp(20px, 4vw, 40px)' }}>
        <button
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: '12px',
            color: 'var(--pp-accent)',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            marginBottom: 24,
          }}
          onClick={() => navigate('/paper/articles')}
        >
          <ArrowLeft size={13} /> 返回列表
        </button>
        <p style={{ color: 'var(--pp-text-muted)', fontSize: '13px' }}>找不到該論文</p>
      </div>
    )
  }

  const dateStr = new Date(article.created_at).toLocaleDateString('zh-TW', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })

  return (
    <div style={{ padding: 'clamp(20px, 4vw, 40px)', maxWidth: 1100, margin: '0 auto' }}>
      {/* Back nav */}
      <button
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: '11.5px',
          color: 'var(--pp-text-muted)',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          marginBottom: 28,
          letterSpacing: '0.03em',
          transition: 'color 0.12s',
        }}
        onClick={() => navigate('/paper/articles')}
        onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--pp-accent)')}
        onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--pp-text-muted)')}
      >
        <ArrowLeft size={13} /> 論文庫
      </button>

      {/* Title block */}
      <div style={{ marginBottom: 32 }}>
        {/* Categories */}
        {article.categories.length > 0 && (
          <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
            {article.categories.map((cat) => (
              <span
                key={cat}
                style={{
                  fontSize: '10px',
                  padding: '2px 8px',
                  border: '1px solid var(--pp-border)',
                  color: 'var(--pp-text-dim)',
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                }}
              >
                {cat}
              </span>
            ))}
          </div>
        )}

        <h1
          style={{
            fontFamily: 'var(--pp-font-display)',
            fontSize: 'clamp(1.4rem, 3.5vw, 2.1rem)',
            fontWeight: 500,
            lineHeight: 1.35,
            letterSpacing: '0.005em',
            color: 'var(--pp-text)',
            marginBottom: 14,
          }}
        >
          {article.title}
        </h1>

        {/* Meta strip */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            flexWrap: 'wrap',
            paddingBottom: 16,
            borderBottom: '1px solid var(--pp-border)',
          }}
        >
          {article.year && (
            <span
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                fontSize: '12px',
                color: 'var(--pp-text-muted)',
              }}
            >
              <Calendar size={12} />
              {article.year}
            </span>
          )}
          {article.authors && article.authors.length > 0 && (
            <span
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                fontSize: '12px',
                color: 'var(--pp-text-muted)',
              }}
            >
              <Users size={12} />
              {article.authors
                .slice(0, 3)
                .map((a) => a.name)
                .join(', ')}
              {article.authors.length > 3 && ` 等 ${article.authors.length} 人`}
            </span>
          )}
          {article.journal && (
            <span
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                fontSize: '12px',
                color: 'var(--pp-text-muted)',
              }}
            >
              <BookOpen size={12} />
              <em>{article.journal}</em>
            </span>
          )}
          <span
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              fontSize: '11px',
              color: 'var(--pp-text-dim)',
              marginLeft: 'auto',
            }}
          >
            <Calendar size={11} />
            建檔 {dateStr}
          </span>
        </div>
      </div>

      {/* Mobile: paper info toggle (hidden on lg+) */}
      <div className="lg:hidden" style={{ marginBottom: 20 }}>
        <button
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 14px',
            fontSize: '11.5px',
            backgroundColor: 'var(--pp-bg-surface)',
            border: '1px solid var(--pp-border)',
            color: 'var(--pp-text-secondary)',
            cursor: 'pointer',
            fontFamily: 'var(--pp-font-ui)',
            letterSpacing: '0.02em',
          }}
          onClick={() => setShowMobileInfo(!showMobileInfo)}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <Info size={12} />
            論文資訊 · 外部連結
          </span>
          {showMobileInfo ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
        {showMobileInfo && (
          <div
            style={{
              border: '1px solid var(--pp-border)',
              borderTop: 'none',
              backgroundColor: 'var(--pp-bg-elevated)',
              padding: '14px',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            {/* Compact metadata rows */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px 20px' }}>
              {article.arxiv_id && (
                <div>
                  <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 2 }}>
                    arXiv
                  </p>
                  <a
                    href={`https://arxiv.org/abs/${article.arxiv_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontSize: '12px',
                      color: 'var(--pp-accent)',
                      textDecoration: 'none',
                      fontFamily: 'var(--pp-font-mono)',
                    }}
                  >
                    {article.arxiv_id}
                  </a>
                </div>
              )}
              {article.doi && (
                <div>
                  <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 2 }}>
                    DOI
                  </p>
                  <p
                    style={{
                      fontSize: '11.5px',
                      color: 'var(--pp-text-secondary)',
                      fontFamily: 'var(--pp-font-mono)',
                      wordBreak: 'break-all',
                    }}
                  >
                    {article.doi}
                  </p>
                </div>
              )}
              {article.year && (
                <div>
                  <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 2 }}>
                    年份
                  </p>
                  <p style={{ fontSize: '12px', color: 'var(--pp-text-secondary)' }}>
                    {article.year}
                  </p>
                </div>
              )}
              {article.journal && (
                <div>
                  <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 2 }}>
                    期刊 / 會議
                  </p>
                  <p
                    style={{
                      fontSize: '12px',
                      color: 'var(--pp-text-secondary)',
                      fontStyle: 'italic',
                    }}
                  >
                    {article.journal}
                  </p>
                </div>
              )}
            </div>
            {/* Authors (full list on mobile) */}
            {article.authors && article.authors.length > 0 && (
              <div>
                <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 2 }}>
                  作者
                </p>
                <p style={{ fontSize: '12px', color: 'var(--pp-text-secondary)', lineHeight: 1.5 }}>
                  {article.authors.map((a) => a.name).join(', ')}
                </p>
              </div>
            )}
            {/* External links */}
            {(article.source_url || article.pdf_url) && (
              <div
                style={{
                  display: 'flex',
                  gap: 16,
                  paddingTop: 6,
                  borderTop: '1px solid var(--pp-border)',
                }}
              >
                {article.source_url && (
                  <a
                    href={article.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      fontSize: '11.5px',
                      color: 'var(--pp-accent)',
                      textDecoration: 'none',
                    }}
                  >
                    <ExternalLink size={11} /> 原始頁面
                  </a>
                )}
                {article.pdf_url && (
                  <a
                    href={article.pdf_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      fontSize: '11.5px',
                      color: 'var(--pp-accent)',
                      textDecoration: 'none',
                    }}
                  >
                    <ExternalLink size={11} /> 下載 PDF
                  </a>
                )}
              </div>
            )}
            {/* Tags */}
            {article.tags.length > 0 && (
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 6,
                  paddingTop: 6,
                  borderTop: '1px solid var(--pp-border)',
                }}
              >
                {article.tags.map((tag) => (
                  <span
                    key={tag}
                    style={{
                      fontSize: '10px',
                      padding: '2px 8px',
                      border: '1px solid rgba(137, 180, 250, 0.35)',
                      color: 'var(--pp-accent)',
                      backgroundColor: 'rgba(137, 180, 250, 0.06)',
                    }}
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_300px]">
        {/* Left: main content */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
          {/* Abstract + Digest side by side on lg+ */}
          <div
            className={`flex flex-col gap-5 ${digest || digestLoading ? 'lg:grid lg:grid-cols-2' : ''}`}
          >
            {/* Abstract */}
            {article.abstract && (
              <div
                style={{
                  border: '1px solid var(--pp-border)',
                  backgroundColor: 'var(--pp-bg-elevated)',
                  alignSelf: 'flex-start',
                }}
                className="lg:self-stretch"
              >
                <div
                  style={{
                    padding: '10px 16px',
                    borderBottom: '1px solid var(--pp-border)',
                    backgroundColor: 'var(--pp-bg-surface)',
                  }}
                >
                  <SectionLabel>摘要</SectionLabel>
                </div>
                <p
                  style={{
                    padding: '16px',
                    fontSize: '13px',
                    lineHeight: 1.75,
                    color: 'var(--pp-text-secondary)',
                    letterSpacing: '0.01em',
                  }}
                >
                  {article.abstract}
                </p>
              </div>
            )}

            {/* Digest — sits beside abstract on lg+ */}
            {digestLoading ? (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '24px 16px',
                  color: 'var(--pp-text-muted)',
                  fontSize: '12px',
                  border: '1px solid var(--pp-border)',
                }}
              >
                <div
                  style={{
                    width: 16,
                    height: 16,
                    border: '2px solid var(--pp-accent)',
                    borderTopColor: 'transparent',
                    animation: 'spin 0.8s linear infinite',
                  }}
                />
                載入摘要中...
              </div>
            ) : digest ? (
              <DigestPanel digest={digest} />
            ) : null}
          </div>

          {/* Full text toggle */}
          {article.full_text && (
            <div style={{ border: '1px solid var(--pp-border)' }}>
              <button
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '10px 16px',
                  fontSize: '11.5px',
                  backgroundColor: 'var(--pp-bg-surface)',
                  color: 'var(--pp-text-secondary)',
                  border: 'none',
                  cursor: 'pointer',
                  fontFamily: 'var(--pp-font-ui)',
                  letterSpacing: '0.02em',
                }}
                onClick={() => setShowFullText(!showFullText)}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <FileText size={12} />
                  原文 Full Text
                </span>
                {showFullText ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </button>
              {showFullText && (
                <div
                  style={{
                    padding: '16px',
                    borderTop: '1px solid var(--pp-border)',
                    backgroundColor: 'var(--pp-bg-elevated)',
                    maxHeight: '60vh',
                    overflowY: 'auto',
                  }}
                >
                  <pre
                    style={{
                      fontSize: '11.5px',
                      lineHeight: 1.7,
                      whiteSpace: 'pre-wrap',
                      color: 'var(--pp-text-secondary)',
                      fontFamily: 'var(--pp-font-ui)',
                    }}
                  >
                    {article.full_text}
                  </pre>
                </div>
              )}
            </div>
          )}

          {/* Annotations section */}
          <div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 7,
                marginBottom: 14,
                paddingBottom: 8,
                borderBottom: '1px solid var(--pp-border)',
              }}
            >
              <MessageSquare size={13} style={{ color: 'var(--pp-text-muted)' }} />
              <SectionLabel>研究筆記</SectionLabel>
              <span
                style={{
                  fontSize: '11px',
                  color: 'var(--pp-text-dim)',
                  marginLeft: 4,
                }}
              >
                ({annotations.length})
              </span>
            </div>

            {/* Existing annotations */}
            {annotations.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
                {annotations.map((ann) => {
                  const typeLabel =
                    ANNOTATION_TYPES.find((t) => t.value === ann.annotation_type)?.label ??
                    ann.annotation_type
                  const typeColor =
                    ANNOTATION_TYPE_COLORS[ann.annotation_type] ?? 'var(--pp-accent)'
                  return (
                    <div
                      key={ann.id}
                      style={{
                        border: '1px solid var(--pp-border)',
                        borderLeft: `3px solid ${typeColor}`,
                        backgroundColor: 'var(--pp-bg-elevated)',
                        padding: '10px 14px',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          marginBottom: 7,
                        }}
                      >
                        <span
                          style={{
                            fontSize: '10px',
                            padding: '1px 7px',
                            border: `1px solid ${typeColor}`,
                            color: typeColor,
                            letterSpacing: '0.04em',
                          }}
                        >
                          {typeLabel}
                        </span>
                        <span style={{ fontSize: '10px', color: 'var(--pp-text-dim)' }}>
                          {new Date(ann.created_at).toLocaleDateString('zh-TW')}
                        </span>
                      </div>
                      <p
                        style={{
                          fontSize: '12.5px',
                          lineHeight: 1.6,
                          color: 'var(--pp-text-secondary)',
                        }}
                      >
                        {ann.note}
                      </p>
                    </div>
                  )
                })}
              </div>
            )}

            {/* Add annotation form */}
            <div
              style={{
                border: '1px solid var(--pp-border)',
                backgroundColor: 'var(--pp-bg-surface)',
              }}
            >
              {/* Type selector */}
              <div
                style={{
                  display: 'flex',
                  gap: 0,
                  borderBottom: '1px solid var(--pp-border)',
                  flexWrap: 'wrap',
                }}
              >
                {ANNOTATION_TYPES.map((type) => {
                  const isActive = annotationType === type.value
                  const color = ANNOTATION_TYPE_COLORS[type.value] ?? 'var(--pp-accent)'
                  return (
                    <button
                      key={type.value}
                      onClick={() => setAnnotationType(type.value)}
                      style={{
                        flex: '1 1 auto',
                        padding: '8px 10px',
                        fontSize: '11px',
                        border: 'none',
                        borderBottom: `2px solid ${isActive ? color : 'transparent'}`,
                        backgroundColor: isActive ? 'rgba(137, 180, 250, 0.05)' : 'transparent',
                        color: isActive ? color : 'var(--pp-text-dim)',
                        cursor: 'pointer',
                        fontFamily: 'var(--pp-font-ui)',
                        transition: 'color 0.12s, border-color 0.12s',
                      }}
                    >
                      {type.label}
                    </button>
                  )
                })}
              </div>

              {/* Input row */}
              <div style={{ display: 'flex', gap: 0 }}>
                <input
                  type="text"
                  placeholder="新增筆記..."
                  value={newAnnotation}
                  onChange={(e) => setNewAnnotation(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSubmitAnnotation()}
                  style={{
                    flex: 1,
                    padding: '10px 14px',
                    fontSize: '12.5px',
                    border: 'none',
                    backgroundColor: 'transparent',
                    color: 'var(--pp-text)',
                    outline: 'none',
                    fontFamily: 'var(--pp-font-ui)',
                  }}
                />
                <button
                  onClick={handleSubmitAnnotation}
                  disabled={!newAnnotation.trim()}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '0 16px',
                    fontSize: '11.5px',
                    border: 'none',
                    borderLeft: '1px solid var(--pp-border)',
                    backgroundColor: newAnnotation.trim()
                      ? 'var(--pp-accent-alpha)'
                      : 'transparent',
                    color: newAnnotation.trim() ? 'var(--pp-accent)' : 'var(--pp-text-dim)',
                    cursor: newAnnotation.trim() ? 'pointer' : 'not-allowed',
                    fontFamily: 'var(--pp-font-ui)',
                    transition: 'background-color 0.12s, color 0.12s',
                  }}
                >
                  <Send size={12} /> 送出
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right sidebar */}
        <div className="hidden lg:flex lg:flex-col lg:gap-3.5 lg:self-start">
          {/* Paper info card */}
          <div
            style={{
              border: '1px solid var(--pp-border)',
              backgroundColor: 'var(--pp-bg-elevated)',
            }}
          >
            <div
              style={{
                padding: '9px 14px',
                borderBottom: '1px solid var(--pp-border)',
                backgroundColor: 'var(--pp-bg-surface)',
              }}
            >
              <SectionLabel>論文資訊</SectionLabel>
            </div>
            <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
              {article.arxiv_id && (
                <div>
                  <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 3 }}>
                    arXiv
                  </p>
                  <a
                    href={`https://arxiv.org/abs/${article.arxiv_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      fontSize: '12px',
                      color: 'var(--pp-accent)',
                      textDecoration: 'none',
                      fontFamily: 'var(--pp-font-mono)',
                    }}
                  >
                    {article.arxiv_id}
                  </a>
                </div>
              )}
              {article.doi && (
                <div>
                  <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 3 }}>
                    DOI
                  </p>
                  <p
                    style={{
                      fontSize: '11.5px',
                      color: 'var(--pp-text-secondary)',
                      fontFamily: 'var(--pp-font-mono)',
                      wordBreak: 'break-all',
                    }}
                  >
                    {article.doi}
                  </p>
                </div>
              )}
              {article.year && (
                <div>
                  <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 3 }}>
                    年份
                  </p>
                  <p style={{ fontSize: '12px', color: 'var(--pp-text-secondary)' }}>
                    {article.year}
                  </p>
                </div>
              )}
              {article.authors && article.authors.length > 0 && (
                <div>
                  <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 3 }}>
                    作者
                  </p>
                  <p
                    style={{ fontSize: '12px', color: 'var(--pp-text-secondary)', lineHeight: 1.5 }}
                  >
                    {article.authors.map((a) => a.name).join(', ')}
                  </p>
                </div>
              )}
              {article.journal && (
                <div>
                  <p style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginBottom: 3 }}>
                    期刊 / 會議
                  </p>
                  <p
                    style={{
                      fontSize: '12px',
                      color: 'var(--pp-text-secondary)',
                      fontStyle: 'italic',
                    }}
                  >
                    {article.journal}
                  </p>
                </div>
              )}
              {(article.source_url || article.pdf_url) && (
                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                    paddingTop: 6,
                    borderTop: '1px solid var(--pp-border)',
                  }}
                >
                  {article.source_url && (
                    <a
                      href={article.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        fontSize: '11.5px',
                        color: 'var(--pp-accent)',
                        textDecoration: 'none',
                      }}
                    >
                      <ExternalLink size={11} /> 原始頁面
                    </a>
                  )}
                  {article.pdf_url && (
                    <a
                      href={article.pdf_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        fontSize: '11.5px',
                        color: 'var(--pp-accent)',
                        textDecoration: 'none',
                      }}
                    >
                      <ExternalLink size={11} /> 下載 PDF
                    </a>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Tags card */}
          {article.tags.length > 0 && (
            <div
              style={{
                border: '1px solid var(--pp-border)',
                backgroundColor: 'var(--pp-bg-elevated)',
              }}
            >
              <div
                style={{
                  padding: '9px 14px',
                  borderBottom: '1px solid var(--pp-border)',
                  backgroundColor: 'var(--pp-bg-surface)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <Tag size={10} style={{ color: 'var(--pp-text-dim)' }} />
                <SectionLabel>標籤</SectionLabel>
              </div>
              <div
                style={{
                  padding: '12px 14px',
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 6,
                }}
              >
                {article.tags.map((tag) => (
                  <span
                    key={tag}
                    style={{
                      fontSize: '10px',
                      padding: '2px 8px',
                      border: '1px solid rgba(137, 180, 250, 0.35)',
                      color: 'var(--pp-accent)',
                      backgroundColor: 'rgba(137, 180, 250, 0.06)',
                    }}
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

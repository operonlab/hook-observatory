import { BookOpen, FileText, MessageSquare, Star, TrendingUp } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import ArticleCard from '../components/ArticleCard'
import { useDashboard } from '../hooks/usePaper'

interface StatCardProps {
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>
  label: string
  value: number | string
  accent?: boolean
  note?: string
}

function StatCard({ icon: Icon, label, value, accent, note }: StatCardProps) {
  return (
    <div
      style={{
        backgroundColor: 'var(--pp-bg-elevated)',
        border: `1px solid ${accent ? 'var(--pp-accent)' : 'var(--pp-border)'}`,
        padding: '18px 20px 16px',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Background numeral decoration */}
      <span
        aria-hidden
        style={{
          position: 'absolute',
          right: 12,
          bottom: -8,
          fontFamily: 'var(--pp-font-display)',
          fontSize: '4.5rem',
          fontWeight: 700,
          color: accent ? 'rgba(137, 180, 250, 0.06)' : 'rgba(255,255,255,0.03)',
          lineHeight: 1,
          userSelect: 'none',
          pointerEvents: 'none',
        }}
      >
        {value}
      </span>

      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 14 }}>
        <Icon size={13} style={{ color: accent ? 'var(--pp-accent)' : 'var(--pp-text-muted)' }} />
        <span
          style={{
            fontSize: '10px',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: 'var(--pp-text-muted)',
            fontFamily: 'var(--pp-font-ui)',
          }}
        >
          {label}
        </span>
      </div>

      <div
        style={{
          fontFamily: 'var(--pp-font-display)',
          fontSize: '2.4rem',
          fontWeight: 400,
          lineHeight: 1,
          color: accent ? 'var(--pp-accent)' : 'var(--pp-text)',
          letterSpacing: '-0.02em',
        }}
      >
        {value}
      </div>

      {note && (
        <p
          style={{
            fontSize: '10px',
            color: 'var(--pp-text-dim)',
            marginTop: 6,
          }}
        >
          {note}
        </p>
      )}
    </div>
  )
}

function SectionHeader({
  title,
  action,
  onAction,
}: {
  title: string
  action?: string
  onAction?: () => void
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        marginBottom: 10,
        paddingBottom: 8,
        borderBottom: '1px solid var(--pp-border)',
      }}
    >
      <h2
        style={{
          fontSize: '11px',
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--pp-text-muted)',
          fontFamily: 'var(--pp-font-ui)',
          fontWeight: 500,
        }}
      >
        {title}
      </h2>
      {action && onAction && (
        <button
          style={{
            fontSize: '11px',
            color: 'var(--pp-accent)',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            letterSpacing: '0.02em',
          }}
          onClick={onAction}
        >
          {action} →
        </button>
      )}
    </div>
  )
}

export default function DashboardPage() {
  const { dashboard, loading } = useDashboard()
  const navigate = useNavigate()

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
        <span>載入中...</span>
      </div>
    )
  }

  const digestRate =
    dashboard && dashboard.total_articles > 0
      ? Math.round((dashboard.total_digests / dashboard.total_articles) * 100)
      : 0

  return (
    <div style={{ padding: 'clamp(20px, 4vw, 40px)', maxWidth: 1100, margin: '0 auto' }}>
      {/* Page Header */}
      <header style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, marginBottom: 6 }}>
          <h1
            style={{
              fontFamily: 'var(--pp-font-display)',
              fontSize: 'clamp(1.6rem, 3vw, 2.2rem)',
              fontWeight: 500,
              color: 'var(--pp-text)',
              lineHeight: 1.1,
              letterSpacing: '-0.01em',
            }}
          >
            論文研究總覽
          </h1>
          {dashboard && (
            <span
              style={{
                fontSize: '11px',
                color: 'var(--pp-text-dim)',
                marginBottom: 4,
                fontFamily: 'var(--pp-font-mono)',
              }}
            >
              v{new Date().getFullYear()}
            </span>
          )}
        </div>
        <p
          style={{
            fontSize: '12px',
            color: 'var(--pp-text-muted)',
            letterSpacing: '0.02em',
          }}
        >
          學術論文管理、自動摘要與研究管線
        </p>
      </header>
      {/* Stats Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 1,
          marginBottom: 36,
          border: '1px solid var(--pp-border)',
        }}
      >
        <StatCard icon={FileText} label="論文總數" value={dashboard?.total_articles ?? 0} accent />
        <StatCard
          icon={BookOpen}
          label="已摘要"
          value={dashboard?.total_digests ?? 0}
          note={`覆蓋率 ${digestRate}%`}
        />
        <StatCard icon={Star} label="高價值" value={dashboard?.high_relevance_count ?? 0} />
        <StatCard icon={MessageSquare} label="研究筆記" value={dashboard?.total_annotations ?? 0} />
      </div>
      {/* Bento: cannibalize (left) + recent (right) on lg+ */}
      <div
        className="lg:grid lg:grid-cols-[1fr_340px] lg:gap-6"
        style={{ display: 'flex', flexDirection: 'column', gap: 36 }}
      >
        {/* Cannibalize candidates */}
        {(dashboard?.cannibalize_candidates?.length ?? 0) > 0 && (
          <section>
            <SectionHeader title="蠶食候選 — 高價值可執行論文" />
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                gap: 1,
              }}
            >
              {dashboard!.cannibalize_candidates.map((article) => (
                <ArticleCard key={article.id} article={article} />
              ))}
            </div>
          </section>
        )}

        {/* Recent articles */}
        {dashboard?.recent_articles && dashboard.recent_articles.length > 0 && (
          <section>
            <SectionHeader
              title="最近收錄"
              action="查看全部"
              onAction={() => navigate('/paper/articles')}
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {dashboard.recent_articles.map((article) => (
                <ArticleCard key={article.id} article={article} />
              ))}
            </div>
          </section>
        )}
      </div>

      {/* Empty state */}
      {!dashboard?.total_articles && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '64px 20px',
            gap: 12,
            border: '1px solid var(--pp-border)',
            color: 'var(--pp-text-dim)',
          }}
        >
          <TrendingUp size={28} />
          <p style={{ fontSize: '13px' }}>尚無論文 — 透過 Capture 匯入研究資料</p>
        </div>
      )}
    </div>
  )
}

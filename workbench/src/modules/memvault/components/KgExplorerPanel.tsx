import { useCallback, useEffect, useRef, useState } from 'react'
import { useMemvaultStore } from '../stores'
import type { Cluster, ClusterDetail, WisdomNode } from '../types'
import InfoTip from './InfoTip'

function hexToRgba(cssVar: string, alpha: number): string {
  return `color-mix(in srgb, ${cssVar} ${Math.round(alpha * 100)}%, transparent)`
}

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins} 分鐘前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小時前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return `${Math.floor(days / 30)} 個月前`
}

// ── Layer Section Header ──

function LayerHeader({
  color,
  label,
  count,
  countUnit,
  collapsed,
  onToggle,
  info,
}: {
  color: string
  label: string
  count: number
  countUnit: string
  collapsed: boolean
  onToggle: () => void
  info?: string
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <button
        onClick={onToggle}
        className="flex items-center gap-2 text-left flex-1"
        style={{ minHeight: 44 }}
      >
        <span
          className="text-xs transition-transform duration-200"
          style={{
            color,
            display: 'inline-block',
            transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
          }}
        >
          ▼
        </span>
        <span
          className="inline-block h-3 w-3 rounded-full shrink-0"
          style={{ backgroundColor: color }}
        />
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
          {label}
        </h3>
      </button>
      {info && <InfoTip text={info} />}
      <span className="text-xs shrink-0" style={{ color: 'var(--subtext0)' }}>
        {count} {countUnit}
      </span>
    </div>
  )
}

// ── Wisdom Card (L2) ──

function WisdomCard({
  node,
  onExpand,
  expanded,
  relatedClusters,
  onClusterNav,
}: {
  node: WisdomNode
  onExpand: () => void
  expanded: boolean
  relatedClusters: Cluster[]
  onClusterNav?: (clusterId: string) => void
}) {
  const confidenceColors: Record<string, string> = {
    HIGH: 'var(--green)',
    MEDIUM: 'var(--yellow)',
    LOW: 'var(--red)',
  }
  const confColor = confidenceColors[node.confidence] ?? 'var(--subtext0)'

  return (
    <div
      className="rounded-xl border p-4 cursor-pointer transition-all duration-200"
      style={{
        backgroundColor: hexToRgba('var(--peach)', 0.06),
        borderColor: expanded ? 'var(--peach)' : 'var(--surface0)',
      }}
      onClick={onExpand}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--peach)'
      }}
      onMouseLeave={(e) => {
        if (!expanded) e.currentTarget.style.borderColor = 'var(--surface0)'
      }}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <span
          className="rounded-full px-2 py-0.5 text-xs font-medium"
          style={{
            backgroundColor: hexToRgba(confColor, 0.18),
            color: confColor,
            border: `1px solid ${confColor}`,
          }}
        >
          {node.confidence}
        </span>
        <span className="text-xs shrink-0" style={{ color: 'var(--subtext0)' }}>
          {node.evidence_count ?? 0} 證據
        </span>
      </div>

      <p className="text-sm leading-relaxed mb-2" style={{ color: 'var(--text)' }}>
        {node.wisdom}
      </p>

      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs" style={{ color: 'var(--peach)' }}>
          {node.bridge_entity}
        </span>
        {node.tags.length > 0 && (
          <div className="flex gap-1 flex-wrap">
            {node.tags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="rounded px-1.5 py-0.5 text-xs"
                style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext0)' }}
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Expanded: show related clusters */}
      {expanded && (
        <div className="mt-3 pt-3 border-t space-y-2" style={{ borderColor: 'var(--surface0)' }}>
          <p className="text-xs font-medium" style={{ color: 'var(--subtext0)' }}>
            關聯群集 ({node.cluster_ids.length})
          </p>
          {relatedClusters.length > 0 ? (
            relatedClusters.map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between text-xs px-2 py-2 rounded cursor-pointer transition-colors gap-2"
                style={{ backgroundColor: hexToRgba('var(--blue)', 0.08) }}
                onClick={(e) => {
                  e.stopPropagation()
                  onClusterNav?.(c.id)
                }}
                title="點擊跳轉到此群集"
              >
                <div className="flex items-center gap-1.5 min-w-0">
                  <span
                    className="inline-block h-2 w-2 rounded-full shrink-0"
                    style={{ backgroundColor: 'var(--blue)' }}
                  />
                  <span
                    className="truncate"
                    style={{
                      color: 'var(--blue)',
                      textDecoration: 'underline',
                      textDecorationStyle: 'dotted',
                    }}
                  >
                    {c.name}
                  </span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span style={{ color: 'var(--subtext0)' }}>{c.size} 成員</span>
                  <span
                    className="rounded px-1 py-0.5"
                    style={{
                      backgroundColor:
                        c.verdict === 'VERIFIED'
                          ? hexToRgba('var(--green)', 0.15)
                          : hexToRgba('var(--yellow)', 0.15),
                      color: c.verdict === 'VERIFIED' ? 'var(--green)' : 'var(--yellow)',
                    }}
                  >
                    {c.verdict}
                  </span>
                </div>
              </div>
            ))
          ) : node.cluster_ids.length > 0 ? (
            <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
              {node.cluster_ids.length} 個群集 ID（尚未載入）
            </p>
          ) : (
            <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
              無關聯群集
            </p>
          )}
          {node.verified && (
            <span
              className="inline-block rounded px-1.5 py-0.5 text-xs"
              style={{
                backgroundColor: hexToRgba('var(--green)', 0.15),
                color: 'var(--green)',
              }}
            >
              已驗證
            </span>
          )}
          <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
            {relativeTime(node.created_at)}
          </p>
        </div>
      )}
    </div>
  )
}

// ── Cluster Card (L1) ──

function ClusterCard({
  cluster,
  onExpand,
  expanded,
  detail,
}: {
  cluster: Cluster
  onExpand: () => void
  expanded: boolean
  detail: ClusterDetail | null
}) {
  return (
    <div
      className="rounded-xl border p-4 cursor-pointer transition-all duration-200"
      style={{
        backgroundColor: hexToRgba('var(--blue)', 0.06),
        borderColor: expanded ? 'var(--blue)' : 'var(--surface0)',
      }}
      onClick={onExpand}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--blue)'
      }}
      onMouseLeave={(e) => {
        if (!expanded) e.currentTarget.style.borderColor = 'var(--surface0)'
      }}
    >
      <div className="flex items-start sm:items-center justify-between mb-2 gap-2">
        <span className="text-sm font-medium flex-1 min-w-0" style={{ color: 'var(--text)' }}>
          {cluster.name}
        </span>
        <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
          <span
            className="rounded-full px-2 py-0.5 text-xs"
            style={{
              backgroundColor: hexToRgba('var(--blue)', 0.15),
              color: 'var(--blue)',
            }}
          >
            {cluster.size} 成員
          </span>
          <span
            className="rounded px-1.5 py-0.5 text-xs"
            style={{
              backgroundColor:
                cluster.verdict === 'VERIFIED'
                  ? hexToRgba('var(--green)', 0.15)
                  : hexToRgba('var(--yellow)', 0.15),
              color: cluster.verdict === 'VERIFIED' ? 'var(--green)' : 'var(--yellow)',
            }}
          >
            {cluster.verdict}
          </span>
        </div>
      </div>

      {cluster.summary && (
        <p className="text-xs mb-2 line-clamp-2" style={{ color: 'var(--subtext1)' }}>
          {cluster.summary}
        </p>
      )}

      <div className="flex gap-1 flex-wrap">
        {cluster.top_subjects.slice(0, 4).map((s) => (
          <span
            key={s}
            className="rounded px-1.5 py-0.5 text-xs"
            style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext0)' }}
          >
            {s}
          </span>
        ))}
      </div>

      {/* Expanded: show detail */}
      {expanded && (
        <div className="mt-3 pt-3 border-t space-y-2" style={{ borderColor: 'var(--surface0)' }}>
          {cluster.summary && (
            <div>
              <p className="text-xs font-medium mb-1" style={{ color: 'var(--subtext0)' }}>
                摘要
              </p>
              <p
                className="text-xs leading-relaxed whitespace-pre-wrap"
                style={{ color: 'var(--text)' }}
              >
                {cluster.summary}
              </p>
            </div>
          )}

          {cluster.top_predicates.length > 0 && (
            <div>
              <p className="text-xs font-medium mb-1" style={{ color: 'var(--subtext0)' }}>
                常見關係
              </p>
              <div className="flex gap-1 flex-wrap">
                {cluster.top_predicates.map((p) => (
                  <span
                    key={p}
                    className="rounded px-1.5 py-0.5 text-xs"
                    style={{
                      backgroundColor: hexToRgba('var(--mauve)', 0.12),
                      color: 'var(--mauve)',
                    }}
                  >
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {cluster.top_objects.length > 0 && (
            <div>
              <p className="text-xs font-medium mb-1" style={{ color: 'var(--subtext0)' }}>
                常見物件
              </p>
              <div className="flex gap-1 flex-wrap">
                {cluster.top_objects.map((o) => (
                  <span
                    key={o}
                    className="rounded px-1.5 py-0.5 text-xs"
                    style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext1)' }}
                  >
                    {o}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Member triples (if populated) */}
          {detail && detail.triples.length > 0 && (
            <div>
              <p className="text-xs font-medium mb-1" style={{ color: 'var(--subtext0)' }}>
                成員三元組
              </p>
              {detail.triples.slice(0, 20).map((t) => (
                <div
                  key={t.id}
                  className="text-xs px-2 py-1.5 rounded mb-1"
                  style={{ backgroundColor: 'var(--base)' }}
                >
                  {/* Mobile: stack vertically */}
                  <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    <span style={{ color: 'var(--teal)' }}>{t.subject}</span>
                    <span style={{ color: 'var(--subtext0)' }}>&rarr;</span>
                    <span style={{ color: 'var(--subtext1)' }}>{t.predicate}</span>
                    <span style={{ color: 'var(--subtext0)' }}>&rarr;</span>
                    <span className="break-all" style={{ color: 'var(--text)' }}>
                      {t.object}
                    </span>
                  </div>
                </div>
              ))}
              {detail.triples.length > 20 && (
                <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
                  ...還有 {detail.triples.length - 20} 筆
                </p>
              )}
            </div>
          )}

          {cluster.generation_batch && (
            <p className="text-xs" style={{ color: 'var(--subtext0)' }}>
              生成批次：{cluster.generation_batch}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Triple Table (L0) ──

function TripleTable() {
  const {
    kg_triples,
    kg_triplesTotal,
    kg_triplesPage,
    kg_loading,
    fetchTriples,
    deleteTriple,
    isStale: isStaleCheck,
  } = useMemvaultStore()
  const [filterPredicate, setFilterPredicate] = useState('')

  useEffect(() => {
    if (isStaleCheck('kg_triples')) fetchTriples(1)
  }, [fetchTriples, isStaleCheck])

  const totalPages = Math.ceil(kg_triplesTotal / 20)

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <input
          type="text"
          value={filterPredicate}
          onChange={(e) => setFilterPredicate(e.target.value)}
          placeholder="篩選 predicate..."
          className="rounded-lg border px-2 py-2 text-xs outline-none flex-1"
          style={{
            backgroundColor: 'var(--base)',
            borderColor: 'var(--surface0)',
            color: 'var(--text)',
            minHeight: 44,
          }}
        />
        <span className="text-xs shrink-0" style={{ color: 'var(--subtext0)' }}>
          共 {kg_triplesTotal} 筆
        </span>
      </div>

      {kg_loading && kg_triples.length === 0 ? (
        <div className="flex justify-center py-8">
          <div
            className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
            style={{ borderColor: 'var(--teal)', borderTopColor: 'transparent' }}
          />
        </div>
      ) : (
        <div className="space-y-1.5">
          {kg_triples
            .filter(
              (t) =>
                !filterPredicate ||
                t.predicate.toLowerCase().includes(filterPredicate.toLowerCase()),
            )
            .map((t) => (
              <div
                key={t.id}
                className="group rounded-lg border px-3 py-2.5 text-xs"
                style={{
                  backgroundColor: 'var(--mantle)',
                  borderColor: 'var(--surface0)',
                }}
              >
                {/* Triple display — wraps on mobile */}
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 mb-1.5">
                  <span className="font-medium" style={{ color: 'var(--teal)' }}>
                    {t.subject}
                  </span>
                  <span style={{ color: 'var(--subtext0)' }}>&rarr;</span>
                  <span style={{ color: 'var(--mauve)' }}>{t.predicate}</span>
                  <span style={{ color: 'var(--subtext0)' }}>&rarr;</span>
                  <span className="break-all flex-1" style={{ color: 'var(--text)' }}>
                    {t.object}
                  </span>
                </div>
                {/* Footer row */}
                <div className="flex items-center justify-between gap-2">
                  {t.topic && (
                    <span
                      className="rounded px-1.5 py-0.5"
                      style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext0)' }}
                    >
                      {t.topic}
                    </span>
                  )}
                  <div className="flex-1" />
                  <button
                    onClick={() => {
                      if (confirm(`刪除三元組：${t.subject} → ${t.predicate} → ${t.object}？`))
                        deleteTriple(t.id)
                    }}
                    className="rounded px-2 py-1 text-xs transition-opacity sm:opacity-0 sm:group-hover:opacity-100"
                    style={{ color: 'var(--red)', minHeight: 36 }}
                    title="刪除"
                  >
                    刪除
                  </button>
                </div>
              </div>
            ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-4">
          <button
            onClick={() => fetchTriples(kg_triplesPage - 1)}
            disabled={kg_triplesPage <= 1}
            className="rounded-lg px-3 py-2 text-xs transition-colors"
            style={{
              backgroundColor: 'var(--surface0)',
              color: kg_triplesPage <= 1 ? 'var(--subtext0)' : 'var(--text)',
              opacity: kg_triplesPage <= 1 ? 0.5 : 1,
              minHeight: 44,
            }}
          >
            上一頁
          </button>
          <span className="text-xs" style={{ color: 'var(--subtext0)' }}>
            {kg_triplesPage} / {totalPages}
          </span>
          <button
            onClick={() => fetchTriples(kg_triplesPage + 1)}
            disabled={kg_triplesPage >= totalPages}
            className="rounded-lg px-3 py-2 text-xs transition-colors"
            style={{
              backgroundColor: 'var(--surface0)',
              color: kg_triplesPage >= totalPages ? 'var(--subtext0)' : 'var(--text)',
              opacity: kg_triplesPage >= totalPages ? 0.5 : 1,
              minHeight: 44,
            }}
          >
            下一頁
          </button>
        </div>
      )}
    </div>
  )
}

// ── Main KG Explorer Panel ──

export default function KgExplorerPanel() {
  const {
    kg_wisdom,
    kg_clusters,
    kg_selectedCluster,
    kg_triplesTotal,
    kg_loading,
    fetchWisdom,
    fetchClusters,
    fetchClusterDetail,
  } = useMemvaultStore()

  const [expandedWisdom, setExpandedWisdom] = useState<string | null>(null)
  const [expandedCluster, setExpandedCluster] = useState<string | null>(null)
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set())

  const clusterSectionRef = useRef<HTMLElement>(null)

  const isStale = useMemvaultStore((s) => s.isStale)

  useEffect(() => {
    if (isStale('kg_wisdom')) fetchWisdom()
    if (isStale('kg_clusters')) fetchClusters()
  }, [fetchWisdom, fetchClusters, isStale])

  const handleClusterExpand = (id: string) => {
    if (expandedCluster === id) {
      setExpandedCluster(null)
    } else {
      setExpandedCluster(id)
      fetchClusterDetail(id)
    }
  }

  const toggleSection = useCallback((key: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const handleClusterNav = useCallback(
    (clusterId: string) => {
      setCollapsedSections((prev) => {
        const next = new Set(prev)
        next.delete('clusters')
        return next
      })
      setExpandedCluster(clusterId)
      fetchClusterDetail(clusterId)
      setTimeout(() => {
        clusterSectionRef.current?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        })
      }, 100)
    },
    [fetchClusterDetail],
  )

  return (
    <div className="space-y-6">
      {/* L2: Wisdom */}
      <section>
        <LayerHeader
          color="var(--peach)"
          label="智慧結晶 (L2)"
          count={kg_wisdom.length}
          countUnit="條"
          collapsed={collapsedSections.has('wisdom')}
          onToggle={() => toggleSection('wisdom')}
          info="智慧結晶是從多個知識群集中提煉出的高層洞察。每條智慧都跨越多個主題群集，代表跨領域的深層認知模式。信心等級（HIGH/MEDIUM/LOW）反映證據的充分程度。"
        />

        {!collapsedSections.has('wisdom') &&
          (kg_loading && kg_wisdom.length === 0 ? (
            <div className="flex justify-center py-6">
              <div
                className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
                style={{ borderColor: 'var(--peach)', borderTopColor: 'transparent' }}
              />
            </div>
          ) : kg_wisdom.length === 0 ? (
            <p className="text-sm py-4" style={{ color: 'var(--subtext0)' }}>
              尚未產生智慧結晶
            </p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {kg_wisdom.map((w) => (
                <WisdomCard
                  key={w.id}
                  node={w}
                  expanded={expandedWisdom === w.id}
                  onExpand={() => setExpandedWisdom(expandedWisdom === w.id ? null : w.id)}
                  relatedClusters={kg_clusters.filter((c) => w.cluster_ids.includes(c.id))}
                  onClusterNav={handleClusterNav}
                />
              ))}
            </div>
          ))}
      </section>

      {/* L1: Clusters */}
      <section ref={clusterSectionRef}>
        <LayerHeader
          color="var(--blue)"
          label="知識群集 (L1)"
          count={kg_clusters.length}
          countUnit="個"
          collapsed={collapsedSections.has('clusters')}
          onToggle={() => toggleSection('clusters')}
          info="知識群集是由語意相近的三元組自動聚類而成的主題分組。每個群集包含一組相關的知識事實，並附有摘要、主要主題和驗證狀態（VERIFIED 表示已驗證，UNVERIFIED 表示待確認）。"
        />

        {!collapsedSections.has('clusters') &&
          (kg_clusters.length === 0 ? (
            <p className="text-sm py-4" style={{ color: 'var(--subtext0)' }}>
              尚未產生知識群集
            </p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {kg_clusters.map((c) => (
                <ClusterCard
                  key={c.id}
                  cluster={c}
                  expanded={expandedCluster === c.id}
                  onExpand={() => handleClusterExpand(c.id)}
                  detail={expandedCluster === c.id ? kg_selectedCluster : null}
                />
              ))}
            </div>
          ))}
      </section>

      {/* L0: Triples */}
      <section>
        <LayerHeader
          color="var(--teal)"
          label="知識三元組 (L0)"
          count={kg_triplesTotal}
          countUnit="筆"
          collapsed={collapsedSections.has('triples')}
          onToggle={() => toggleSection('triples')}
          info="三元組是知識圖譜的最小單位，格式為「主詞 → 關係 → 受詞」。每條三元組記錄一個具體的知識事實，由對話中自動提取。這些是所有上層結構（群集、智慧）的基礎資料。"
        />

        {!collapsedSections.has('triples') && <TripleTable />}
      </section>
    </div>
  )
}

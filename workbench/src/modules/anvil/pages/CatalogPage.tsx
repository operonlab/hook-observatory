import { useCallback, useEffect, useRef, useState } from 'react'
import { catalogApi } from '../api'
import SkillGalaxyCanvas from '../components/SkillGalaxyCanvas'
import SkillListView from '../components/SkillListView'
import type { CatalogListResponse, CatalogSkillDetail, GraphData } from '../types'
import { DOMAIN_COLORS } from '../types'

export default function CatalogPage() {
  const [view, setView] = useState<'graph' | 'list'>('list')
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [listData, setListData] = useState<CatalogListResponse | null>(null)
  const [selectedSkill, setSelectedSkill] = useState<CatalogSkillDetail | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeDomains, setActiveDomains] = useState<Set<string>>(new Set())
  const [activeDomainFilter, setActiveDomainFilter] = useState<string | null>(null)
  const [activeEdgeTypes, setActiveEdgeTypes] = useState<Set<string>>(
    new Set(['pipeline', 'enhancement', 'shares-domain']),
  )
  const [syncing, setSyncing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [guideExpanded, setGuideExpanded] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Initial data load
  useEffect(() => {
    setLoading(true)
    Promise.all([catalogApi.graph(), catalogApi.list({ limit: 500 })])
      .then(([graph, list]) => {
        setGraphData(graph)
        setListData(list)
        setActiveDomains(new Set(Object.keys(graph.stats.domain_distribution)))
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // Debounced search + domain filter refetch
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      catalogApi
        .list({
          q: searchQuery || undefined,
          domain: activeDomainFilter || undefined,
          limit: 500,
        })
        .then(setListData)
        .catch(() => {})
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [searchQuery, activeDomainFilter])

  const handleSkillClick = useCallback((name: string) => {
    setGuideExpanded(false)
    catalogApi
      .get(name)
      .then(setSelectedSkill)
      .catch(() => {})
  }, [])

  const handleSync = useCallback(async () => {
    setSyncing(true)
    try {
      await catalogApi.sync()
      const [graph, list] = await Promise.all([
        catalogApi.graph(),
        catalogApi.list({
          q: searchQuery || undefined,
          domain: activeDomainFilter || undefined,
          limit: 500,
        }),
      ])
      setGraphData(graph)
      setListData(list)
      setActiveDomains(new Set(Object.keys(graph.stats.domain_distribution)))
    } catch {
      // silently fail
    } finally {
      setSyncing(false)
    }
  }, [searchQuery, activeDomainFilter])

  const toggleEdgeType = useCallback((edgeType: string) => {
    setActiveEdgeTypes((prev) => {
      const next = new Set(prev)
      if (next.has(edgeType)) {
        next.delete(edgeType)
      } else {
        next.add(edgeType)
      }
      return next
    })
  }, [])

  const toggleDomain = useCallback((domain: string) => {
    setActiveDomains((prev) => {
      const next = new Set(prev)
      if (next.has(domain)) {
        next.delete(domain)
      } else {
        next.add(domain)
      }
      return next
    })
  }, [])

  const total = graphData?.stats.total_skills ?? 0
  const edges = graphData?.stats.total_edges ?? 0

  return (
    <div
      className="flex flex-col h-full"
      style={{ backgroundColor: 'var(--av-bg)', color: 'var(--av-text)' }}
    >
      {/* Header Bar */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b shrink-0"
        style={{ borderColor: 'var(--av-border)', backgroundColor: 'var(--av-bg-surface)' }}
      >
        {/* Search */}
        <input
          type="search"
          placeholder="搜尋技能..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 max-w-xs text-sm rounded-md border px-3 py-1.5 outline-none"
          style={{
            backgroundColor: 'var(--av-bg)',
            borderColor: 'var(--av-border)',
            color: 'var(--av-text)',
          }}
        />

        {/* View Toggle */}
        <div
          className="flex rounded-md overflow-hidden border"
          style={{ borderColor: 'var(--av-border)' }}
        >
          {(['list', 'graph'] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className="px-3 py-1.5 text-xs font-medium transition-colors"
              style={{
                backgroundColor: view === v ? 'var(--av-accent-alpha)' : 'transparent',
                color: view === v ? 'var(--av-accent)' : 'var(--av-text-muted)',
                borderRight: v === 'list' ? `1px solid var(--av-border)` : undefined,
              }}
            >
              {v === 'list' ? 'List' : 'Galaxy'}
            </button>
          ))}
        </div>

        {/* Sync Button */}
        <button
          type="button"
          onClick={handleSync}
          disabled={syncing}
          className="text-xs px-3 py-1.5 rounded-md border transition-colors"
          style={{
            borderColor: 'var(--av-border)',
            color: syncing ? 'var(--av-text-muted)' : 'var(--av-accent)',
            backgroundColor: syncing ? 'transparent' : 'var(--av-accent-alpha)',
          }}
        >
          {syncing ? '同步中...' : 'Sync'}
        </button>

        {/* Stats */}
        <span className="text-xs ml-auto" style={{ color: 'var(--av-text-muted)' }}>
          {loading ? '載入中...' : `${total} skills • ${edges} edges`}
        </span>
      </div>

      {/* Main Content */}
      <div className="flex flex-1 min-h-0 relative">
        {/* Content Area */}
        <div className="flex-1 min-w-0 relative overflow-hidden">
          {view === 'graph' ? (
            <>
              {graphData && (
                <SkillGalaxyCanvas
                  graphData={graphData}
                  activeDomains={activeDomains}
                  activeEdgeTypes={activeEdgeTypes}
                  searchQuery={searchQuery}
                  onNodeClick={handleSkillClick}
                  selectedSkillName={selectedSkill?.name ?? null}
                />
              )}
              {/* Domain Legend Overlay */}
              {graphData && (
                <DomainLegend
                  distribution={graphData.stats.domain_distribution}
                  activeDomains={activeDomains}
                  onToggle={toggleDomain}
                  activeEdgeTypes={activeEdgeTypes}
                  onToggleEdge={toggleEdgeType}
                />
              )}
            </>
          ) : (
            <SkillListView
              data={listData}
              searchQuery={searchQuery}
              onSkillClick={handleSkillClick}
              selectedSkillName={selectedSkill?.name ?? null}
              onDomainFilter={setActiveDomainFilter}
              activeDomain={activeDomainFilter}
            />
          )}
        </div>

        {/* Skill Detail Drawer */}
        {selectedSkill && (
          <SkillDetailDrawer
            skill={selectedSkill}
            guideExpanded={guideExpanded}
            onToggleGuide={() => setGuideExpanded((v) => !v)}
            onClose={() => setSelectedSkill(null)}
          />
        )}
      </div>
    </div>
  )
}

// ── DomainLegend ─────────────────────────────────────────────────────────────

function DomainLegend({
  distribution,
  activeDomains,
  onToggle,
  activeEdgeTypes,
  onToggleEdge,
}: {
  distribution: Record<string, number>
  activeDomains: Set<string>
  onToggle: (domain: string) => void
  activeEdgeTypes: Set<string>
  onToggleEdge: (edgeType: string) => void
}) {
  const entries = Object.entries(distribution).sort((a, b) => b[1] - a[1])

  return (
    <div
      className="absolute top-3 right-3 rounded-lg border p-3 text-xs space-y-1.5"
      style={{
        backgroundColor: 'rgba(30,30,46,0.88)',
        borderColor: 'var(--av-border)',
        backdropFilter: 'blur(4px)',
        maxHeight: '80vh',
        overflowY: 'auto',
        minWidth: 160,
        zIndex: 10,
      }}
    >
      <div className="font-medium mb-2" style={{ color: 'var(--av-text-secondary)' }}>
        Domain
      </div>
      {entries.map(([domain, count]) => {
        const active = activeDomains.has(domain)
        const color = DOMAIN_COLORS[domain] ?? '#888'
        return (
          <button
            key={domain}
            type="button"
            onClick={() => onToggle(domain)}
            className="flex items-center gap-2 w-full text-left rounded transition-opacity"
            style={{ opacity: active ? 1 : 0.3 }}
          >
            <span
              className="shrink-0 w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="truncate" style={{ color: 'var(--av-text-secondary)' }}>
              {domain}
            </span>
            <span className="ml-auto shrink-0" style={{ color: 'var(--av-text-muted)' }}>
              {count}
            </span>
          </button>
        )
      })}

      {/* Edge type legend */}
      <div className="mt-3 pt-2.5 border-t space-y-1.5" style={{ borderColor: 'var(--av-border)' }}>
        <div className="font-medium mb-2" style={{ color: 'var(--av-text-secondary)' }}>
          Edges
        </div>
        {[
          { label: 'pipeline', color: 'rgba(241, 250, 140, 0.8)', desc: '上下游串接' },
          { label: 'enhancement', color: 'rgba(139, 233, 253, 0.7)', desc: '功能增強' },
          { label: 'shares-domain', color: 'rgba(150, 170, 230, 0.5)', desc: '同領域' },
        ].map((e) => {
          const active = activeEdgeTypes.has(e.label)
          return (
            <button
              key={e.label}
              type="button"
              onClick={() => onToggleEdge(e.label)}
              className="flex items-center gap-2 w-full text-left rounded transition-opacity"
              style={{ opacity: active ? 1 : 0.3 }}
            >
              <span
                className="shrink-0 w-4 h-0.5 rounded-full"
                style={{ backgroundColor: e.color }}
              />
              <span className="truncate" style={{ color: 'var(--av-text-tertiary)' }}>
                {e.desc}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── SkillDetailDrawer ─────────────────────────────────────────────────────────

function SkillDetailDrawer({
  skill,
  guideExpanded,
  onToggleGuide,
  onClose,
}: {
  skill: CatalogSkillDetail
  guideExpanded: boolean
  onToggleGuide: () => void
  onClose: () => void
}) {
  const domainColor = DOMAIN_COLORS[skill.domain] ?? '#888'
  const health = skill.health_score ?? 0

  return (
    <div
      className="shrink-0 border-l flex flex-col"
      style={{
        width: 320,
        backgroundColor: 'var(--av-bg-surface)',
        borderColor: 'var(--av-border)',
        overflowY: 'auto',
      }}
    >
      {/* Drawer Header */}
      <div
        className="flex items-start justify-between px-4 py-3 border-b shrink-0 gap-2"
        style={{ borderColor: 'var(--av-border)' }}
      >
        <div className="min-w-0">
          <div
            className="font-mono text-sm font-semibold truncate"
            style={{ color: 'var(--av-text)' }}
          >
            {skill.name}
          </div>
          <span
            className="inline-block text-xs px-2 py-0.5 rounded-full mt-1"
            style={{
              backgroundColor: `${domainColor}26`,
              color: domainColor,
            }}
          >
            {skill.domain}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 mt-0.5 w-6 h-6 flex items-center justify-center rounded transition-colors text-lg leading-none"
          style={{ color: 'var(--av-text-muted)' }}
        >
          ×
        </button>
      </div>

      {/* Drawer Body */}
      <div className="px-4 py-3 space-y-4 text-xs flex-1">
        {/* Version + Health */}
        <div className="flex items-center gap-3">
          {skill.version && <span style={{ color: 'var(--av-text-muted)' }}>v{skill.version}</span>}
          <div className="flex items-center gap-2 flex-1">
            <span style={{ color: 'var(--av-text-muted)' }}>Health</span>
            <div
              className="flex-1 h-2 rounded-full overflow-hidden"
              style={{ backgroundColor: 'var(--av-border)' }}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${health}%`,
                  backgroundColor:
                    health >= 70
                      ? 'var(--av-pass)'
                      : health >= 40
                        ? 'var(--av-warn)'
                        : 'var(--av-fail)',
                }}
              />
            </div>
            <span
              style={{
                color:
                  health >= 70
                    ? 'var(--av-pass)'
                    : health >= 40
                      ? 'var(--av-warn)'
                      : 'var(--av-fail)',
              }}
            >
              {health}
            </span>
          </div>
        </div>

        {/* Pain Point */}
        {skill.pain_point && (
          <div>
            <div className="font-medium mb-1" style={{ color: 'var(--av-text-secondary)' }}>
              Pain Point
            </div>
            <p style={{ color: 'var(--av-text-tertiary)', lineHeight: 1.6 }}>{skill.pain_point}</p>
          </div>
        )}

        {/* Tags */}
        {skill.tags.length > 0 && (
          <div>
            <div className="font-medium mb-1.5" style={{ color: 'var(--av-text-secondary)' }}>
              Tags
            </div>
            <div className="flex flex-wrap gap-1">
              {skill.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-1.5 py-0.5 rounded"
                  style={{
                    backgroundColor: 'var(--av-bg)',
                    color: 'var(--av-text-muted)',
                    border: '1px solid var(--av-border)',
                  }}
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Tools */}
        {skill.tools.length > 0 && (
          <div>
            <div className="font-medium mb-1.5" style={{ color: 'var(--av-text-secondary)' }}>
              Tools ({skill.tools.length})
            </div>
            <div className="flex flex-wrap gap-1">
              {skill.tools.map((tool) => (
                <span
                  key={tool}
                  className="px-1.5 py-0.5 rounded font-mono"
                  style={{
                    backgroundColor: 'rgba(137,180,250,0.1)',
                    color: 'var(--av-info)',
                    border: '1px solid rgba(137,180,250,0.2)',
                  }}
                >
                  {tool}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Triggers */}
        {skill.triggers.length > 0 && (
          <div>
            <div className="font-medium mb-1.5" style={{ color: 'var(--av-text-secondary)' }}>
              Triggers
            </div>
            <ul className="space-y-1">
              {skill.triggers.map((t, i) => (
                <li
                  key={i}
                  className="flex items-start gap-1.5"
                  style={{ color: 'var(--av-text-tertiary)' }}
                >
                  <span style={{ color: 'var(--av-accent)', marginTop: 1 }}>›</span>
                  {t}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Strengths */}
        {skill.strengths.length > 0 && (
          <div>
            <div className="font-medium mb-1.5" style={{ color: 'var(--av-text-secondary)' }}>
              Strengths
            </div>
            <ul className="space-y-1">
              {skill.strengths.map((s, i) => (
                <li
                  key={i}
                  className="flex items-start gap-1.5"
                  style={{ color: 'var(--av-text-tertiary)' }}
                >
                  <span style={{ color: 'var(--av-pass)', marginTop: 1 }}>✓</span>
                  {s}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Resources */}
        <div>
          <div className="font-medium mb-1.5" style={{ color: 'var(--av-text-secondary)' }}>
            Resources
          </div>
          <div className="flex gap-3" style={{ color: 'var(--av-text-muted)' }}>
            <span>{skill.resources.scripts} scripts</span>
            <span>{skill.resources.references} refs</span>
            <span>{skill.resources.assets} assets</span>
          </div>
        </div>

        {/* Invocations */}
        {skill.invocation_count > 0 && (
          <div style={{ color: 'var(--av-text-muted)' }}>
            呼叫次數: <span style={{ color: 'var(--av-info)' }}>{skill.invocation_count}</span>
          </div>
        )}

        {/* Guide Section */}
        {skill.guide && (
          <div>
            <button
              type="button"
              onClick={onToggleGuide}
              className="flex items-center gap-1.5 font-medium w-full text-left"
              style={{ color: 'var(--av-text-secondary)' }}
            >
              <span
                className="transition-transform"
                style={{
                  display: 'inline-block',
                  transform: guideExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                }}
              >
                ›
              </span>
              說明書
            </button>
            {guideExpanded && (
              <pre
                className="mt-2 p-3 rounded text-[11px] leading-relaxed overflow-x-auto"
                style={{
                  backgroundColor: 'var(--av-bg)',
                  border: '1px solid var(--av-border)',
                  color: 'var(--av-text-secondary)',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {skill.guide}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

import { ChevronDown, Database, MessageSquare, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ConclusionCard from '../components/ConclusionCard'
import DateNavigator from '../components/DateNavigator'
import FollowUpThread from '../components/FollowUpThread'
import MarkdownBlock from '../components/MarkdownBlock'
import TopicTabs from '../components/TopicTabs'
import { useAnalysts, useBriefingDetail, useTodaySummary, useTopics } from '../hooks/useBriefing'
import { useBriefingStore } from '../stores'
import type { Briefing, FollowUp } from '../types'

const ANALYST_COLORS: Record<string, string> = {
  claude: '#c4a7e7',
  codex: '#9ccfd8',
  gemini: '#f6c177',
}

/* ── Collapsible Section ── */
function CollapsibleSection({
  title,
  icon,
  count,
  children,
  defaultOpen = false,
}: {
  title: string
  icon: React.ReactNode
  count?: number
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border" style={{ borderColor: 'var(--bf-border)' }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full px-4 sm:px-5 py-3 cursor-pointer transition-colors"
        style={{ backgroundColor: open ? 'var(--bf-bg-elevated)' : 'transparent' }}
        onMouseEnter={(e) => {
          if (!open) e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.02)'
        }}
        onMouseLeave={(e) => {
          if (!open)
            e.currentTarget.style.backgroundColor = open ? 'var(--bf-bg-elevated)' : 'transparent'
        }}
      >
        <div className="flex items-center gap-2">
          {icon}
          <span
            className="text-xs uppercase tracking-widest"
            style={{ color: 'var(--bf-text-tertiary)' }}
          >
            {title}
          </span>
          {count !== undefined && (
            <span className="text-[10px] tabular-nums" style={{ color: 'var(--bf-text-dim)' }}>
              ({count})
            </span>
          )}
        </div>
        <ChevronDown
          size={14}
          style={{
            color: 'var(--bf-text-muted)',
            transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s ease',
          }}
        />
      </button>
      {open && (
        <div
          className="px-4 sm:px-5 pb-4 sm:pb-5 border-t"
          style={{ borderColor: 'var(--bf-border)' }}
        >
          {children}
        </div>
      )}
    </div>
  )
}

/* ── Debate Entry (editorial divider style) ── */
function DebateEntry({
  analystName,
  analystColor,
  content,
}: {
  analystName: string
  analystColor: string
  content: string
}) {
  return (
    <div className="py-5 first:pt-0 last:pb-0">
      <div className="flex items-center gap-3 mb-4">
        <div className="h-px flex-1" style={{ backgroundColor: 'var(--bf-border)' }} />
        <span
          className="text-xs font-medium tracking-wide shrink-0"
          style={{ color: analystColor }}
        >
          {analystName}
        </span>
        <div className="h-px flex-1" style={{ backgroundColor: 'var(--bf-border)' }} />
      </div>
      <MarkdownBlock content={content} />
    </div>
  )
}

/* ── Single Briefing Panel (used in tabbed view) ── */
function BriefingPanel({
  briefing,
  getAnalystInfo,
}: {
  briefing: Briefing
  getAnalystInfo: (key: string) => { label: string; color: string }
}) {
  const debateEntries: { key: string; content: string }[] = []
  const analysisEntries: Record<string, string> = {}
  const rawEntries: Record<string, string> = {}

  if (briefing.entries?.length) {
    for (const e of briefing.entries) {
      if (e.phase === 'debate') debateEntries.push({ key: e.key, content: e.content })
      else if (e.phase === 'analysis') analysisEntries[e.key] = e.content
      else if (e.phase === 'raw') rawEntries[e.key] = e.content
    }
  } else {
    if (briefing.raw_data) Object.assign(rawEntries, briefing.raw_data)
    if (briefing.analyses) Object.assign(analysisEntries, briefing.analyses)
    if (briefing.debate) debateEntries.push({ key: 'debate', content: briefing.debate })
  }

  const analysisKeys = Object.keys(analysisEntries).sort()
  const rawKeys = Object.keys(rawEntries).sort()

  return (
    <div className="space-y-8">
      {/* Conclusion */}
      {briefing.conclusion && (
        <ConclusionCard
          content={briefing.conclusion}
          confidence={(briefing.conclusion_meta?.confidence as number | null) ?? null}
          consensusPoints={(briefing.conclusion_meta?.consensus_points as string[]) || []}
          dissentPoints={
            (briefing.conclusion_meta?.dissent_points as Record<string, unknown>[]) || []
          }
        />
      )}

      {/* Debate */}
      {debateEntries.length > 0 && (
        <section>
          <div className="flex items-center gap-3 mb-6">
            <MessageSquare size={14} style={{ color: 'var(--bf-accent)' }} />
            <h2
              className="text-lg"
              style={{
                fontFamily: 'var(--bf-font-display)',
                color: 'var(--bf-text)',
                fontWeight: 400,
              }}
            >
              交叉辯論
            </h2>
            <div className="h-px flex-1" style={{ backgroundColor: 'var(--bf-border)' }} />
          </div>
          <div>
            {debateEntries.map((entry, i) => {
              const info = getAnalystInfo(entry.key)
              return (
                <DebateEntry
                  key={`debate-${i}`}
                  analystName={info.label}
                  analystColor={info.color}
                  content={entry.content}
                />
              )
            })}
          </div>
        </section>
      )}

      {/* Analysis */}
      {analysisKeys.length > 0 && (
        <CollapsibleSection
          title="分析師觀點"
          icon={<Users size={14} style={{ color: 'var(--bf-text-tertiary)' }} />}
          count={analysisKeys.length}
        >
          <div className="space-y-5 pt-4">
            {analysisKeys.map((key) => {
              const info = getAnalystInfo(key)
              return (
                <div key={key}>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-1.5 h-1.5" style={{ backgroundColor: info.color }} />
                    <span className="text-xs font-medium" style={{ color: info.color }}>
                      {info.label}
                    </span>
                  </div>
                  <div className="border-l-2 pl-4" style={{ borderColor: info.color }}>
                    <MarkdownBlock content={analysisEntries[key]} />
                  </div>
                </div>
              )
            })}
          </div>
        </CollapsibleSection>
      )}

      {/* Raw */}
      {rawKeys.length > 0 && (
        <CollapsibleSection
          title="原始資料"
          icon={<Database size={14} style={{ color: 'var(--bf-text-tertiary)' }} />}
          count={rawKeys.length}
        >
          <div className="space-y-5 pt-4">
            {rawKeys.map((key) => (
              <div key={key}>
                <div
                  className="text-[10px] uppercase tracking-widest mb-2"
                  style={{ color: 'var(--bf-text-dim)' }}
                >
                  {key}
                </div>
                <MarkdownBlock content={rawEntries[key]} />
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}
    </div>
  )
}

/* ── Main Page ── */
export default function TodayBriefing() {
  const { selectedDate, setSelectedDate } = useBriefingStore()
  const { summary, loading: summaryLoading } = useTodaySummary()
  const { briefings, loading: detailLoading } = useBriefingDetail(selectedDate)
  const { analysts } = useAnalysts()
  const { topics } = useTopics()
  const navigate = useNavigate()

  const loading = summaryLoading || detailLoading

  const getAnalystInfo = (key: string) => {
    const analyst = analysts.find((a) => a.name === key)
    return {
      label: analyst?.display_name || key,
      color: analyst?.color || ANALYST_COLORS[key] || 'var(--bf-accent)',
    }
  }

  // Determine if we should use tabbed view
  const uniqueDomains = new Set(briefings.map((b) => b.domain))
  const isLegacyMixed = briefings.length === 1 && briefings[0]?.domain === 'daily'
  const useTabbed = briefings.length > 1 && uniqueDomains.size > 1 && !isLegacyMixed

  // Tab state
  const [activeTabIndex, setActiveTabIndex] = useState(0)

  // Reset tab index when briefings change
  useEffect(() => {
    setActiveTabIndex(0)
  }, [selectedDate])

  // Active briefing for tabbed view
  const activeBriefing = useTabbed ? briefings[activeTabIndex] : null

  // For legacy mixed layout: collect all entries across all briefings
  const allDebateEntries: { key: string; content: string }[] = []
  const allAnalysisEntries: Record<string, string> = {}
  const allRawEntries: Record<string, string> = {}

  if (!useTabbed) {
    for (const b of briefings) {
      if (b.entries?.length) {
        for (const e of b.entries) {
          if (e.phase === 'debate') allDebateEntries.push({ key: e.key, content: e.content })
          else if (e.phase === 'analysis') allAnalysisEntries[e.key] = e.content
          else if (e.phase === 'raw') allRawEntries[e.key] = e.content
        }
      } else {
        if (b.raw_data) Object.assign(allRawEntries, b.raw_data)
        if (b.analyses) Object.assign(allAnalysisEntries, b.analyses)
        if (b.debate) allDebateEntries.push({ key: 'debate', content: b.debate })
      }
    }
  }

  // Primary briefing for follow-up threading
  const primaryBriefing = useTabbed
    ? activeBriefing
    : briefings.find((b) => b.domain === 'digest') ||
      briefings.find((b) => (b.entries?.length ?? 0) > 0) ||
      briefings[0]

  // Local follow-up state
  const [followUps, setFollowUps] = useState<FollowUp[]>([])
  useEffect(() => {
    setFollowUps(primaryBriefing?.follow_ups || [])
  }, [primaryBriefing?.id, primaryBriefing?.follow_ups])

  const handleNewFollowUp = (fu: FollowUp) => {
    setFollowUps((prev) => [...prev, fu])
  }

  const handleFollowUpUpdate = (updated: FollowUp) => {
    setFollowUps((prev) => prev.map((fu) => (fu.id === updated.id ? updated : fu)))
  }

  if (loading && !summary && briefings.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div
          className="h-6 w-6 animate-spin border-2 border-t-transparent"
          style={{ borderColor: 'var(--bf-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  const analysisKeys = Object.keys(allAnalysisEntries).sort()
  const rawKeys = Object.keys(allRawEntries).sort()

  return (
    <div className="p-4 sm:p-6 xl:p-8 max-w-3xl mx-auto space-y-8">
      {/* Date navigator */}
      <div className="flex justify-center">
        <DateNavigator date={selectedDate} onDateChange={setSelectedDate} />
      </div>

      {/* Status line */}
      {summary && (
        <div className="flex items-center justify-center gap-4">
          <span className="text-xs" style={{ color: 'var(--bf-text-dim)' }}>
            {summary.domains.length} 領域
          </span>
          {!useTabbed && allDebateEntries.length > 0 && (
            <span className="text-xs" style={{ color: 'var(--bf-text-dim)' }}>
              {allDebateEntries.length} 辯論
            </span>
          )}
          {summary.follow_up_count > 0 && (
            <span className="text-xs" style={{ color: 'var(--bf-text-dim)' }}>
              {summary.follow_up_count} 追問
            </span>
          )}
          {summary.status && summary.status !== 'completed' && (
            <span
              className="text-[10px] px-2 py-0.5 border bf-status-pulse"
              style={{ borderColor: 'var(--bf-accent)', color: 'var(--bf-accent)' }}
            >
              {summary.status}
            </span>
          )}
        </div>
      )}

      {/* ── TABBED VIEW ── */}
      {useTabbed && (
        <>
          <TopicTabs
            briefings={briefings}
            topics={topics}
            activeIndex={activeTabIndex}
            onSelect={setActiveTabIndex}
          />

          {activeBriefing && (
            <BriefingPanel briefing={activeBriefing} getAnalystInfo={getAnalystInfo} />
          )}
        </>
      )}

      {/* ── LEGACY MIXED VIEW ── */}
      {!useTabbed && briefings.length > 0 && (
        <>
          {/* Merged conclusion (top-level) */}
          {summary?.merged_conclusion && (
            <ConclusionCard
              content={summary.merged_conclusion}
              confidence={summary.confidence}
              consensusPoints={summary.consensus_points}
              dissentPoints={summary.dissent_points}
            />
          )}

          {/* Per-domain conclusions (fallback when no merged) */}
          {!summary?.merged_conclusion &&
            briefings.some((b) => b.conclusion) &&
            briefings
              .filter((b) => b.conclusion)
              .map((b) => (
                <div key={b.id}>
                  <div
                    className="text-[10px] uppercase tracking-widest mb-2"
                    style={{ color: 'var(--bf-text-dim)' }}
                  >
                    {b.domain}
                  </div>
                  <ConclusionCard
                    content={b.conclusion!}
                    confidence={(b.conclusion_meta?.confidence as number | null) ?? null}
                    consensusPoints={(b.conclusion_meta?.consensus_points as string[]) || []}
                    dissentPoints={
                      (b.conclusion_meta?.dissent_points as Record<string, unknown>[]) || []
                    }
                  />
                </div>
              ))}

          {/* DEBATE */}
          {allDebateEntries.length > 0 && (
            <section>
              <div className="flex items-center gap-3 mb-6">
                <MessageSquare size={14} style={{ color: 'var(--bf-accent)' }} />
                <h2
                  className="text-lg"
                  style={{
                    fontFamily: 'var(--bf-font-display)',
                    color: 'var(--bf-text)',
                    fontWeight: 400,
                  }}
                >
                  交叉辯論
                </h2>
                <div className="h-px flex-1" style={{ backgroundColor: 'var(--bf-border)' }} />
              </div>

              <div>
                {allDebateEntries.map((entry, i) => {
                  const info = getAnalystInfo(entry.key)
                  return (
                    <DebateEntry
                      key={`debate-${i}`}
                      analystName={info.label}
                      analystColor={info.color}
                      content={entry.content}
                    />
                  )
                })}
              </div>
            </section>
          )}

          {/* ANALYSIS */}
          {analysisKeys.length > 0 && (
            <CollapsibleSection
              title="分析師觀點"
              icon={<Users size={14} style={{ color: 'var(--bf-text-tertiary)' }} />}
              count={analysisKeys.length}
            >
              <div className="space-y-5 pt-4">
                {analysisKeys.map((key) => {
                  const info = getAnalystInfo(key)
                  return (
                    <div key={key}>
                      <div className="flex items-center gap-2 mb-2">
                        <div className="w-1.5 h-1.5" style={{ backgroundColor: info.color }} />
                        <span className="text-xs font-medium" style={{ color: info.color }}>
                          {info.label}
                        </span>
                      </div>
                      <div className="border-l-2 pl-4" style={{ borderColor: info.color }}>
                        <MarkdownBlock content={allAnalysisEntries[key]} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </CollapsibleSection>
          )}

          {/* RAW DATA */}
          {rawKeys.length > 0 && (
            <CollapsibleSection
              title="原始資料"
              icon={<Database size={14} style={{ color: 'var(--bf-text-tertiary)' }} />}
              count={rawKeys.length}
            >
              <div className="space-y-5 pt-4">
                {rawKeys.map((key) => (
                  <div key={key}>
                    <div
                      className="text-[10px] uppercase tracking-widest mb-2"
                      style={{ color: 'var(--bf-text-dim)' }}
                    >
                      {key}
                    </div>
                    <MarkdownBlock content={allRawEntries[key]} />
                  </div>
                ))}
              </div>
            </CollapsibleSection>
          )}
        </>
      )}

      {/* ── FOLLOW-UP ── */}
      {primaryBriefing && (
        <FollowUpThread
          briefingId={primaryBriefing.id}
          followUps={followUps}
          onNewFollowUp={handleNewFollowUp}
          onFollowUpUpdate={handleFollowUpUpdate}
        />
      )}

      {/* Empty state */}
      {briefings.length === 0 && !loading && (
        <div
          className="border p-8 text-center"
          style={{
            backgroundColor: 'var(--bf-bg-elevated)',
            borderColor: 'var(--bf-border)',
          }}
        >
          <p className="text-sm mb-3" style={{ color: 'var(--bf-text-dim)' }}>
            {selectedDate} 尚無簡報資料
          </p>
          <button
            type="button"
            onClick={() => navigate('/briefing/config')}
            className="text-xs px-3 py-1.5 border transition-colors cursor-pointer"
            style={{
              borderColor: 'var(--bf-accent)',
              color: 'var(--bf-accent)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--bf-accent)'
              e.currentTarget.style.color = 'var(--bf-text-on-accent)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
              e.currentTarget.style.color = 'var(--bf-accent)'
            }}
          >
            前往設定主題
          </button>
        </div>
      )}
    </div>
  )
}

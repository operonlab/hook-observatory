import { Database, MessageSquare, Users } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ConclusionCard from '../components/ConclusionCard'
import DateNavigator from '../components/DateNavigator'
import DebateBubble from '../components/DebateBubble'
import DomainSection from '../components/DomainSection'
import FollowUpThread from '../components/FollowUpThread'
import MarkdownBlock from '../components/MarkdownBlock'
import { useAnalysts, useBriefingDetail, useTodaySummary } from '../hooks/useBriefing'
import { useBriefingStore } from '../stores'
import type { Briefing, FollowUp } from '../types'

const ANALYST_COLORS: Record<string, string> = {
  claude: '#c4a7e7',
  codex: '#9ccfd8',
  gemini: '#f6c177',
}

type DetailTab = 'analyses' | 'debate' | 'raw'

function BriefingDomainDetail({ briefing }: { briefing: Briefing }) {
  const [activeTab, setActiveTab] = useState<DetailTab>('analyses')
  const { analysts } = useAnalysts()
  const [followUps, setFollowUps] = useState<FollowUp[]>(briefing.follow_ups || [])

  // Collect entries by phase
  const rawEntries: Record<string, string> = {}
  const analysisEntries: Record<string, string> = {}
  const debateEntries: { key: string; content: string }[] = []

  if (briefing.entries?.length) {
    for (const e of briefing.entries) {
      if (e.phase === 'raw') rawEntries[e.key] = e.content
      else if (e.phase === 'analysis') analysisEntries[e.key] = e.content
      else if (e.phase === 'debate') debateEntries.push({ key: e.key, content: e.content })
    }
  } else {
    if (briefing.raw_data) Object.assign(rawEntries, briefing.raw_data)
    if (briefing.analyses) Object.assign(analysisEntries, briefing.analyses)
    if (briefing.debate) debateEntries.push({ key: 'debate', content: briefing.debate })
  }

  const analysisKeys = Object.keys(analysisEntries).sort()
  const rawKeys = Object.keys(rawEntries).sort()

  const tabs: { id: DetailTab; label: string; icon: React.ReactNode; disabled?: boolean }[] = [
    { id: 'analyses', label: '分析師觀點', icon: <Users size={14} /> },
    { id: 'debate', label: '交叉辯論', icon: <MessageSquare size={14} />, disabled: debateEntries.length === 0 },
    { id: 'raw', label: '原始資料', icon: <Database size={14} />, disabled: rawKeys.length === 0 },
  ]

  const getAnalystInfo = (key: string) => {
    const analyst = analysts.find((a) => a.name === key)
    return {
      label: analyst?.display_name || key,
      color: analyst?.color || ANALYST_COLORS[key] || 'var(--bf-accent)',
    }
  }

  const handleNewFollowUp = (fu: FollowUp) => {
    setFollowUps((prev) => [...prev, fu])
  }

  return (
    <div className="space-y-4">
      {/* Conclusion first */}
      {briefing.conclusion && (
        <ConclusionCard
          content={briefing.conclusion}
          confidence={briefing.conclusion_meta?.confidence as number | null ?? null}
          consensusPoints={(briefing.conclusion_meta?.consensus_points as string[]) || []}
          dissentPoints={(briefing.conclusion_meta?.dissent_points as Record<string, unknown>[]) || []}
        />
      )}

      {/* Tab bar */}
      <div className="flex border-b" style={{ borderColor: 'var(--bf-border)' }}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => !tab.disabled && setActiveTab(tab.id)}
            disabled={tab.disabled}
            className="flex items-center gap-1.5 px-4 py-3 text-xs transition-colors disabled:opacity-30"
            style={{
              color: activeTab === tab.id ? 'var(--bf-accent)' : 'var(--bf-text-tertiary)',
              borderBottom: activeTab === tab.id ? '2px solid var(--bf-accent)' : '2px solid transparent',
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
          {analysisKeys.length > 0 ? (
            analysisKeys.map((key) => {
              const info = getAnalystInfo(key)
              return (
                <div
                  key={key}
                  className="border"
                  style={{
                    backgroundColor: 'var(--bf-bg-elevated)',
                    borderColor: 'var(--bf-border)',
                    borderLeftWidth: 3,
                    borderLeftColor: info.color,
                  }}
                >
                  <div className="px-4 sm:px-5 py-3 border-b" style={{ borderColor: 'var(--bf-border)' }}>
                    <span className="text-sm font-medium" style={{ color: info.color }}>
                      {info.label}
                    </span>
                  </div>
                  <div className="px-4 sm:px-5 py-4">
                    <MarkdownBlock content={analysisEntries[key]} />
                  </div>
                </div>
              )
            })
          ) : (
            <div
              className="border p-8 text-center text-sm"
              style={{
                backgroundColor: 'var(--bf-bg-elevated)',
                borderColor: 'var(--bf-border)',
                color: 'var(--bf-text-dim)',
              }}
            >
              無分析資料
            </div>
          )}
        </div>
      )}

      {activeTab === 'debate' && (
        <div className="space-y-3">
          {debateEntries.map((entry, i) => {
            const info = getAnalystInfo(entry.key)
            return (
              <DebateBubble
                key={i}
                analystName={info.label}
                analystColor={info.color}
                content={entry.content}
                side={i % 2 === 0 ? 'left' : 'right'}
              />
            )
          })}
        </div>
      )}

      {activeTab === 'raw' && (
        <div className="space-y-3">
          {rawKeys.map((key) => (
            <div
              key={key}
              className="border"
              style={{ backgroundColor: 'var(--bf-bg-elevated)', borderColor: 'var(--bf-border)' }}
            >
              <div className="px-4 sm:px-5 py-3 border-b" style={{ borderColor: 'var(--bf-border)' }}>
                <span
                  className="text-xs uppercase tracking-widest"
                  style={{ color: 'var(--bf-text-tertiary)' }}
                >
                  {key}
                </span>
              </div>
              <div className="px-4 sm:px-5 py-4">
                <MarkdownBlock content={rawEntries[key]} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Follow-up thread */}
      <FollowUpThread
        briefingId={briefing.id}
        followUps={followUps}
        onNewFollowUp={handleNewFollowUp}
      />
    </div>
  )
}

export default function TodayBriefing() {
  const { selectedDate, setSelectedDate } = useBriefingStore()
  const { summary, loading: summaryLoading } = useTodaySummary()
  const { briefings, loading: detailLoading } = useBriefingDetail(selectedDate)
  const navigate = useNavigate()

  const loading = summaryLoading || detailLoading

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

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-6">
      {/* Date navigator */}
      <div className="flex justify-center">
        <DateNavigator date={selectedDate} onDateChange={setSelectedDate} />
      </div>

      {/* Status badges */}
      {summary && (
        <div className="flex flex-wrap items-center justify-center gap-3">
          <span className="text-xs" style={{ color: 'var(--bf-text-dim)' }}>
            {summary.domains.length} 領域
          </span>
          {summary.follow_up_count > 0 && (
            <span className="text-xs" style={{ color: 'var(--bf-text-dim)' }}>
              {summary.follow_up_count} 追問
            </span>
          )}
          {summary.status && summary.status !== 'completed' && (
            <span
              className="text-[10px] px-2 py-0.5 border animate-pulse"
              style={{ borderColor: 'var(--bf-accent)', color: 'var(--bf-accent)' }}
            >
              {summary.status}
            </span>
          )}
        </div>
      )}

      {/* Merged conclusion (top-level) */}
      {summary?.merged_conclusion && (
        <ConclusionCard
          content={summary.merged_conclusion}
          confidence={summary.confidence}
          consensusPoints={summary.consensus_points}
          dissentPoints={summary.dissent_points}
        />
      )}

      {/* Domain sections */}
      {briefings.length > 0 ? (
        <div className="space-y-4">
          {briefings.map((b) => {
            const domainInfo = summary?.domains.find((d) => d.briefing_id === b.id)
            return (
              <DomainSection
                key={b.id}
                domain={
                  domainInfo || {
                    domain: b.domain,
                    display_name: b.domain,
                    briefing_id: b.id,
                    status: b.status,
                    sources_count: 0,
                    analysts_count: 0,
                    has_conclusion: !!b.conclusion,
                  }
                }
                defaultOpen={briefings.length === 1}
              >
                <BriefingDomainDetail briefing={b} />
              </DomainSection>
            )
          })}
        </div>
      ) : (
        !loading && (
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
              onClick={() => navigate('/briefing/config')}
              className="text-xs px-3 py-1.5 border transition-colors"
              style={{ borderColor: 'var(--bf-accent)', color: 'var(--bf-accent)' }}
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
        )
      )}
    </div>
  )
}

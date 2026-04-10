import { useState } from 'react'
import { useCommunities, useSummaries } from '../hooks/queries'
import type { CommunitySummary, Community } from '../types'
import InfoTip from './InfoTip'

function SummaryCard({ summary, community }: { summary: CommunitySummary; community?: Community }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <button
      onClick={() => setExpanded(!expanded)}
      className="w-full text-left rounded-xl border p-4 transition-all duration-200"
      style={{
        backgroundColor: expanded ? 'var(--mantle)' : 'var(--base)',
        borderColor: expanded ? 'var(--peach)' : 'var(--surface0)',
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {community && (
            <div className="flex items-center gap-2 mb-1">
              <span
                className="inline-block h-2 w-2 rounded-full shrink-0"
                style={{ backgroundColor: 'var(--blue)' }}
              />
              <span className="text-xs font-medium" style={{ color: 'var(--blue)' }}>
                {community.name}
              </span>
              {community.size > 0 && (
                <span className="text-[10px]" style={{ color: 'var(--subtext1)' }}>
                  {community.size} entities
                </span>
              )}
            </div>
          )}
          <p className="text-sm leading-relaxed" style={{ color: 'var(--text)' }}>
            {summary.summary}
          </p>
        </div>
      </div>

      {/* Tags */}
      {summary.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {summary.tags.slice(0, 5).map((tag) => (
            <span
              key={tag}
              className="rounded px-2 py-0.5 text-[11px]"
              style={{
                backgroundColor: 'color-mix(in srgb, var(--teal) 12%, transparent)',
                color: 'var(--teal)',
              }}
            >
              {tag}
            </span>
          ))}
          {summary.tags.length > 5 && (
            <span className="text-[11px] py-0.5" style={{ color: 'var(--subtext1)' }}>
              +{summary.tags.length - 5}
            </span>
          )}
        </div>
      )}

      {/* Expanded: key findings */}
      {expanded && summary.key_findings.length > 0 && (
        <div className="mt-3 pt-3 border-t" style={{ borderColor: 'var(--surface0)' }}>
          <p
            className="text-[11px] uppercase tracking-[0.14em] mb-2"
            style={{ color: 'var(--subtext1)' }}
          >
            Key Findings
          </p>
          <ul className="space-y-1.5">
            {summary.key_findings.map((finding, i) => (
              <li
                key={i}
                className="text-xs leading-relaxed flex gap-2"
                style={{ color: 'var(--subtext0)' }}
              >
                <span className="shrink-0" style={{ color: 'var(--peach)' }}>
                  •
                </span>
                {finding}
              </li>
            ))}
          </ul>
          {summary.evidence_count != null && summary.evidence_count > 0 && (
            <p className="text-[10px] mt-2" style={{ color: 'var(--subtext1)' }}>
              {summary.evidence_count} evidence triples
            </p>
          )}
        </div>
      )}
    </button>
  )
}

export default function CommunityInsights() {
  const { data: summaries = [], isLoading: loadingSummaries } = useSummaries()
  const { data: communities = [] } = useCommunities()

  const communityMap = new Map(communities.map((c) => [c.id, c]))

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <div
          className="h-3 w-3 rounded-full shrink-0"
          style={{ backgroundColor: 'var(--peach)' }}
        />
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
          Community Insights
        </h3>
        <InfoTip text="由 Leiden 演算法自動偵測的知識社群，LLM 生成摘要與關鍵發現。點擊卡片展開查看 key findings。" />
        {summaries.length > 0 && (
          <span className="text-xs" style={{ color: 'var(--subtext0)' }}>
            {summaries.length} summaries
          </span>
        )}
      </div>

      {loadingSummaries && summaries.length === 0 ? (
        <div className="flex justify-center py-8">
          <div
            className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
            style={{ borderColor: 'var(--peach)', borderTopColor: 'transparent' }}
          />
        </div>
      ) : summaries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 gap-2">
          <p className="text-sm" style={{ color: 'var(--subtext0)' }}>
            尚無社群洞察
          </p>
          <p className="text-xs" style={{ color: 'var(--subtext1)' }}>
            知識圖譜累積足夠三元組後，Dream Loop 會自動生成社群摘要
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {summaries.map((s) => (
            <SummaryCard
              key={s.id}
              summary={s}
              community={communityMap.get(s.community_id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

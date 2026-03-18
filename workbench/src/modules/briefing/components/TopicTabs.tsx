import type { Briefing, BriefingTopic } from '../types'

const TOPIC_ACCENT_COLORS: Record<string, string> = {
  news: '#c9a962',
  tech: '#9ccfd8',
  weather: '#f6c177',
  finance: '#c4a7e7',
  digest: '#c9a962',
  politics: '#eb6f92',
  sports: '#31748f',
  health: '#4ade80',
}

function getTopicAccent(domain: string): string {
  return TOPIC_ACCENT_COLORS[domain] || 'var(--bf-accent)'
}

interface TopicTabsProps {
  briefings: Briefing[]
  topics: BriefingTopic[]
  activeIndex: number
  onSelect: (index: number) => void
}

export default function TopicTabs({ briefings, topics, activeIndex, onSelect }: TopicTabsProps) {
  return (
    <div
      className="flex gap-0 overflow-x-auto border-b"
      style={{ borderColor: 'var(--bf-border)' }}
    >
      {briefings.map((b, i) => {
        const isActive = i === activeIndex
        const topic = topics.find((t) => t.id === b.topic_id)
        const label = topic?.display_name || b.domain
        const accent = getTopicAccent(b.domain)
        const statusIcon =
          b.status === 'completed' ? '\u2713' : b.status === 'failed' ? '\u2717' : null

        return (
          <button
            type="button"
            key={b.id}
            onClick={() => onSelect(i)}
            className="relative px-4 py-2.5 text-sm whitespace-nowrap transition-colors shrink-0"
            style={{
              color: isActive ? accent : 'var(--bf-text-muted)',
              backgroundColor: isActive ? 'var(--bf-bg-elevated)' : 'transparent',
              borderBottom: isActive ? `2px solid ${accent}` : '2px solid transparent',
            }}
          >
            <span className="flex items-center gap-2">
              {label}
              {statusIcon && (
                <span
                  className="text-[10px]"
                  style={{
                    color:
                      b.status === 'completed'
                        ? 'var(--bf-confidence-high)'
                        : 'var(--bf-confidence-low)',
                  }}
                >
                  {statusIcon}
                </span>
              )}
              {b.status === 'processing' && (
                <span
                  className="bf-status-pulse inline-block w-1.5 h-1.5"
                  style={{ backgroundColor: accent }}
                />
              )}
            </span>
          </button>
        )
      })}
    </div>
  )
}

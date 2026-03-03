import { FileText, Hash } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { Topic } from '../types'

interface TopicCardProps {
  topic: Topic
}

export default function TopicCard({ topic }: TopicCardProps) {
  const navigate = useNavigate()

  return (
    <button
      onClick={() => navigate(`/intelflow/topics/${topic.id}`)}
      className="flex flex-col gap-3 border p-4 sm:p-5 text-left transition-colors min-h-[80px] w-full"
      style={{
        backgroundColor: 'var(--if-bg-elevated)',
        borderColor: 'var(--if-border)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--if-accent)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--if-border)'
      }}
    >
      <div className="flex items-center gap-2">
        <Hash size={14} style={{ color: 'var(--if-accent)', flexShrink: 0 }} />
        <span className="text-sm font-medium leading-snug" style={{ color: 'var(--if-text)' }}>
          {topic.display_name || topic.name}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <FileText size={12} style={{ color: 'var(--if-text-dim)' }} />
        <span className="text-xs" style={{ color: 'var(--if-text-tertiary)' }}>
          {topic.report_count} 篇報告
        </span>
      </div>
    </button>
  )
}

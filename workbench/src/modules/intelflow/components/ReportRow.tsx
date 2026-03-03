import { ChevronRight, FileText } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { Report, ReportBrief } from '../types'

interface ReportRowProps {
  report: Report | ReportBrief
}

export default function ReportRow({ report }: ReportRowProps) {
  const navigate = useNavigate()

  const date = new Date(report.created_at).toLocaleDateString('zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })

  return (
    <button
      onClick={() => navigate(`/intelflow/reports/${report.id}`)}
      className="flex w-full items-center gap-3 border-b px-4 py-4 text-left transition-colors min-h-[60px]"
      style={{ borderColor: 'var(--if-border)' }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = 'var(--if-bg-surface)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'transparent'
      }}
    >
      <FileText size={15} style={{ color: 'var(--if-text-muted)', flexShrink: 0 }} />

      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium leading-snug" style={{ color: 'var(--if-text)' }}>
          {report.title}
        </div>
        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
          <span className="text-xs" style={{ color: 'var(--if-text-dim)' }}>
            {date}
          </span>
          <div className="hidden sm:flex gap-1 flex-wrap">
            {report.tags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="text-[10px] px-1.5 py-0.5 border"
                style={{
                  borderColor: 'var(--if-border)',
                  color: 'var(--if-text-tertiary)',
                }}
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>

      {'skill_name' in report && report.skill_name && (
        <span
          className="hidden md:inline text-xs px-2 py-0.5 border shrink-0"
          style={{
            borderColor: 'var(--if-accent)',
            color: 'var(--if-accent)',
          }}
        >
          {report.skill_name}
        </span>
      )}

      <ChevronRight size={14} style={{ color: 'var(--if-text-dim)', flexShrink: 0 }} />
    </button>
  )
}

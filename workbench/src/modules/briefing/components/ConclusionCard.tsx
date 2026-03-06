import { CheckCircle2, Shield } from 'lucide-react'
import ConfidenceMeter from './ConfidenceMeter'
import MarkdownBlock from './MarkdownBlock'

interface ConclusionCardProps {
  content: string
  confidence: number | null
  consensusPoints: string[]
  dissentPoints: Record<string, unknown>[]
}

export default function ConclusionCard({
  content,
  confidence,
  consensusPoints,
  dissentPoints,
}: ConclusionCardProps) {
  return (
    <div
      className="border"
      style={{
        backgroundColor: 'var(--bf-conclusion-bg)',
        borderColor: 'var(--bf-conclusion-border)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 sm:px-5 py-3 border-b"
        style={{ borderColor: 'var(--bf-conclusion-border)' }}
      >
        <div className="flex items-center gap-2">
          <Shield size={14} style={{ color: 'var(--bf-confidence-high)' }} />
          <span
            className="text-xs uppercase tracking-widest"
            style={{ color: 'var(--bf-confidence-high)' }}
          >
            綜合結論
          </span>
        </div>
        {confidence !== null && <ConfidenceMeter value={confidence} />}
      </div>

      {/* Conclusion body */}
      <div className="px-4 sm:px-5 py-4">
        <MarkdownBlock content={content} />
      </div>

      {/* Consensus points */}
      {consensusPoints.length > 0 && (
        <div
          className="px-4 sm:px-5 py-3 border-t"
          style={{ borderColor: 'var(--bf-conclusion-border)' }}
        >
          <h4
            className="text-[10px] uppercase tracking-widest mb-2"
            style={{ color: 'var(--bf-text-tertiary)' }}
          >
            共識要點
          </h4>
          <ul className="space-y-1.5">
            {consensusPoints.map((point, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <CheckCircle2
                  size={12}
                  className="mt-0.5 shrink-0"
                  style={{ color: 'var(--bf-confidence-high)' }}
                />
                <span style={{ color: 'var(--bf-text-secondary)' }}>{point}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Dissent points */}
      {dissentPoints.length > 0 && (
        <div
          className="px-4 sm:px-5 py-3 border-t"
          style={{ borderColor: 'var(--bf-conclusion-border)' }}
        >
          <h4
            className="text-[10px] uppercase tracking-widest mb-2"
            style={{ color: 'var(--bf-text-tertiary)' }}
          >
            分歧觀點
          </h4>
          <ul className="space-y-1.5">
            {dissentPoints.map((point, i) => (
              <li key={i} className="text-sm" style={{ color: 'var(--bf-text-muted)' }}>
                {typeof point === 'string'
                  ? point
                  : (point as Record<string, string>).summary ||
                    (point as Record<string, string>).point ||
                    JSON.stringify(point)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

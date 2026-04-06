import type { CoverageGap } from '../types'

interface Props {
  gaps: CoverageGap[]
}

const GAP_TYPE_LABEL: Record<string, string> = {
  topic_missing: 'Topic Missing',
  depth_insufficient: 'Insufficient Depth',
  outdated: 'Outdated',
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-700',
  investigating: 'bg-blue-100 text-blue-700',
  resolved: 'bg-green-100 text-green-700',
  dismissed: 'bg-gray-100 text-gray-500',
}

export default function CoverageGapList({ gaps }: Props) {
  if (!gaps.length) {
    return (
      <p className="py-2 text-sm text-gray-400">No coverage gaps found.</p>
    )
  }

  return (
    <div className="space-y-2">
      {gaps.map((gap) => (
        <div key={gap.id} className="rounded-lg border p-3">
          <div className="mb-1 flex items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-xs ${
                STATUS_COLOR[gap.status] || 'bg-gray-100'
              }`}
            >
              {gap.status}
            </span>
            <span className="text-xs text-gray-400">
              {GAP_TYPE_LABEL[gap.gap_type] || gap.gap_type}
            </span>
            <span className="ml-auto text-xs text-gray-300">
              {new Date(gap.detected_at).toLocaleDateString()}
            </span>
          </div>
          <p className="text-sm line-clamp-2">{gap.query_text}</p>
          {gap.resolution && (
            <div className="mt-1 text-xs text-green-600">
              Resolved: {gap.resolution}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

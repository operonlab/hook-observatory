import type { Document, DocumentBrief } from '../types'

interface Props {
  document: Document | DocumentBrief
  compact?: boolean
}

const STATUS_COLORS: Record<string, string> = {
  ingested: 'bg-yellow-100 text-yellow-700',
  processing: 'bg-blue-100 text-blue-700',
  indexed: 'bg-indigo-100 text-indigo-700',
  enriched: 'bg-purple-100 text-purple-700',
  published: 'bg-green-100 text-green-700',
  archived: 'bg-gray-100 text-gray-500',
  failed: 'bg-red-100 text-red-700',
}

export default function DocumentCard({ document: doc, compact }: Props) {
  const colorClass = STATUS_COLORS[doc.status] || 'bg-gray-100 text-gray-600'

  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm transition hover:shadow-md">
      <div className="mb-2 flex items-start justify-between">
        <h3 className={`font-medium ${compact ? 'text-sm' : 'text-base'}`}>
          {doc.title}
        </h3>
        <span className={`rounded-full px-2 py-0.5 text-xs ${colorClass}`}>
          {doc.status}
        </span>
      </div>

      <div className="mb-2 flex flex-wrap gap-1">
        {doc.tags.map((tag) => (
          <span
            key={tag}
            className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600"
          >
            {tag}
          </span>
        ))}
      </div>

      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>{doc.source_type}</span>
        <span>{new Date(doc.created_at).toLocaleDateString()}</span>
      </div>

      {'confidence' in doc && doc.confidence != null && (
        <div className="mt-2">
          <div className="h-1.5 w-full rounded-full bg-gray-200">
            <div
              className="h-1.5 rounded-full bg-blue-500"
              style={{ width: `${Math.round(doc.confidence * 100)}%` }}
            />
          </div>
          <span className="text-xs text-gray-400">
            Confidence: {Math.round(doc.confidence * 100)}%
          </span>
        </div>
      )}
    </div>
  )
}

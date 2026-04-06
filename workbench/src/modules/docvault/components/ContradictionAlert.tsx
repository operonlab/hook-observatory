import type { Contradiction } from '../types'

interface Props {
  contradictions: Contradiction[]
  documentTitle?: string
}

export default function ContradictionAlert({ contradictions, documentTitle }: Props) {
  if (!contradictions.length) return null

  return (
    <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-lg">⚠️</span>
        <h3 className="text-sm font-semibold text-yellow-800">
          {contradictions.length} Contradiction{contradictions.length > 1 ? 's' : ''} Detected
          {documentTitle && ` — ${documentTitle}`}
        </h3>
      </div>

      <div className="space-y-3">
        {contradictions.map((c) => (
          <div key={c.relation_id} className="rounded border border-yellow-100 bg-white p-3">
            <div className="mb-1 flex items-center gap-2 text-sm">
              <span className="font-medium text-yellow-700">
                vs. {c.other_document_title}
              </span>
              {c.confidence != null && (
                <span className="text-xs text-gray-400">
                  ({Math.round(c.confidence * 100)}% confidence)
                </span>
              )}
            </div>
            {c.evidence && (
              <p className="text-xs text-gray-600 line-clamp-3">
                {c.evidence}
              </p>
            )}
            <div className="mt-1 text-xs text-gray-300">
              {c.created_at && new Date(c.created_at).toLocaleDateString()}
              {c.source_chunk_id && ` · chunk: ${c.source_chunk_id.slice(0, 8)}`}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

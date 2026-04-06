import type { CitationRef } from '../types'

interface Props {
  citations: CitationRef[]
}

export default function CitationPanel({ citations }: Props) {
  if (!citations.length) return null

  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold text-gray-700">
        Citations ({citations.length})
      </h3>
      <div className="space-y-3">
        {citations.map((cite, i) => (
          <div key={`${cite.document_id}-${i}`} className="rounded-lg border bg-white p-3">
            <div className="mb-1 flex items-center gap-2 text-xs">
              <span className="rounded bg-blue-100 px-1.5 py-0.5 font-mono text-blue-700">
                [{i + 1}]
              </span>
              {cite.section && (
                <span className="text-gray-500">{cite.section}</span>
              )}
              {cite.page && (
                <span className="text-gray-400">p.{cite.page}</span>
              )}
            </div>
            {cite.quote && (
              <p className="mt-1 border-l-2 border-blue-200 pl-2 text-xs italic text-gray-600">
                &ldquo;{cite.quote}&rdquo;
              </p>
            )}
            <div className="mt-1 text-xs text-gray-300">
              doc: {cite.document_id.slice(0, 8)}
              {cite.chunk_id && ` · chunk: ${cite.chunk_id.slice(0, 8)}`}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

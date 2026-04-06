import type { DocumentChunk } from '../types'

interface Props {
  chunks: DocumentChunk[]
  highlightQuery?: string
}

function highlightText(text: string, query: string | undefined) {
  if (!query) return text
  const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'))
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? (
      <mark key={i} className="bg-yellow-200 px-0.5">
        {part}
      </mark>
    ) : (
      part
    ),
  )
}

export default function ChunkViewer({ chunks, highlightQuery }: Props) {
  if (!chunks.length) {
    return <p className="py-4 text-center text-sm text-gray-400">No chunks available.</p>
  }

  return (
    <div className="space-y-3">
      {chunks.map((chunk) => (
        <div key={chunk.id} className="rounded-lg border p-3">
          <div className="mb-1 flex items-center gap-2 text-xs text-gray-400">
            <span className="font-mono">#{chunk.chunk_index}</span>
            {chunk.section_path && <span>· {chunk.section_path}</span>}
            {chunk.page_range && <span>· p.{chunk.page_range}</span>}
            <span className="rounded bg-gray-100 px-1">{chunk.chunk_type}</span>
            <span className="ml-auto">{chunk.token_count} tokens</span>
          </div>
          {chunk.heading && (
            <div className="mb-1 text-sm font-medium">{chunk.heading}</div>
          )}
          <p className="whitespace-pre-wrap text-sm leading-relaxed">
            {highlightText(chunk.content, highlightQuery)}
          </p>
        </div>
      ))}
    </div>
  )
}

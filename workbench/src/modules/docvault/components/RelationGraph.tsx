import { useRelationsQuery } from '../hooks/queries'
import type { DocumentRelation } from '../types'

interface Props {
  documentId: string
}

const RELATION_ICONS: Record<string, string> = {
  cites: '📎',
  extends: '📐',
  contradicts: '⚡',
  supersedes: '🔄',
  related: '🔗',
}

export default function RelationGraph({ documentId }: Props) {
  const { data, isLoading } = useRelationsQuery(documentId)
  const relations = data?.items ?? []

  if (isLoading) {
    return <div className="py-4 text-center text-sm text-gray-400">Loading relations...</div>
  }

  if (!relations.length) {
    return (
      <div className="rounded-lg border border-dashed p-4 text-center text-sm text-gray-400">
        No document relations found.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-gray-700">
        Document Relations ({relations.length})
      </h3>
      {relations.map((rel) => (
        <RelationEdge key={rel.id} relation={rel} currentDocId={documentId} />
      ))}
    </div>
  )
}

function RelationEdge({
  relation: rel,
  currentDocId,
}: {
  relation: DocumentRelation
  currentDocId: string
}) {
  const icon = RELATION_ICONS[rel.relation_type] || '🔗'
  const isSource = rel.source_document_id === currentDocId
  const otherId = isSource ? rel.target_document_id : rel.source_document_id
  const direction = isSource ? '→' : '←'

  return (
    <div className="flex items-center gap-2 rounded-lg border p-3 text-sm">
      <span className="text-lg">{icon}</span>
      <div className="flex-1">
        <div className="flex items-center gap-1">
          <span className="font-mono text-xs text-gray-400">
            {currentDocId.slice(0, 8)}
          </span>
          <span className="text-gray-400">{direction}</span>
          <span className="rounded bg-gray-100 px-1 text-xs">{rel.relation_type}</span>
          <span className="text-gray-400">{direction}</span>
          <span className="font-mono text-xs text-gray-400">{otherId.slice(0, 8)}</span>
        </div>
        {rel.evidence && (
          <p className="mt-1 text-xs text-gray-500 line-clamp-2">{rel.evidence}</p>
        )}
      </div>
      {rel.confidence != null && (
        <span className="text-xs text-gray-400">
          {Math.round(rel.confidence * 100)}%
        </span>
      )}
    </div>
  )
}

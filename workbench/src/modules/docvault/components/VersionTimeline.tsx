import { useVersionsQuery } from '../hooks/queries'

interface Props {
  documentId: string
}

const VERSION_STATUS_COLOR: Record<string, string> = {
  processing: 'border-blue-400 bg-blue-50',
  ready: 'border-green-400 bg-green-50',
  superseded: 'border-gray-300 bg-gray-50',
}

export default function VersionTimeline({ documentId }: Props) {
  const { data, isLoading } = useVersionsQuery(documentId)
  const versions = data?.items ?? []

  if (isLoading) {
    return <div className="py-4 text-center text-sm text-gray-400">Loading versions...</div>
  }

  if (!versions.length) {
    return (
      <div className="rounded-lg border border-dashed p-4 text-center text-sm text-gray-400">
        No versions found.
      </div>
    )
  }

  return (
    <div className="space-y-0">
      <h3 className="mb-3 text-sm font-semibold text-gray-700">
        Version History ({versions.length})
      </h3>
      <div className="relative border-l-2 border-gray-200 pl-4">
        {versions.map((v) => {
          const colorClass = VERSION_STATUS_COLOR[v.status] || 'border-gray-300 bg-gray-50'
          return (
            <div key={v.id} className="relative mb-4 last:mb-0">
              {/* Dot on timeline */}
              <div
                className={`absolute -left-[1.35rem] top-1 h-3 w-3 rounded-full border-2 ${colorClass}`}
              />
              <div className="rounded-lg border p-3">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-semibold">v{v.version_number}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs ${
                      v.status === 'ready'
                        ? 'bg-green-100 text-green-700'
                        : v.status === 'processing'
                          ? 'bg-blue-100 text-blue-700'
                          : 'bg-gray-100 text-gray-500'
                    }`}
                  >
                    {v.status}
                  </span>
                  <span className="ml-auto text-xs text-gray-400">
                    {new Date(v.created_at).toLocaleDateString()}
                  </span>
                </div>
                <div className="mt-1 flex gap-3 text-xs text-gray-500">
                  <span>{v.chunk_count} chunks</span>
                  {v.extraction_model && <span>Model: {v.extraction_model}</span>}
                </div>
                {v.summary && (
                  <p className="mt-1 text-xs text-gray-600 line-clamp-2">{v.summary}</p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

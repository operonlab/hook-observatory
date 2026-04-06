import { useState } from 'react'
import { useDocumentsQuery, useSearchQuery } from '../hooks/queries'
import { useDocvaultStore } from '../stores'
import DocumentCard from '../components/DocumentCard'
import UploadDropzone from '../components/UploadDropzone'

export default function BrowserPage() {
  const store = useDocvaultStore()
  const [showUpload, setShowUpload] = useState(false)

  const { data: documents, isLoading } = useDocumentsQuery({
    page: store.documentsPage,
    tags: store.activeTag,
    status: store.activeStatus,
  })

  const { data: searchResults } = useSearchQuery(store.searchQuery)

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Document Browser</h1>
        <button
          onClick={() => setShowUpload(!showUpload)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
        >
          {showUpload ? 'Close Upload' : 'Upload Document'}
        </button>
      </div>

      {showUpload && <UploadDropzone onUploaded={() => setShowUpload(false)} />}

      {/* Search Bar */}
      <div className="flex gap-3">
        <input
          type="text"
          value={store.searchQuery}
          onChange={(e) => store.setSearchQuery(e.target.value)}
          placeholder="Search documents..."
          className="flex-1 rounded-lg border px-4 py-2 text-sm"
        />
        {store.searchQuery && (
          <button
            onClick={store.clearSearch}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Clear
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="flex gap-2 text-sm">
        {['all', 'ingested', 'processing', 'indexed', 'enriched', 'published', 'archived'].map(
          (s) => (
            <button
              key={s}
              onClick={() => store.setActiveStatus(s === 'all' ? null : s)}
              className={`rounded-full px-3 py-1 ${
                (s === 'all' && !store.activeStatus) || store.activeStatus === s
                  ? 'bg-blue-100 text-blue-700'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {s}
            </button>
          ),
        )}
      </div>

      {/* Search Results */}
      {store.searchQuery && searchResults?.results?.length ? (
        <section>
          <h2 className="mb-2 text-lg font-semibold">
            Search Results ({searchResults.results.length})
          </h2>
          <div className="space-y-2">
            {searchResults.results.map((chunk, i) => (
              <div key={`${chunk.document_id}-${i}`} className="rounded-lg border p-3 text-sm">
                <div className="mb-1 text-xs text-gray-400">
                  {chunk.section_path || 'Unknown section'} · {chunk.chunk_type}
                </div>
                <p className="line-clamp-3">{chunk.content}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Document List */}
      {isLoading ? (
        <div className="py-8 text-center text-gray-400">Loading documents...</div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {documents?.items.map((doc) => (
              <DocumentCard key={doc.id} document={doc} />
            ))}
          </div>
          {!documents?.items.length && (
            <p className="py-8 text-center text-gray-400">No documents found.</p>
          )}

          {/* Pagination */}
          {documents && documents.total > 20 && (
            <div className="flex justify-center gap-2">
              <button
                disabled={store.documentsPage <= 1}
                onClick={() => store.setDocumentsPage(store.documentsPage - 1)}
                className="rounded px-3 py-1 text-sm disabled:opacity-50"
              >
                Previous
              </button>
              <span className="px-3 py-1 text-sm text-gray-500">
                Page {store.documentsPage} of {Math.ceil(documents.total / 20)}
              </span>
              <button
                disabled={store.documentsPage >= Math.ceil(documents.total / 20)}
                onClick={() => store.setDocumentsPage(store.documentsPage + 1)}
                className="rounded px-3 py-1 text-sm disabled:opacity-50"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

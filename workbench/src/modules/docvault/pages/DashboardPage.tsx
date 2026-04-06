import { useDashboardQuery, useGapsQuery } from '../hooks/queries'
import DocumentCard from '../components/DocumentCard'
import CoverageGapList from '../components/CoverageGapList'

export default function DashboardPage() {
  const { data: dashboard, isLoading } = useDashboardQuery()
  const { data: gaps } = useGapsQuery('pending')

  if (isLoading) {
    return <div className="flex items-center justify-center p-8">Loading...</div>
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <h1 className="text-2xl font-bold">DocVault Dashboard</h1>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Documents" value={dashboard?.total_documents ?? 0} />
        <StatCard label="Published" value={dashboard?.published_count ?? 0} />
        <StatCard label="Chunks" value={dashboard?.total_chunks ?? 0} />
        <StatCard label="QA Queries" value={dashboard?.total_qa_logs ?? 0} />
      </div>

      {/* Recent Documents */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">Recent Documents</h2>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {dashboard?.recent_documents.map((doc) => (
            <DocumentCard key={doc.id} document={doc} compact />
          ))}
          {!dashboard?.recent_documents.length && (
            <p className="text-sm text-gray-500">No documents yet.</p>
          )}
        </div>
      </section>

      {/* Coverage Gaps */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">
          Pending Coverage Gaps ({dashboard?.coverage_gap_count ?? 0})
        </h2>
        <CoverageGapList gaps={gaps?.items ?? []} />
      </section>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-sm text-gray-500">{label}</div>
    </div>
  )
}

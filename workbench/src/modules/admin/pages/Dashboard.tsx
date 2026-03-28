import TierDistributionChart from '../components/TierDistributionChart'

export default function Dashboard() {
  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-6 text-2xl font-bold" style={{ color: 'var(--text)' }}>
        管理儀表板
      </h1>

      <div className="grid grid-cols-1 gap-6">
        <TierDistributionChart />
      </div>
    </div>
  )
}

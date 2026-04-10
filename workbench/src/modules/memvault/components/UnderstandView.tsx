import CommunityInsights from './CommunityInsights'
import UnderstandingGauge from './UnderstandingGauge'
import { useProfile } from '../hooks/queries'

export default function UnderstandView() {
  const { data: profile, isLoading } = useProfile()

  return (
    <div className="mx-auto max-w-4xl px-3 py-4 sm:px-4 sm:py-5 lg:px-6 lg:py-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-lg font-semibold" style={{ color: 'var(--text)' }}>
          Understand
        </h1>
        <p className="text-xs mt-1" style={{ color: 'var(--subtext0)' }}>
          系統對你的理解深度 — 知識圖譜密度、偏好信心度、社群洞察
        </p>
      </div>

      {/* K/A Gauge */}
      <div className="mb-6">
        <UnderstandingGauge profile={profile ?? null} loading={isLoading} />
      </div>

      {/* Growth stats */}
      <GrowthStats />

      {/* Community Insights */}
      <div className="mt-6">
        <CommunityInsights />
      </div>
    </div>
  )
}

function GrowthStats() {
  const { data: profile } = useProfile()

  if (!profile) return null

  const totalScore = profile.knowledge_score + profile.attitude_score + profile.skill_score
  const avgScore = Math.round(totalScore / 3)

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <StatCard label="Knowledge" value={profile.knowledge_score} color="var(--blue)" />
      <StatCard label="Attitude" value={profile.attitude_score} color="var(--green)" />
      <StatCard label="Skill" value={profile.skill_score} color="var(--mauve)" />
      <StatCard label="Overall" value={avgScore} color="var(--lavender)" />
    </div>
  )
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string
  value: number
  color: string
}) {
  return (
    <div
      className="rounded-xl border p-4 text-center"
      style={{
        backgroundColor: 'var(--mantle)',
        borderColor: 'var(--surface0)',
      }}
    >
      <p
        className="text-[11px] uppercase tracking-[0.14em] mb-1"
        style={{ color: 'var(--subtext1)' }}
      >
        {label}
      </p>
      <p className="text-2xl font-bold tabular-nums" style={{ color }}>
        {value}
      </p>
    </div>
  )
}

import { ArrowLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { lifecycleApi } from '../api'
import type { LifecycleRun } from '../types'
import { PHASE_NAMES, STATUS_CONFIG, TRIGGER_LABELS } from '../types'

const PHASE_ORDER = ['audit', 'test', 'security', 'optimize', 'publish', 'catalog', 'report']

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const [run, setRun] = useState<LifecycleRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedSkills, setExpandedSkills] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (!runId) return
    lifecycleApi
      .get(runId)
      .then(setRun)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [runId])

  const toggleSkill = (name: string) => {
    setExpandedSkills((prev) => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  if (loading)
    return (
      <div className="p-6" style={{ color: 'var(--av-text-muted)' }}>
        載入中...
      </div>
    )
  if (error || !run)
    return (
      <div className="p-6" style={{ color: 'var(--av-fail)' }}>
        錯誤: {error || '找不到此執行紀錄'}
      </div>
    )

  const skipped = new Set(run.skipped_phases || [])

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/anvil/runs')}
          className="p-1.5 rounded-md hover:bg-[var(--av-accent-alpha)] transition-colors"
          style={{ color: 'var(--av-text-muted)' }}
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-lg font-semibold font-mono" style={{ color: 'var(--av-text)' }}>
            {run.run_id}
          </h1>
          <div
            className="flex items-center gap-3 text-xs"
            style={{ color: 'var(--av-text-muted)' }}
          >
            <span
              className="px-2 py-0.5 rounded-full"
              style={{
                color: STATUS_CONFIG[run.status].color,
                backgroundColor: STATUS_CONFIG[run.status].bg,
              }}
            >
              {STATUS_CONFIG[run.status].label}
            </span>
            <span>{TRIGGER_LABELS[run.trigger]}</span>
            <span>{run.started_at?.slice(0, 16).replace('T', ' ')}</span>
          </div>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          label="通過"
          value={run.test_passed}
          total={run.total_skills}
          color="var(--av-pass)"
        />
        <MetricCard
          label="部分通過"
          value={run.test_partial}
          total={run.total_skills}
          color="var(--av-warn)"
        />
        <MetricCard
          label="失敗"
          value={run.test_failed}
          total={run.total_skills}
          color="var(--av-fail)"
        />
        <MetricCard
          label="安全 Clean"
          value={run.sec_clean}
          total={run.total_skills}
          color="var(--av-pass)"
        />
      </div>

      {/* Phase Progress */}
      <div
        className="rounded-lg border p-5"
        style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
      >
        <h2 className="text-sm font-medium mb-4" style={{ color: 'var(--av-text)' }}>
          Phase 進度
        </h2>
        <div className="flex gap-2 flex-wrap">
          {PHASE_ORDER.map((phase) => {
            const phaseResult = run.phases?.[phase]
            const isSkipped = skipped.has(phase)
            const hasError = run.errors?.[phase]
            const status = isSkipped ? 'skipped' : hasError ? 'failed' : phaseResult?.status || 'ok'

            const colors: Record<string, { bg: string; text: string }> = {
              ok: { bg: 'rgba(166,227,161,0.2)', text: 'var(--av-pass)' },
              skipped: { bg: 'rgba(108,112,134,0.15)', text: 'var(--av-text-muted)' },
              failed: { bg: 'rgba(243,139,168,0.2)', text: 'var(--av-fail)' },
            }
            const c = colors[status] || colors.ok

            return (
              <div
                key={phase}
                className="px-3 py-2 rounded-md text-xs font-medium"
                style={{ backgroundColor: c.bg, color: c.text }}
                title={hasError || ''}
              >
                {PHASE_NAMES[phase] || phase}
              </div>
            )
          })}
        </div>
      </div>

      {/* Errors */}
      {Object.keys(run.errors || {}).length > 0 && (
        <div
          className="rounded-lg border p-5"
          style={{ backgroundColor: 'rgba(243,139,168,0.05)', borderColor: 'var(--av-fail)' }}
        >
          <h2 className="text-sm font-medium mb-3" style={{ color: 'var(--av-fail)' }}>
            錯誤
          </h2>
          {Object.entries(run.errors).map(([phase, msg]) => (
            <div key={phase} className="text-xs mb-1" style={{ color: 'var(--av-text)' }}>
              <strong>{PHASE_NAMES[phase] || phase}:</strong> {msg}
            </div>
          ))}
        </div>
      )}

      {/* Test Details */}
      {run.test_details && Array.isArray(run.test_details) && (
        <div
          className="rounded-lg border p-5"
          style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
        >
          <h2 className="text-sm font-medium mb-4" style={{ color: 'var(--av-text)' }}>
            測試詳情 ({run.test_details.length} skills)
          </h2>
          <div className="space-y-1">
            {run.test_details.map((skill) => (
              <div key={skill.skill_name}>
                <button
                  type="button"
                  onClick={() => toggleSkill(skill.skill_name)}
                  className="w-full flex items-center justify-between px-3 py-2 rounded-md text-xs hover:bg-[var(--av-accent-alpha)] transition-colors"
                  style={{ color: 'var(--av-text)' }}
                >
                  <span className="font-mono">{skill.skill_name}</span>
                  <span
                    style={{
                      color:
                        skill.status === 'pass'
                          ? 'var(--av-pass)'
                          : skill.status === 'partial'
                            ? 'var(--av-warn)'
                            : 'var(--av-fail)',
                    }}
                  >
                    {skill.status?.toUpperCase()}
                  </span>
                </button>
                {expandedSkills.has(skill.skill_name) && skill.checks && (
                  <div className="pl-6 pb-2 space-y-1">
                    {skill.checks.map((check, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs">
                        <span style={{ color: check.passed ? 'var(--av-pass)' : 'var(--av-fail)' }}>
                          {check.passed ? '✓' : '✗'}
                        </span>
                        <span style={{ color: 'var(--av-text-secondary)' }}>
                          {check.name}: {check.detail}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function MetricCard({
  label,
  value,
  total,
  color,
}: {
  label: string
  value: number
  total: number
  color: string
}) {
  return (
    <div
      className="rounded-lg border p-3"
      style={{ backgroundColor: 'var(--av-bg-card)', borderColor: 'var(--av-border)' }}
    >
      <div className="text-xs mb-1" style={{ color: 'var(--av-text-muted)' }}>
        {label}
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-xl font-semibold" style={{ color }}>
          {value}
        </span>
        <span className="text-xs" style={{ color: 'var(--av-text-muted)' }}>
          / {total}
        </span>
      </div>
    </div>
  )
}

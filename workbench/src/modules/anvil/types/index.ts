// ─── Lifecycle Run ───

export type RunStatus = 'running' | 'completed' | 'failed' | 'partial'
export type RunTrigger = 'manual' | 'cron' | 'api'

export interface LifecycleRun {
  id: string
  run_id: string
  status: RunStatus
  trigger: RunTrigger
  started_at: string
  completed_at: string | null
  phases: Record<string, PhaseResult>
  total_skills: number
  test_passed: number
  test_partial: number
  test_failed: number
  sec_clean: number
  sec_warned: number
  sec_blocked: number
  optimized: number
  changes_applied: number
  test_details: SkillTestDetail[] | null
  security_details: SkillSecurityDetail[] | null
  catalog_snapshot: Record<string, unknown> | null
  skipped_phases: string[]
  errors: Record<string, string>
}

export interface PhaseResult {
  status: 'ok' | 'skipped' | 'failed'
  duration_ms?: number
  detail?: string
}

export interface SkillTestDetail {
  skill_name: string
  status: 'pass' | 'partial' | 'fail'
  checks: TestCheck[]
}

export interface TestCheck {
  id: string
  name: string
  passed: boolean
  detail: string
}

export interface SkillSecurityDetail {
  skill_name: string
  status: 'clean' | 'warn' | 'block'
  findings: SecurityFinding[]
}

export interface SecurityFinding {
  id: string
  severity: string
  pattern: string
  line: number
  context: string
}

export interface LifecycleRunList {
  items: LifecycleRun[]
  total: number
  limit: number
  offset: number
}

export interface TrendPoint {
  date: string
  total_skills: number
  pass_rate: number
  sec_clean_rate: number
}

export interface LifecycleTrends {
  points: TrendPoint[]
  total_runs: number
  avg_pass_rate: number
}

// ─── Display Config ───

export const STATUS_CONFIG: Record<RunStatus, { label: string; color: string; bg: string }> = {
  running: { label: '執行中', color: '#89b4fa', bg: 'rgba(137,180,250,0.15)' },
  completed: { label: '完成', color: '#a6e3a1', bg: 'rgba(166,227,161,0.15)' },
  failed: { label: '失敗', color: '#f38ba8', bg: 'rgba(243,139,168,0.15)' },
  partial: { label: '部分完成', color: '#f9e2af', bg: 'rgba(249,226,175,0.15)' },
}

export const TRIGGER_LABELS: Record<RunTrigger, string> = {
  manual: '手動',
  cron: '排程',
  api: 'API',
}

export const PHASE_NAMES: Record<string, string> = {
  audit: '審計',
  test: '測試',
  security: '安全掃描',
  optimize: '優化',
  publish: '發佈',
  catalog: '目錄',
  report: '報告',
}

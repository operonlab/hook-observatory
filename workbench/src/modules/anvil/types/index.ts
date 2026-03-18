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

// ─── Stats ───

export interface TopSkill {
  skill_name: string
  count: number
  success_rate: number
}

export interface TrendDay {
  day: string
  count: number
}

export interface GlobalStats {
  total_invocations: number
  total_skills: number
  avg_success_rate: number
  top_skills: TopSkill[]
  trend_7d: TrendDay[]
}

export interface DemandItem {
  skill_name: string
  user_invocations: number
  auto_invocations: number
  total_usage: number
  auto_rate: number
}

export interface DemandStats {
  items: DemandItem[]
  total_user: number
  total_auto: number
  total_usage: number
  overall_auto_rate: number
}

export interface MonthBreakdown {
  month: string
  total_saved_minutes: number
  tasks_count: number
}

export interface TimeSavedStats {
  total_saved_minutes: number
  avg_saved_per_task: number
  tasks_with_estimates: number
  monthly_breakdown: MonthBreakdown[]
}

// ─── Catalog ───

export const DOMAIN_COLORS: Record<string, string> = {
  general: '#6b7fff',
  ideation: '#ff7eb3',
  'visual-design': '#ffb86b',
  'dev-tooling': '#50fa7b',
  analysis: '#8be9fd',
  'content-creation': '#ff79c6',
  'document-output': '#bd93f9',
  orchestration: '#f1fa8c',
  'knowledge-mgmt': '#ff5555',
  'skill-meta': '#69ff94',
  media: '#f8f8f2',
  'workshop-ops': '#cba6f7',
  debugging: '#74c7ec',
  communication: '#eba0ac',
  reference: '#6272a4',
}

export interface CatalogSkill {
  name: string
  version: string | null
  domain: string
  description: string | null
  tags: string[]
  strengths: string[]
  pain_point: string | null
  triggers: string[]
  tools: string[]
  body_lines: number
  resources: { scripts: number; references: number; assets: number }
  io_schema: Record<string, unknown> | null
  health_score: number | null
  status: string
}

export interface CatalogSkillDetail extends CatalogSkill {
  guide: string | null
  health_details: Record<string, unknown> | null
  connected_edges: GraphEdge[]
  invocation_count: number
}

export interface GraphNode {
  id: string
  domain: string
  description: string | null
  health_score: number | null
  val: number
  color?: string
  x?: number
  y?: number
  z?: number
  fx?: number | null
  fy?: number | null
  fz?: number | null
}

export interface GraphEdge {
  source: string
  target: string
  type: string
  strength: number
  description: string | null
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  compositions: { name: string; skills: string[]; completeness: number }[]
  stats: {
    total_skills: number
    total_edges: number
    domain_distribution: Record<string, number>
  }
}

export interface CatalogListResponse {
  items: CatalogSkill[]
  total: number
  limit: number
  offset: number
  domain_counts: Record<string, number>
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

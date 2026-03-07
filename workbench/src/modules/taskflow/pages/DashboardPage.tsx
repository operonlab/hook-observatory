import { AlertCircle, CheckCircle2, Clock, Plus, TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { dashboardApi } from '../api'
import type { Task, TaskProgressStats } from '../types'
import { PRIORITY_CONFIG, SOURCE_CONFIG, STATUS_CONFIG } from '../types'

function formatDate(dateStr: string | null): string {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('zh-TW', { month: 'numeric', day: 'numeric' })
}

function TaskCard({ task, onClick }: { task: Task; onClick: () => void }) {
  const status = STATUS_CONFIG[task.status]
  const priority = PRIORITY_CONFIG[task.priority]

  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left rounded-lg border p-3 transition-colors hover:border-[color:var(--tf-accent-dim)]"
      style={{
        borderColor: 'var(--tf-border)',
        backgroundColor: 'var(--tf-bg-elevated)',
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-[13px] font-medium leading-snug" style={{ color: 'var(--tf-text)' }}>
          {task.title}
        </span>
        <span
          className="shrink-0 text-[11px] px-1.5 py-0.5 rounded font-medium"
          style={{
            color: status.color,
            backgroundColor: status.bgColor,
            border: `1px solid ${status.borderColor}`,
          }}
        >
          {status.label}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1.5 flex-wrap">
        <span
          className="text-[11px] px-1.5 py-0.5 rounded"
          style={{ color: priority.color, backgroundColor: priority.bgColor }}
        >
          {priority.label}
        </span>
        <span className="text-[11px]" style={{ color: 'var(--tf-text-muted)' }}>
          {SOURCE_CONFIG[task.source].icon} {SOURCE_CONFIG[task.source].label}
        </span>
        {task.due_date && (
          <span className="text-[11px]" style={{ color: 'var(--tf-text-muted)' }}>
            <Clock size={10} className="inline mr-0.5" />
            {formatDate(task.due_date)}
          </span>
        )}
      </div>
    </button>
  )
}

function StatCard({
  label,
  value,
  icon,
  color,
}: {
  label: string
  value: number
  icon: React.ReactNode
  color: string
}) {
  return (
    <div
      className="rounded-lg border p-3"
      style={{ borderColor: 'var(--tf-border)', backgroundColor: 'var(--tf-bg-elevated)' }}
    >
      <div className="flex items-center gap-2 mb-1">
        <span style={{ color }}>{icon}</span>
        <span className="text-[11px]" style={{ color: 'var(--tf-text-muted)' }}>
          {label}
        </span>
      </div>
      <div className="text-2xl font-semibold tabular-nums" style={{ color }}>
        {value}
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [todayTasks, setTodayTasks] = useState<Task[]>([])
  const [upcomingTasks, setUpcomingTasks] = useState<Task[]>([])
  const [stats, setStats] = useState<TaskProgressStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      dashboardApi.today().catch(() => [] as Task[]),
      dashboardApi.upcoming(7).catch(() => [] as Task[]),
      dashboardApi.progress().catch(() => null),
    ])
      .then(([today, upcoming, progress]) => {
        setTodayTasks(today)
        setUpcomingTasks(upcoming)
        setStats(progress)
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--tf-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  const inProgress = stats?.by_status.in_progress ?? 0
  const done = stats?.by_status.done ?? 0
  const blocked = stats?.by_status.blocked ?? 0
  const overdue = stats?.overdue ?? 0

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--tf-text)' }}>
          任務概覽
        </h1>
        <button
          type="button"
          onClick={() => navigate('/taskflow/tasks')}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors"
          style={{
            backgroundColor: 'var(--tf-accent-alpha)',
            color: 'var(--tf-accent)',
            border: '1px solid var(--tf-accent-dim)',
          }}
        >
          <Plus size={14} />
          新增任務
        </button>
      </div>

      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            label="進行中"
            value={inProgress}
            icon={<TrendingUp size={14} />}
            color="var(--tf-in-progress)"
          />
          <StatCard
            label="已完成"
            value={done}
            icon={<CheckCircle2 size={14} />}
            color="var(--tf-done)"
          />
          <StatCard
            label="阻塞中"
            value={blocked}
            icon={<AlertCircle size={14} />}
            color="var(--tf-blocked)"
          />
          <StatCard
            label="逾期"
            value={overdue}
            icon={<Clock size={14} />}
            color={overdue > 0 ? 'var(--tf-urgent)' : 'var(--tf-text-muted)'}
          />
        </div>
      )}

      {/* Today's tasks */}
      <section>
        <h2
          className="text-[13px] font-medium mb-2.5"
          style={{ color: 'var(--tf-text-secondary)' }}
        >
          今日任務 ({todayTasks.length})
        </h2>
        {todayTasks.length === 0 ? (
          <div
            className="rounded-lg border p-6 text-center text-[13px]"
            style={{ borderColor: 'var(--tf-border)', color: 'var(--tf-text-muted)' }}
          >
            今天沒有排定的任務 🎉
          </div>
        ) : (
          <div className="space-y-2">
            {todayTasks.map((task) => (
              <TaskCard key={task.id} task={task} onClick={() => navigate('/taskflow/tasks')} />
            ))}
          </div>
        )}
      </section>

      {/* Upcoming tasks */}
      <section>
        <h2
          className="text-[13px] font-medium mb-2.5"
          style={{ color: 'var(--tf-text-secondary)' }}
        >
          即將到期（7天內）({upcomingTasks.length})
        </h2>
        {upcomingTasks.length === 0 ? (
          <div
            className="rounded-lg border p-6 text-center text-[13px]"
            style={{ borderColor: 'var(--tf-border)', color: 'var(--tf-text-muted)' }}
          >
            近期無到期任務
          </div>
        ) : (
          <div className="space-y-2">
            {upcomingTasks.slice(0, 5).map((task) => (
              <TaskCard key={task.id} task={task} onClick={() => navigate('/taskflow/tasks')} />
            ))}
            {upcomingTasks.length > 5 && (
              <button
                type="button"
                onClick={() => navigate('/taskflow/tasks')}
                className="w-full text-center text-[12px] py-2"
                style={{ color: 'var(--tf-accent)' }}
              >
                查看全部 {upcomingTasks.length} 筆 →
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

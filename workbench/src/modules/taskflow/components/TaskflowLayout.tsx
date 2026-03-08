import { BarChart3, Calendar, CheckSquare, LayoutDashboard } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import '../styles/taskflow.css'

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/taskflow' },
  { id: 'tasks', label: '任務', icon: CheckSquare, path: '/taskflow/tasks' },
  { id: 'stats', label: '統計', icon: BarChart3, path: '/taskflow/stats' },
] as const

export default function TaskflowLayout() {
  const location = useLocation()

  const isActive = (item: (typeof NAV_ITEMS)[number]) => {
    if (item.id === 'dashboard') return location.pathname === '/taskflow'
    return location.pathname.startsWith(item.path)
  }

  return (
    <div className="taskflow flex flex-col md:flex-row h-full">
      {/* ─── Desktop Sidebar ─── */}
      <aside
        className="hidden md:flex flex-col shrink-0 border-r"
        style={{
          width: 220,
          backgroundColor: 'var(--tf-bg)',
          borderColor: 'var(--tf-border)',
        }}
      >
        <div
          className="flex items-center gap-2.5 px-5 py-4 border-b"
          style={{ borderColor: 'var(--tf-border)' }}
        >
          <span className="text-lg">✅</span>
          <span className="text-sm font-medium tracking-wide" style={{ color: 'var(--tf-accent)' }}>
            任務排程
          </span>
        </div>

        <nav className="flex-1 py-2 px-2 space-y-0.5">
          {NAV_ITEMS.map((item) => {
            const active = isActive(item)
            const Icon = item.icon
            return (
              <NavLink
                key={item.id}
                to={item.path}
                className="flex items-center gap-3 px-3 py-2.5 text-[13px] rounded-md transition-colors"
                style={{
                  backgroundColor: active ? 'var(--tf-accent-alpha)' : 'transparent',
                  color: active ? 'var(--tf-accent)' : 'var(--tf-text-tertiary)',
                  borderLeft: active ? '2px solid var(--tf-accent)' : '2px solid transparent',
                }}
              >
                <Icon size={15} />
                {item.label}
              </NavLink>
            )
          })}

          {/* Cross-module link */}
          <div className="pt-2 mt-2 border-t" style={{ borderColor: 'var(--tf-border)' }}>
            <NavLink
              to="/dailyos"
              className="flex items-center gap-3 px-3 py-2.5 text-[13px] rounded-md transition-colors"
              style={{
                color: 'var(--tf-text-muted)',
                borderLeft: '2px solid transparent',
              }}
            >
              <Calendar size={15} />
              每日規劃
            </NavLink>
          </div>
        </nav>
      </aside>

      {/* ─── Main Content ─── */}
      <main className="flex-1 min-w-0 overflow-y-auto pb-16 md:pb-0">
        <Outlet />
      </main>

      {/* ─── Mobile Bottom Tab Bar ─── */}
      <nav
        className="flex md:hidden items-stretch border-t shrink-0 fixed bottom-0 left-0 right-0 z-30"
        style={{
          backgroundColor: 'var(--tf-bg)',
          borderColor: 'var(--tf-border)',
          paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        }}
      >
        {NAV_ITEMS.map((item) => {
          const active = isActive(item)
          const Icon = item.icon
          return (
            <NavLink
              key={item.id}
              to={item.path}
              className="flex flex-1 flex-col items-center justify-center gap-1 py-2 min-h-[56px] text-[10px] transition-colors"
              style={{
                color: active ? 'var(--tf-accent)' : 'var(--tf-text-muted)',
                backgroundColor: active ? 'var(--tf-accent-alpha)' : 'transparent',
              }}
            >
              <Icon size={20} />
              <span className="font-medium">{item.label}</span>
            </NavLink>
          )
        })}
      </nav>
    </div>
  )
}

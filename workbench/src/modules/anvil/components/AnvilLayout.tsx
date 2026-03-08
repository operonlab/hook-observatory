import { Activity, BarChart3, History, Shield } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import '../styles/anvil.css'

const NAV_ITEMS = [
  { id: 'dashboard', label: '總覽', icon: BarChart3, path: '/anvil' },
  { id: 'runs', label: '執行紀錄', icon: History, path: '/anvil/runs' },
  { id: 'health', label: '健康狀態', icon: Activity, path: '/anvil/health' },
  { id: 'security', label: '安全報告', icon: Shield, path: '/anvil/security' },
] as const

export default function AnvilLayout() {
  const location = useLocation()

  const isActive = (item: (typeof NAV_ITEMS)[number]) => {
    if (item.id === 'dashboard') return location.pathname === '/anvil'
    return location.pathname.startsWith(item.path)
  }

  return (
    <div className="anvil flex flex-col md:flex-row h-full">
      {/* Desktop Sidebar */}
      <aside
        className="hidden md:flex flex-col shrink-0 border-r"
        style={{
          width: 220,
          backgroundColor: 'var(--av-bg)',
          borderColor: 'var(--av-border)',
        }}
      >
        <div
          className="flex items-center gap-2.5 px-5 py-4 border-b"
          style={{ borderColor: 'var(--av-border)' }}
        >
          <span className="text-lg">🔨</span>
          <span className="text-sm font-medium tracking-wide" style={{ color: 'var(--av-accent)' }}>
            技能鍛造
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
                  backgroundColor: active ? 'var(--av-accent-alpha)' : 'transparent',
                  color: active ? 'var(--av-accent)' : 'var(--av-text-tertiary)',
                  borderLeft: active ? '2px solid var(--av-accent)' : '2px solid transparent',
                }}
              >
                <Icon size={15} />
                {item.label}
              </NavLink>
            )
          })}
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex-1 min-w-0 overflow-y-auto pb-16 md:pb-0">
        <Outlet />
      </main>

      {/* Mobile Bottom Tab Bar */}
      <nav
        className="flex md:hidden items-stretch border-t shrink-0 fixed bottom-0 left-0 right-0 z-30"
        style={{
          backgroundColor: 'var(--av-bg)',
          borderColor: 'var(--av-border)',
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
                color: active ? 'var(--av-accent)' : 'var(--av-text-muted)',
                backgroundColor: active ? 'var(--av-accent-alpha)' : 'transparent',
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

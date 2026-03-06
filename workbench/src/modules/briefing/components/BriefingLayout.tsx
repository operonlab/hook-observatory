import { Calendar, History, Newspaper, Settings } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import '../styles/briefing.css'

const NAV_ITEMS = [
  { id: 'today', label: '今日簡報', icon: Newspaper, path: '/briefing' },
  { id: 'history', label: '歷史', icon: History, path: '/briefing/history' },
  { id: 'calendar', label: '日曆', icon: Calendar, path: '/briefing/calendar' },
  { id: 'config', label: '設定', icon: Settings, path: '/briefing/config' },
] as const

export default function BriefingLayout() {
  const location = useLocation()

  const isActive = (item: (typeof NAV_ITEMS)[number]) => {
    if (item.id === 'today') {
      return (
        location.pathname === '/briefing' ||
        (location.pathname.startsWith('/briefing/') &&
          !['history', 'calendar', 'config'].some((p) =>
            location.pathname.startsWith(`/briefing/${p}`),
          ))
      )
    }
    return location.pathname.startsWith(item.path)
  }

  return (
    <div className="briefing flex flex-col md:flex-row h-full">
      {/* Desktop Sidebar */}
      <aside
        className="hidden md:flex flex-col shrink-0 border-r"
        style={{
          width: 220,
          backgroundColor: 'var(--bf-bg)',
          borderColor: 'var(--bf-border)',
        }}
      >
        <div
          className="flex items-center gap-2.5 px-5 py-4 border-b"
          style={{ borderColor: 'var(--bf-border)' }}
        >
          <span
            className="text-sm tracking-wide"
            style={{
              fontFamily: 'var(--bf-font-display)',
              color: 'var(--bf-accent)',
              fontWeight: 500,
              letterSpacing: '0.04em',
            }}
          >
            Briefing
          </span>
          <span
            className="text-[10px] uppercase tracking-widest"
            style={{ color: 'var(--bf-text-dim)', letterSpacing: '0.1em' }}
          >
            每日情報
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
                className="flex items-center gap-3 px-3 py-2.5 text-[13px] transition-colors"
                style={{
                  backgroundColor: active ? 'var(--bf-accent-alpha)' : 'transparent',
                  color: active ? 'var(--bf-accent)' : 'var(--bf-text-tertiary)',
                  borderLeft: active ? '2px solid var(--bf-accent)' : '2px solid transparent',
                }}
                onMouseEnter={(e) => {
                  if (!active) {
                    e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)'
                    e.currentTarget.style.color = 'var(--bf-text-secondary)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!active) {
                    e.currentTarget.style.backgroundColor = 'transparent'
                    e.currentTarget.style.color = 'var(--bf-text-tertiary)'
                  }
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
          backgroundColor: 'var(--bf-bg)',
          borderColor: 'var(--bf-border)',
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
                color: active ? 'var(--bf-accent)' : 'var(--bf-text-muted)',
                backgroundColor: active ? 'var(--bf-accent-alpha)' : 'transparent',
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

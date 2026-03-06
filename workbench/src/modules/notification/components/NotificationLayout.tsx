import { Bell, Clock, Send } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import '../styles/notification.css'

const NAV_ITEMS = [
  { id: 'history', label: '通知記錄', icon: Clock, path: '/notification' },
  { id: 'send', label: '發送通知', icon: Send, path: '/notification/send' },
] as const

export default function NotificationLayout() {
  const location = useLocation()

  const isActive = (item: (typeof NAV_ITEMS)[number]) => {
    if (item.id === 'history') return location.pathname === '/notification'
    return location.pathname.startsWith(item.path)
  }

  return (
    <div className="notification flex flex-col md:flex-row h-full">
      {/* Desktop Sidebar */}
      <aside
        className="hidden md:flex flex-col shrink-0 border-r"
        style={{
          width: 220,
          backgroundColor: 'var(--crust)',
          borderColor: 'var(--surface0)',
        }}
      >
        <div
          className="flex items-center gap-2.5 px-5 py-4 border-b"
          style={{ borderColor: 'var(--surface0)' }}
        >
          <Bell size={15} style={{ color: 'var(--accent)' }} />
          <span
            className="text-sm"
            style={{
              color: 'var(--accent)',
              fontWeight: 500,
              letterSpacing: '0.04em',
            }}
          >
            Notification
          </span>
          <span
            className="text-[10px] uppercase tracking-widest"
            style={{ color: 'var(--subtext1)', letterSpacing: '0.1em' }}
          >
            通知中心
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
                className="flex items-center gap-3 px-3 py-2.5 text-[13px] transition-colors cursor-pointer"
                style={{
                  backgroundColor: active
                    ? 'color-mix(in srgb, var(--accent) 12%, transparent)'
                    : 'transparent',
                  color: active ? 'var(--accent)' : 'var(--subtext1)',
                  borderLeft: active ? '2px solid var(--accent)' : '2px solid transparent',
                }}
                onMouseEnter={(e) => {
                  if (!active) {
                    e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)'
                    e.currentTarget.style.color = 'var(--subtext0)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!active) {
                    e.currentTarget.style.backgroundColor = 'transparent'
                    e.currentTarget.style.color = 'var(--subtext1)'
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
          backgroundColor: 'var(--crust)',
          borderColor: 'var(--surface0)',
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
              className="flex flex-1 flex-col items-center justify-center gap-1 py-2.5 min-h-[56px] text-[10px] transition-colors cursor-pointer"
              style={{
                color: active ? 'var(--accent)' : 'var(--subtext1)',
                backgroundColor: active
                  ? 'color-mix(in srgb, var(--accent) 8%, transparent)'
                  : 'transparent',
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

import { BookOpen, LayoutDashboard, List, Search } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import '../styles/paper.css'

const NAV_ITEMS = [
  { id: 'dashboard', label: '總覽', icon: LayoutDashboard, path: '/paper' },
  { id: 'articles', label: '論文庫', icon: List, path: '/paper/articles' },
  { id: 'search', label: '語意搜尋', icon: Search, path: '/paper/search' },
] as const

export default function PaperLayout() {
  const location = useLocation()

  const isActive = (item: (typeof NAV_ITEMS)[number]) => {
    if (item.id === 'dashboard') return location.pathname === '/paper'
    return location.pathname.startsWith(item.path)
  }

  return (
    <div className="paper flex flex-col md:flex-row h-full">
      {/* ─── Desktop Sidebar ─── */}
      <aside
        className="hidden md:flex flex-col shrink-0"
        style={{
          width: 232,
          backgroundColor: 'var(--pp-bg)',
          borderRight: '1px solid var(--pp-border)',
        }}
      >
        {/* Logo / Brand */}
        <div
          style={{
            padding: '28px 20px 24px',
            borderBottom: '1px solid var(--pp-border)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <div
              style={{
                width: 28,
                height: 28,
                border: '1px solid var(--pp-accent)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <BookOpen size={13} style={{ color: 'var(--pp-accent)' }} />
            </div>
            <span
              style={{
                fontFamily: 'var(--pp-font-display)',
                fontSize: '1.35rem',
                fontWeight: 600,
                color: 'var(--pp-text)',
                letterSpacing: '0.01em',
                lineHeight: 1,
              }}
            >
              Paper
            </span>
          </div>
          <p
            style={{
              fontSize: '10px',
              color: 'var(--pp-text-dim)',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              paddingLeft: 38,
            }}
          >
            學術研究管線
          </p>
        </div>

        {/* Navigation */}
        <nav
          style={{
            flex: 1,
            padding: '12px 10px',
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
          }}
        >
          {NAV_ITEMS.map((item) => {
            const active = isActive(item)
            const Icon = item.icon
            return (
              <NavLink
                key={item.id}
                to={item.path}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '9px 12px',
                  fontSize: '12.5px',
                  fontFamily: 'var(--pp-font-ui)',
                  letterSpacing: '0.01em',
                  color: active ? 'var(--pp-accent)' : 'var(--pp-text-tertiary)',
                  backgroundColor: active ? 'var(--pp-accent-alpha)' : 'transparent',
                  borderLeft: `2px solid ${active ? 'var(--pp-accent)' : 'transparent'}`,
                  textDecoration: 'none',
                  transition: 'color 0.15s, background-color 0.15s',
                }}
                onMouseEnter={(e) => {
                  if (!active) {
                    e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.04)'
                    e.currentTarget.style.color = 'var(--pp-text-secondary)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!active) {
                    e.currentTarget.style.backgroundColor = 'transparent'
                    e.currentTarget.style.color = 'var(--pp-text-tertiary)'
                  }
                }}
              >
                <Icon size={14} style={{ flexShrink: 0 }} />
                <span>{item.label}</span>
              </NavLink>
            )
          })}
        </nav>

        {/* Footer decoration */}
        <div
          style={{
            padding: '16px 20px',
            borderTop: '1px solid var(--pp-border)',
          }}
        >
          <p
            style={{
              fontFamily: 'var(--pp-font-display)',
              fontSize: '11px',
              color: 'var(--pp-text-dim)',
              fontStyle: 'italic',
              letterSpacing: '0.02em',
            }}
          >
            "研究是創造的基礎"
          </p>
        </div>
      </aside>

      {/* ─── Main Content ─── */}
      <main className="flex-1 min-w-0 overflow-y-auto pb-16 md:pb-0">
        <Outlet />
      </main>

      {/* ─── Mobile Bottom Tab Bar ─── */}
      <nav
        className="flex md:hidden items-stretch shrink-0 fixed bottom-0 left-0 right-0 z-30"
        style={{
          backgroundColor: 'var(--pp-bg)',
          borderTop: '1px solid var(--pp-border)',
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
              className="flex flex-1 flex-col items-center justify-center gap-1 py-2 min-h-[56px] transition-colors"
              style={{
                color: active ? 'var(--pp-accent)' : 'var(--pp-text-muted)',
                backgroundColor: active ? 'var(--pp-accent-alpha)' : 'transparent',
                borderTop: `2px solid ${active ? 'var(--pp-accent)' : 'transparent'}`,
                fontSize: '10px',
                fontFamily: 'var(--pp-font-ui)',
                textDecoration: 'none',
              }}
            >
              <Icon size={19} />
              <span style={{ fontWeight: active ? 500 : 400 }}>{item.label}</span>
            </NavLink>
          )
        })}
      </nav>
    </div>
  )
}

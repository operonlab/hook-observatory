import { LayoutDashboard, LayoutGrid, LogOut } from 'lucide-react'
import { useMemo, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import CaptureBadge from '@/modules/capture/CaptureBadge'
import { VoiceFab } from '@/modules/voice'
import { LAUNCHER_ITEMS } from '@/shared/constants/apps'
import AppLauncher from '@/shell/AppLauncher'

export default function AppHeader() {
  const { user, logout } = useAuth()
  const location = useLocation()
  const [showLauncher, setShowLauncher] = useState(false)

  const isAppsPage = location.pathname === '/apps'

  // Derive current module from route
  const currentApp = useMemo(() => {
    // Sort by path length desc to match most specific path first
    return LAUNCHER_ITEMS.find(
      (app) => app.kind === 'app' && app.path && location.pathname.startsWith(app.path),
    )
  }, [location.pathname])

  const accentColor = currentApp?.color

  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 flex h-12 items-center justify-between px-5"
      style={{
        background: 'rgba(0, 0, 0, 0.6)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        borderBottom: accentColor
          ? `1px solid ${accentColor}25`
          : '1px solid rgba(255, 255, 255, 0.06)',
      }}
    >
      {/* Left — Brand + Current Module */}
      <div className="flex items-center gap-0 min-w-0">
        <NavLink
          to="/apps"
          className="shrink-0 transition-opacity hover:opacity-70"
          style={{ textDecoration: 'none' }}
        >
          <span
            style={{
              fontFamily: "'Cormorant Garamond', Georgia, serif",
              fontSize: '1.125rem',
              fontWeight: 600,
              letterSpacing: '0.02em',
              color: 'rgba(255, 255, 255, 0.85)',
            }}
          >
            Workshop
          </span>
        </NavLink>

        {currentApp && (
          <>
            <span
              className="mx-3 select-none"
              style={{
                color: accentColor ? `${accentColor}40` : 'rgba(255, 255, 255, 0.2)',
                fontSize: '0.875rem',
              }}
            >
              /
            </span>
            <span
              className="truncate text-sm"
              style={{
                color: accentColor ?? 'rgba(255, 255, 255, 0.55)',
                fontWeight: 500,
                letterSpacing: '0.01em',
              }}
            >
              {currentApp.name}
            </span>
          </>
        )}
      </div>

      {/* Right — Controls */}
      <div className="relative flex items-center gap-1.5">
        {/* Dashboard toggle (only on /apps) */}
        {isAppsPage && (
          <HeaderButton
            icon={<LayoutDashboard size={16} />}
            active={false}
            accentColor={accentColor}
            aria-label="Dashboard"
            onClick={() => window.dispatchEvent(new CustomEvent('toggle-dashboard'))}
          />
        )}

        {/* App Switcher */}
        <HeaderButton
          icon={<LayoutGrid size={16} />}
          active={showLauncher}
          accentColor={accentColor}
          aria-label="App Switcher"
          onClick={() => setShowLauncher((v) => !v)}
        />

        {showLauncher && <AppLauncher onClose={() => setShowLauncher(false)} />}

        {/* Voice Gateway */}
        <VoiceFab />

        {/* Capture Badge */}
        <CaptureBadge />

        {/* Separator */}
        <span
          className="mx-0.5 h-4"
          style={{
            borderLeft: accentColor
              ? `1px solid ${accentColor}20`
              : '1px solid rgba(255, 255, 255, 0.08)',
          }}
        />

        {/* User Avatar */}
        {user && (
          <button
            type="button"
            className="flex h-8 items-center gap-2 px-2 transition-colors"
            style={{
              color: 'rgba(255, 255, 255, 0.5)',
              borderRadius: '6px',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
            }}
            onClick={() => logout().catch(() => {})}
            title="登出"
          >
            <div
              className="flex h-6 w-6 items-center justify-center text-[10px] font-semibold"
              style={{
                backgroundColor: accentColor ? `${accentColor}20` : 'rgba(180, 190, 254, 0.15)',
                color: accentColor ?? 'rgba(180, 190, 254, 0.85)',
                borderRadius: '50%',
              }}
            >
              {user.name?.charAt(0).toUpperCase() ?? '?'}
            </div>
            <span className="hidden text-xs sm:block">{user.name}</span>
            <LogOut size={13} style={{ opacity: 0.5 }} />
          </button>
        )}
      </div>
    </header>
  )
}

/** Reusable icon button for header */
function HeaderButton({
  icon,
  active,
  accentColor,
  onClick,
  ...rest
}: {
  icon: React.ReactNode
  active: boolean
  accentColor?: string
  onClick: () => void
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-8 w-8 items-center justify-center transition-colors"
      style={{
        color: active ? 'rgba(255, 255, 255, 0.9)' : 'rgba(255, 255, 255, 0.4)',
        borderRadius: '6px',
        backgroundColor: active ? 'rgba(255, 255, 255, 0.08)' : 'transparent',
      }}
      onMouseEnter={(e) => {
        if (!active) {
          e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)'
          e.currentTarget.style.color = 'rgba(255, 255, 255, 0.7)'
        }
      }}
      onMouseLeave={(e) => {
        if (!active) {
          e.currentTarget.style.backgroundColor = 'transparent'
          e.currentTarget.style.color = 'rgba(255, 255, 255, 0.4)'
        }
      }}
      {...rest}
    >
      {icon}
    </button>
  )
}

import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { APP_LIST } from '@/shared/constants/apps'

interface AppLauncherProps {
  onClose: () => void
}

export default function AppLauncher({ onClose }: AppLauncherProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [onClose])

  const availableApps = APP_LIST.filter(
    (app) => app.status === 'available' || app.status === 'external',
  )

  return (
    <div
      ref={ref}
      className="absolute right-0 top-12 z-50 flex flex-col overflow-hidden shadow-2xl"
      style={{
        background: 'rgba(10, 10, 14, 0.97)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        border: '1px solid rgba(255, 255, 255, 0.06)',
        minWidth: 260,
        borderRadius: '2px',
      }}
    >
      {/* Header */}
      <div
        className="px-4 pt-3 pb-2"
        style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.04)' }}
      >
        <span
          className="text-[10px] uppercase tracking-wider"
          style={{ color: 'rgba(255, 255, 255, 0.2)', letterSpacing: '0.15em' }}
        >
          Applications
        </span>
      </div>

      {/* App list */}
      <div className="py-1">
        {availableApps.map((app) => {
          const isActive = location.pathname.startsWith(app.path)
          return (
            <button
              key={app.id}
              onClick={() => {
                if (app.externalUrl) {
                  window.location.href = app.externalUrl
                } else {
                  navigate(app.path)
                }
                onClose()
              }}
              className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors"
              style={{
                backgroundColor: isActive ? `${app.color}0c` : 'transparent',
                borderLeft: isActive ? `2px solid ${app.color}` : '2px solid transparent',
                cursor: 'pointer',
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = `${app.color}08`
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = 'transparent'
                }
              }}
            >
              <span className="text-base">{app.icon}</span>
              <span
                className="text-xs"
                style={{
                  color: isActive ? app.color : 'rgba(255, 255, 255, 0.55)',
                  fontWeight: isActive ? 500 : 400,
                }}
              >
                {app.name}
              </span>
              {app.externalUrl ? (
                <span
                  className="ml-auto text-[10px]"
                  style={{ color: 'rgba(255, 255, 255, 0.25)' }}
                >
                  ↗
                </span>
              ) : isActive ? (
                <span
                  className="ml-auto h-1.5 w-1.5"
                  style={{
                    backgroundColor: app.color,
                    borderRadius: '50%',
                  }}
                />
              ) : null}
            </button>
          )
        })}
      </div>

      {/* Footer */}
      <div className="px-4 py-2.5" style={{ borderTop: '1px solid rgba(255, 255, 255, 0.04)' }}>
        <button
          onClick={() => {
            navigate('/apps')
            onClose()
          }}
          className="w-full text-left text-[11px] transition-colors"
          style={{ color: 'rgba(255, 255, 255, 0.25)' }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = 'rgba(255, 255, 255, 0.5)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = 'rgba(255, 255, 255, 0.25)'
          }}
        >
          全部應用 →
        </button>
      </div>
    </div>
  )
}

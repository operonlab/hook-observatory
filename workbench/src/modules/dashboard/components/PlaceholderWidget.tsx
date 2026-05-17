import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LAUNCHER_ITEMS } from '@/shared/constants/apps'
import type { WidgetProps } from '../types/widget'

/** Clock widget — shows current time */
export function ClockWidget(_props: WidgetProps) {
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="flex h-full flex-col items-center justify-center gap-1">
      <span
        className="text-2xl font-light tabular-nums"
        style={{ color: 'rgba(255, 255, 255, 0.85)' }}
      >
        {now.toLocaleTimeString('zh-TW', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })}
      </span>
      <span className="text-xs" style={{ color: 'rgba(255, 255, 255, 0.35)' }}>
        {now.toLocaleDateString('zh-TW', {
          month: 'long',
          day: 'numeric',
          weekday: 'short',
        })}
      </span>
    </div>
  )
}

/** Notes widget — simple textarea */
export function NotesWidget({ instanceId }: WidgetProps) {
  const storageKey = `dashboard-notes-${instanceId}`
  const [text, setText] = useState(() => localStorage.getItem(storageKey) ?? '')

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, text)
    } catch {
      // QuotaExceededError in private browsing — ignore
    }
  }, [storageKey, text])

  return (
    <div className="flex h-full flex-col p-2">
      <span
        className="mb-1.5 text-[10px] uppercase tracking-wider"
        style={{ color: 'rgba(255, 255, 255, 0.25)' }}
      >
        Notes
      </span>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="在這裡記下想法..."
        className="flex-1 resize-none bg-transparent text-xs leading-relaxed outline-none"
        style={{
          color: 'rgba(255, 255, 255, 0.7)',
          caretColor: 'var(--accent)',
        }}
      />
    </div>
  )
}

/** Quick links widget — shortcut to internal apps */
export function QuickLinksWidget(_props: WidgetProps) {
  const navigate = useNavigate()
  const apps = LAUNCHER_ITEMS.filter(
    (a) => a.kind === 'app' && a.status === 'available' && a.path,
  ).slice(0, 6)

  return (
    <div className="flex h-full flex-col p-2">
      <span
        className="mb-2 text-[10px] uppercase tracking-wider"
        style={{ color: 'rgba(255, 255, 255, 0.25)' }}
      >
        Quick Links
      </span>
      <div className="grid grid-cols-3 gap-1.5 flex-1 content-start">
        {apps.map((app) => (
          <button
            type="button"
            key={app.id}
            onClick={() => app.path && navigate(app.path)}
            className="flex flex-col items-center gap-1 rounded p-1.5 transition-colors"
            style={{ backgroundColor: 'transparent' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = `${app.color}15`
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
            }}
          >
            <span className="text-base">{app.icon}</span>
            <span
              className="text-[10px] truncate w-full text-center"
              style={{ color: 'rgba(255, 255, 255, 0.5)' }}
            >
              {app.name}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

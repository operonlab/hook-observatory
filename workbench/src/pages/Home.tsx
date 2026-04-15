import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppOrder } from '@/hooks/useAppOrder'
import { useAuth } from '@/hooks/useAuth'
import ToolboxPopover from '@/shell/ToolboxPopover'
import type { AppInfo } from '@/types'

const LONG_PRESS_MS = 500

function AppCard({
  app,
  isHovered,
  onHover,
  onClick,
  onHide,
  isDragOver,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDrop,
}: {
  app: AppInfo
  isHovered: boolean
  onHover: (id: string | null) => void
  onClick: (rect: DOMRect) => void
  onHide: () => void
  isDragOver: boolean
  onDragStart: () => void
  onDragOver: (e: React.DragEvent) => void
  onDragEnd: () => void
  onDrop: (e: React.DragEvent) => void
}) {
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const longPressed = useRef(false)

  const clearPress = () => {
    if (pressTimer.current) {
      clearTimeout(pressTimer.current)
      pressTimer.current = null
    }
  }

  return (
    <button
      type="button"
      draggable
      onDragStart={(e) => {
        clearPress()
        e.dataTransfer.effectAllowed = 'move'
        e.currentTarget.style.opacity = '0.4'
        onDragStart()
      }}
      onDragOver={onDragOver}
      onDragEnd={(e) => {
        e.currentTarget.style.opacity = '1'
        onDragEnd()
      }}
      onDrop={onDrop}
      onPointerDown={() => {
        longPressed.current = false
        clearPress()
        pressTimer.current = setTimeout(() => {
          longPressed.current = true
          onHide()
        }, LONG_PRESS_MS)
      }}
      onPointerUp={clearPress}
      onPointerLeave={clearPress}
      onPointerCancel={clearPress}
      onContextMenu={(e) => {
        e.preventDefault()
        onHide()
      }}
      onClick={(e) => {
        if (longPressed.current) {
          e.preventDefault()
          longPressed.current = false
          return
        }
        onClick(e.currentTarget.getBoundingClientRect())
      }}
      onMouseEnter={() => onHover(app.id)}
      onMouseLeave={() => {
        clearPress()
        onHover(null)
      }}
      className="group relative flex items-start gap-4 p-6 text-left transition-all"
      style={{
        backgroundColor: isHovered ? `${app.color}14` : 'transparent',
        cursor: 'grab',
        border: '1px solid rgba(255, 255, 255, 0.04)',
        borderLeft: isDragOver
          ? `2px solid ${app.color}`
          : `2px solid ${isHovered ? app.color : `${app.color}40`}`,
        boxShadow: isDragOver ? `inset 0 0 0 1px ${app.color}40` : 'none',
        transition: 'border 0.15s, box-shadow 0.15s, background-color 0.2s',
      }}
    >
      <span
        className="flex h-11 w-11 shrink-0 items-center justify-center text-xl"
        style={{
          backgroundColor: isHovered ? `${app.color}30` : `${app.color}20`,
          border: `1px solid ${app.color}${isHovered ? '50' : '35'}`,
          borderRadius: '8px',
          transition: 'all 0.2s ease',
        }}
      >
        {app.icon}
      </span>
      <div className="min-w-0 flex-1">
        <h3
          className="text-sm font-medium transition-colors"
          style={{
            color: isHovered ? app.color : 'rgba(255, 255, 255, 0.85)',
          }}
        >
          {app.name}
        </h3>
        <p
          className="mt-1 text-xs leading-relaxed"
          style={{
            color: isHovered ? 'rgba(255, 255, 255, 0.45)' : 'rgba(255, 255, 255, 0.3)',
          }}
        >
          {app.description}
        </p>
      </div>
      <span
        className="mt-1 text-xs opacity-0 transition-opacity group-hover:opacity-100"
        style={{ color: app.color }}
      >
        {app.externalUrl ? '↗' : '→'}
      </span>
    </button>
  )
}

function DraggableGrid({
  apps,
  section,
  onReorder,
  renderCard,
}: {
  apps: AppInfo[]
  section: 'internal' | 'external'
  onReorder: (section: 'internal' | 'external', fromId: string, toId: string) => void
  renderCard: (
    app: AppInfo,
    isDragOver: boolean,
    handlers: DragHandlers,
    section: 'internal' | 'external',
  ) => React.ReactNode
}) {
  const dragId = useRef<string | null>(null)
  const [dragOverId, setDragOverId] = useState<string | null>(null)

  return (
    <div className="grid grid-cols-1 gap-px sm:grid-cols-2 lg:grid-cols-3">
      {apps.map((app) => {
        const handlers: DragHandlers = {
          onDragStart: () => {
            dragId.current = app.id
          },
          onDragOver: (e: React.DragEvent) => {
            e.preventDefault()
            e.dataTransfer.dropEffect = 'move'
            if (dragId.current && dragId.current !== app.id) {
              setDragOverId(app.id)
            }
          },
          onDragEnd: () => {
            dragId.current = null
            setDragOverId(null)
          },
          onDrop: (e: React.DragEvent) => {
            e.preventDefault()
            if (dragId.current && dragId.current !== app.id) {
              onReorder(section, dragId.current, app.id)
            }
            dragId.current = null
            setDragOverId(null)
          },
        }
        return renderCard(app, dragOverId === app.id, handlers, section)
      })}
    </div>
  )
}

interface DragHandlers {
  onDragStart: () => void
  onDragOver: (e: React.DragEvent) => void
  onDragEnd: () => void
  onDrop: (e: React.DragEvent) => void
}

export default function Home() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [toolboxOpen, setToolboxOpen] = useState(false)
  const [toolboxAnchor, setToolboxAnchor] = useState<DOMRect | null>(null)
  const { sortedInternal, sortedExternal, comingSoon, hiddenApps, reorder, hide, unhide } =
    useAppOrder()

  const openApp = (app: AppInfo, rect: DOMRect) => {
    if (app.id === 'toolbox') {
      setToolboxAnchor(rect)
      setToolboxOpen(true)
      return
    }
    if (app.externalUrl) {
      window.location.href = app.externalUrl
    } else {
      navigate(app.path)
    }
  }

  const renderCard = (
    app: AppInfo,
    isDragOver: boolean,
    handlers: DragHandlers,
    _section: 'internal' | 'external',
  ) => (
    <AppCard
      key={app.id}
      app={app}
      isHovered={hoveredId === app.id}
      onHover={setHoveredId}
      onClick={(rect) => openApp(app, rect)}
      onHide={() => hide(app.id)}
      isDragOver={isDragOver}
      onDragStart={handlers.onDragStart}
      onDragOver={handlers.onDragOver}
      onDragEnd={handlers.onDragEnd}
      onDrop={handlers.onDrop}
    />
  )

  return (
    <div className="min-h-full flex flex-col" style={{ backgroundColor: '#1a1b2e' }}>
      {/* Hero section */}
      <div className="flex flex-col items-center pt-16 pb-12 px-6">
        <p
          className="text-sm tracking-widest uppercase mb-3"
          style={{ color: 'rgba(255, 255, 255, 0.25)', letterSpacing: '0.2em' }}
        >
          Workshop
        </p>
        <h1
          style={{
            fontFamily: "'Cormorant Garamond', Georgia, serif",
            fontSize: 'clamp(1.75rem, 4vw, 2.5rem)',
            fontWeight: 400,
            color: 'rgba(255, 255, 255, 0.9)',
            letterSpacing: '0.02em',
          }}
        >
          {user?.name ? `${user.name}` : 'Welcome'}
        </h1>
        <p className="mt-2 text-sm" style={{ color: 'rgba(255, 255, 255, 0.3)' }}>
          拖拽調整順序 · 長按隱藏入口 · 選擇一個應用開始
        </p>
      </div>

      {/* Internal apps — same React project */}
      <div className="mx-auto w-full max-w-6xl px-6 pb-8">
        <p
          className="mb-4 text-xs tracking-wider uppercase"
          style={{ color: 'rgba(255, 255, 255, 0.2)', letterSpacing: '0.15em' }}
        >
          內部系統
        </p>
        <DraggableGrid
          apps={sortedInternal}
          section="internal"
          onReorder={reorder}
          renderCard={renderCard}
        />
      </div>

      {/* External apps — standalone stations */}
      {sortedExternal.length > 0 && (
        <div className="mx-auto w-full max-w-6xl px-6 pb-8">
          <p
            className="mb-4 text-xs tracking-wider uppercase"
            style={{ color: 'rgba(255, 255, 255, 0.2)', letterSpacing: '0.15em' }}
          >
            外部系統
          </p>
          <DraggableGrid
            apps={sortedExternal}
            section="external"
            onReorder={reorder}
            renderCard={renderCard}
          />
        </div>
      )}

      {/* Hidden apps — stashed via long-press */}
      {hiddenApps.length > 0 && (
        <div className="mx-auto w-full max-w-6xl px-6 pb-8">
          <p
            className="mb-4 text-xs tracking-wider uppercase"
            style={{ color: 'rgba(255, 255, 255, 0.2)', letterSpacing: '0.15em' }}
          >
            已隱藏（點擊復原）
          </p>
          <div className="flex flex-wrap gap-2">
            {hiddenApps.map((app) => (
              <button
                type="button"
                key={app.id}
                onClick={() => unhide(app.id)}
                className="group flex items-center gap-2 px-3 py-1.5 transition-all"
                style={{
                  backgroundColor: `${app.color}10`,
                  border: `1px solid ${app.color}30`,
                  borderRadius: '6px',
                  opacity: 0.6,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.opacity = '1'
                  e.currentTarget.style.backgroundColor = `${app.color}20`
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.opacity = '0.6'
                  e.currentTarget.style.backgroundColor = `${app.color}10`
                }}
                title={`復原 ${app.name}`}
              >
                <span className="text-sm">{app.icon}</span>
                <span className="text-xs" style={{ color: 'rgba(255, 255, 255, 0.7)' }}>
                  {app.name}
                </span>
                <span className="text-xs" style={{ color: app.color }}>
                  ↺
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <ToolboxPopover
        open={toolboxOpen}
        anchorRect={toolboxAnchor}
        onClose={() => setToolboxOpen(false)}
      />

      {/* Coming soon section */}
      {comingSoon.length > 0 && (
        <div className="mx-auto w-full max-w-6xl px-6 pb-16">
          <p
            className="mb-4 text-xs tracking-wider uppercase"
            style={{
              color: 'rgba(255, 255, 255, 0.15)',
              letterSpacing: '0.15em',
            }}
          >
            即將推出
          </p>
          <div className="flex flex-wrap gap-6">
            {comingSoon.map((app) => (
              <div key={app.id} className="flex items-center gap-3" style={{ opacity: 0.4 }}>
                <span
                  className="flex h-6 w-6 items-center justify-center text-sm"
                  style={{
                    backgroundColor: `${app.color}18`,
                    borderRadius: '4px',
                  }}
                >
                  {app.icon}
                </span>
                <span className="text-xs" style={{ color: 'rgba(255, 255, 255, 0.5)' }}>
                  {app.name}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

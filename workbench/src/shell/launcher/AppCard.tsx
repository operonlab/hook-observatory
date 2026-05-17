import { useRef } from 'react'
import type { LauncherItem } from '@/types'

const LONG_PRESS_MS = 500

export interface AppCardProps {
  app: LauncherItem
  isHovered: boolean
  /** 'reorder' | 'stack' | null — drives border / glow state */
  dragState: 'reorder' | 'stack' | null
  /** Stack-into-folder progress (0..1) — drives conic ring */
  stackProgress: number
  draggable: boolean
  onHover: (id: string | null) => void
  onClick: (rect: DOMRect) => void
  onHide: () => void
  onDragStart: () => void
  onDragOver: (e: React.DragEvent) => void
  onDragLeave: () => void
  onDragEnd: () => void
  onDrop: (e: React.DragEvent) => void
}

/**
 * Single app tile rendered in the launcher grid (or inside a folder).
 *
 * Visual states layered on top of base style:
 *  - hovered          → tinted background, brighter border
 *  - dragState=reorder → left-edge accent in app color
 *  - dragState=stack   → dashed outline + conic-gradient ring + scale-down,
 *                        signalling "release to form a folder with me"
 */
export default function AppCard({
  app,
  isHovered,
  dragState,
  stackProgress,
  draggable,
  onHover,
  onClick,
  onHide,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDragEnd,
  onDrop,
}: AppCardProps) {
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const longPressed = useRef(false)

  const clearPress = () => {
    if (pressTimer.current) {
      clearTimeout(pressTimer.current)
      pressTimer.current = null
    }
  }

  const isStack = dragState === 'stack'
  const isReorder = dragState === 'reorder'
  const ringAngle = Math.round(stackProgress * 360)

  return (
    <button
      type="button"
      draggable={draggable}
      onDragStart={(e) => {
        clearPress()
        e.dataTransfer.effectAllowed = 'move'
        // Hide native drag image — we rely on the source card's own opacity
        // change for "I am being dragged" feedback. Native ghost looks
        // jarring against the dark theme.
        e.currentTarget.style.opacity = '0.4'
        onDragStart()
      }}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
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
      className="group relative flex items-start gap-4 p-6 text-left"
      style={{
        backgroundColor: isHovered ? `${app.color}14` : 'transparent',
        cursor: draggable ? 'grab' : 'pointer',
        border: '1px solid rgba(255, 255, 255, 0.04)',
        borderLeft: isReorder
          ? `2px solid ${app.color}`
          : `2px solid ${isHovered ? app.color : `${app.color}40`}`,
        outline: isStack ? `2px dashed ${app.color}` : 'none',
        outlineOffset: isStack ? '-2px' : '0',
        boxShadow: isReorder
          ? `inset 0 0 0 1px ${app.color}40`
          : isStack
            ? `0 0 0 4px ${app.color}25, 0 8px 28px ${app.color}30`
            : 'none',
        transform: isStack ? `scale(${1 - 0.05 * stackProgress})` : 'scale(1)',
        transition:
          'border 0.15s ease, outline 0.15s ease, box-shadow 0.2s ease, background-color 0.2s ease, transform 0.2s cubic-bezier(0.34, 1.4, 0.5, 1)',
      }}
    >
      {/* Conic countdown ring — only visible while stacking */}
      {isStack && stackProgress > 0 ? (
        <span
          aria-hidden
          className="pointer-events-none absolute -left-1 -top-1 -right-1 -bottom-1"
          style={{
            background: `conic-gradient(${app.color} ${ringAngle}deg, transparent 0deg)`,
            WebkitMaskImage:
              'radial-gradient(closest-side, transparent calc(100% - 3px), black calc(100% - 2px), black 100%)',
            maskImage:
              'radial-gradient(closest-side, transparent calc(100% - 3px), black calc(100% - 2px), black 100%)',
            opacity: 0.85,
            transition: 'opacity 0.15s ease',
          }}
        />
      ) : null}

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
        {app.description ? (
          <p
            className="mt-1 text-xs leading-relaxed"
            style={{
              color: isHovered ? 'rgba(255, 255, 255, 0.45)' : 'rgba(255, 255, 255, 0.3)',
            }}
          >
            {app.description}
          </p>
        ) : null}
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

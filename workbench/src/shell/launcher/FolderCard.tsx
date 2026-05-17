import { useRef } from 'react'
import type { LauncherItem } from '@/types'

const LONG_PRESS_MS = 500

export interface FolderCardProps {
  folder: LauncherItem
  /** First 4 children resolved for mini-grid preview */
  previewChildren: LauncherItem[]
  isHovered: boolean
  /** True iff the dragger is dwelling on this folder for drop-into. */
  isArmed: boolean
  /** 0..1 drop-into countdown progress (drives ring + scale). */
  armProgress: number
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
 * Folder tile — visually distinct from app cards (iOS-style mini grid of
 * first 4 children) so the user instantly knows "drag into me, don't reorder".
 *
 * The conic-gradient ring around the icon doubles as the drop-into countdown.
 */
export default function FolderCard({
  folder,
  previewChildren,
  isHovered,
  isArmed,
  armProgress,
  onHover,
  onClick,
  onHide,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDragEnd,
  onDrop,
}: FolderCardProps) {
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const longPressed = useRef(false)

  const clearPress = () => {
    if (pressTimer.current) {
      clearTimeout(pressTimer.current)
      pressTimer.current = null
    }
  }

  const ringAngle = Math.round(armProgress * 360)
  const placeholders = 4 - previewChildren.length
  const childCount = previewChildren.length

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
      onMouseEnter={() => onHover(folder.id)}
      onMouseLeave={() => {
        clearPress()
        onHover(null)
      }}
      className="group relative flex items-start gap-4 p-6 text-left"
      style={{
        backgroundColor: isHovered || isArmed ? `${folder.color}14` : 'transparent',
        cursor: 'grab',
        border: '1px solid rgba(255, 255, 255, 0.04)',
        borderLeft: isArmed
          ? `2px solid ${folder.color}`
          : `2px solid ${isHovered ? folder.color : `${folder.color}40`}`,
        outline: isArmed ? `2px dashed ${folder.color}` : 'none',
        outlineOffset: isArmed ? '-2px' : '0',
        boxShadow: isArmed ? `0 0 0 4px ${folder.color}25, 0 8px 28px ${folder.color}30` : 'none',
        transform: isArmed ? `scale(${1 - 0.05 * armProgress})` : 'scale(1)',
        transition:
          'border 0.15s ease, outline 0.15s ease, box-shadow 0.2s ease, background-color 0.2s ease, transform 0.2s cubic-bezier(0.34, 1.4, 0.5, 1)',
      }}
    >
      {/* Mini-grid icon (iOS folder look) */}
      <span
        className="relative flex h-11 w-11 shrink-0 items-center justify-center"
        style={{
          backgroundColor: isHovered || isArmed ? `${folder.color}30` : `${folder.color}20`,
          border: `1px solid ${folder.color}${isHovered || isArmed ? '50' : '35'}`,
          borderRadius: '8px',
          transition: 'all 0.2s ease',
          overflow: 'hidden',
        }}
      >
        {previewChildren.length === 0 ? (
          <span className="text-xl">{folder.icon}</span>
        ) : (
          <span className="grid grid-cols-2 gap-[2px] p-[3px]">
            {previewChildren.map((c) => (
              <span
                key={c.id}
                className="flex h-[14px] w-[14px] items-center justify-center text-[10px]"
                style={{
                  backgroundColor: `${c.color}25`,
                  borderRadius: '2px',
                }}
              >
                {c.icon}
              </span>
            ))}
            {Array.from({ length: placeholders }).map((_, i) => (
              <span
                key={`ph-${i}`}
                className="h-[14px] w-[14px]"
                style={{
                  backgroundColor: 'rgba(255, 255, 255, 0.04)',
                  borderRadius: '2px',
                }}
              />
            ))}
          </span>
        )}

        {/* Conic countdown ring on the icon */}
        {isArmed && armProgress > 0 ? (
          <span
            aria-hidden
            className="pointer-events-none absolute -inset-[3px]"
            style={{
              background: `conic-gradient(${folder.color} ${ringAngle}deg, transparent 0deg)`,
              borderRadius: '11px',
              WebkitMaskImage:
                'radial-gradient(closest-side, transparent calc(100% - 3px), black calc(100% - 2px), black 100%)',
              maskImage:
                'radial-gradient(closest-side, transparent calc(100% - 3px), black calc(100% - 2px), black 100%)',
            }}
          />
        ) : null}
      </span>

      <div className="min-w-0 flex-1">
        <h3
          className="text-sm font-medium transition-colors"
          style={{
            color: isHovered || isArmed ? folder.color : 'rgba(255, 255, 255, 0.85)',
          }}
        >
          {folder.name}
          <span
            className="ml-2 text-[10px] font-normal"
            style={{ color: 'rgba(255, 255, 255, 0.35)' }}
          >
            {childCount} 個項目
          </span>
        </h3>
        {folder.description ? (
          <p
            className="mt-1 text-xs leading-relaxed"
            style={{
              color:
                isHovered || isArmed ? 'rgba(255, 255, 255, 0.45)' : 'rgba(255, 255, 255, 0.3)',
            }}
          >
            {folder.description}
          </p>
        ) : null}
      </div>
      <span
        className="mt-1 text-xs opacity-0 transition-opacity group-hover:opacity-100"
        style={{ color: folder.color }}
      >
        📂
      </span>
    </button>
  )
}

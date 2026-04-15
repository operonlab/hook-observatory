import { useEffect, useRef, useState } from 'react'
import { TOOL_LIST, type ToolEntry } from '@/shared/constants/tools'

interface ToolboxPopoverProps {
  open: boolean
  anchorRect: DOMRect | null
  onClose: () => void
}

function ToolTile({
  tool,
  isHovered,
  onHover,
  onClick,
}: {
  tool: ToolEntry
  isHovered: boolean
  onHover: (id: string | null) => void
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => onHover(tool.id)}
      onMouseLeave={() => onHover(null)}
      className="flex flex-col items-center gap-2 p-3 transition-transform"
      style={{
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        transform: isHovered ? 'scale(1.05)' : 'scale(1)',
      }}
    >
      <span
        className="flex h-16 w-16 items-center justify-center text-3xl"
        style={{
          backgroundColor: `${tool.color}25`,
          border: `1px solid ${tool.color}${isHovered ? '80' : '50'}`,
          borderRadius: '18px',
          boxShadow: isHovered ? `0 8px 24px ${tool.color}30` : 'none',
          transition: 'all 0.2s ease',
        }}
      >
        {tool.icon}
      </span>
      <span
        className="max-w-[88px] text-center text-xs leading-tight"
        style={{
          color: 'rgba(255, 255, 255, 0.85)',
          fontWeight: 500,
        }}
      >
        {tool.name}
      </span>
    </button>
  )
}

export default function ToolboxPopover({ open, anchorRect, onClose }: ToolboxPopoverProps) {
  const [mounted, setMounted] = useState(false)
  const [entered, setEntered] = useState(false)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) {
      setMounted(true)
      // Next frame so the initial styles commit before transitioning in
      const raf = requestAnimationFrame(() => setEntered(true))
      return () => cancelAnimationFrame(raf)
    }
    setEntered(false)
    // Wait for exit transition before unmounting
    const t = setTimeout(() => setMounted(false), 250)
    return () => clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!mounted) return null

  // iOS folder feel: when closed, card scales down toward the anchor (the
  // launcher card the user clicked); when open, it centers on screen.
  const originX = anchorRect ? anchorRect.left + anchorRect.width / 2 : window.innerWidth / 2
  const originY = anchorRect ? anchorRect.top + anchorRect.height / 2 : window.innerHeight / 2

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="工具箱"
      onClick={(e) => {
        if (cardRef.current && !cardRef.current.contains(e.target as Node)) {
          onClose()
        }
      }}
      className="fixed inset-0 z-[200] flex items-center justify-center"
      style={{
        background: entered ? 'rgba(10, 10, 14, 0.55)' : 'rgba(10, 10, 14, 0)',
        backdropFilter: entered ? 'blur(20px)' : 'blur(0px)',
        WebkitBackdropFilter: entered ? 'blur(20px)' : 'blur(0px)',
        transition: 'background 0.25s ease, backdrop-filter 0.25s ease',
      }}
    >
      <div
        ref={cardRef}
        className="relative mx-4 flex flex-col overflow-hidden"
        style={{
          width: 'min(520px, 92vw)',
          maxHeight: '80vh',
          backgroundColor: 'rgba(26, 27, 46, 0.92)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '24px',
          boxShadow: '0 24px 64px rgba(0, 0, 0, 0.55)',
          transform: entered
            ? 'translate(0, 0) scale(1)'
            : `translate(${originX - window.innerWidth / 2}px, ${originY - window.innerHeight / 2}px) scale(0.25)`,
          opacity: entered ? 1 : 0,
          transformOrigin: 'center',
          transition: 'transform 0.28s cubic-bezier(0.34, 1.2, 0.5, 1), opacity 0.2s ease',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 pt-5 pb-3"
          style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}
        >
          <div className="flex items-center gap-3">
            <span className="text-2xl">🧰</span>
            <div>
              <h2 className="text-base font-medium" style={{ color: 'rgba(255, 255, 255, 0.9)' }}>
                工具箱
              </h2>
              <p className="text-[11px]" style={{ color: 'rgba(255, 255, 255, 0.4)' }}>
                獨立靜態網頁小工具集合
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center text-sm transition-colors"
            style={{
              backgroundColor: 'rgba(255, 255, 255, 0.06)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '50%',
              color: 'rgba(255, 255, 255, 0.6)',
              cursor: 'pointer',
            }}
            aria-label="關閉"
          >
            ✕
          </button>
        </div>

        {/* Tiles */}
        <div className="overflow-y-auto p-6">
          {TOOL_LIST.length === 0 ? (
            <p className="text-center text-sm" style={{ color: 'rgba(255, 255, 255, 0.3)' }}>
              目前尚無工具
            </p>
          ) : (
            <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
              {TOOL_LIST.map((tool) => (
                <ToolTile
                  key={tool.id}
                  tool={tool}
                  isHovered={hoveredId === tool.id}
                  onHover={setHoveredId}
                  onClick={() => {
                    window.location.href = tool.url
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

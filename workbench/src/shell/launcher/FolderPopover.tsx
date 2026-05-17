import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { LauncherItem } from '@/types'

export interface FolderPopoverProps {
  folder: LauncherItem | null
  anchorRect: DOMRect | null
  children: LauncherItem[]
  onClose: () => void
  onOpenChild: (child: LauncherItem) => void
  onReorderChild: (folderId: string, fromId: string, toId: string) => void
  onPopChild: (childId: string) => void
  onRename: (folderId: string, name: string) => void
}

const POP_OUT_THRESHOLD_PX = 80

/**
 * iOS-style folder popover: scales up from the source card, dims background,
 * tiles children in a 3-4 column grid. Supports drag-to-reorder within and
 * drag-out-of-popover-to-eject. User-folder names are double-click editable.
 *
 * Replaces the older `ToolboxPopover` — same animation, generalised.
 */
export default function FolderPopover({
  folder,
  anchorRect,
  children: items,
  onClose,
  onOpenChild,
  onReorderChild,
  onPopChild,
  onRename,
}: FolderPopoverProps) {
  const [mounted, setMounted] = useState(false)
  const [entered, setEntered] = useState(false)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)

  const isOpen = folder != null

  // Editing folder name
  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState('')

  // Drag state (scoped to inside the popover)
  const draggedRef = useRef<string | null>(null)
  const [dragOverId, setDragOverId] = useState<string | null>(null)
  const [popHint, setPopHint] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setMounted(true)
      setDraftName(folder?.name ?? '')
      return
    }
    setEntered(false)
    setEditing(false)
    const t = setTimeout(() => setMounted(false), 260)
    return () => clearTimeout(t)
  }, [isOpen, folder])

  // Double-rAF + forced reflow so the enter animation actually runs
  // (same trick the original ToolboxPopover used — without it React may
  // batch mount + enter into a single commit and the CSS transition
  // doesn't fire).
  useEffect(() => {
    if (!isOpen || !mounted) return
    let raf1 = 0
    let raf2 = 0
    raf1 = requestAnimationFrame(() => {
      cardRef.current?.getBoundingClientRect()
      raf2 = requestAnimationFrame(() => setEntered(true))
    })
    return () => {
      cancelAnimationFrame(raf1)
      cancelAnimationFrame(raf2)
    }
  }, [isOpen, mounted])

  useEffect(() => {
    if (!isOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (editing) setEditing(false)
        else onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, editing, onClose])

  if (!mounted || !folder) return null

  const originX = anchorRect ? anchorRect.left + anchorRect.width / 2 : window.innerWidth / 2
  const originY = anchorRect ? anchorRect.top + anchorRect.height / 2 : window.innerHeight / 2

  const commitRename = () => {
    onRename(folder.id, draftName)
    setEditing(false)
  }

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={folder.name}
      onClick={(e) => {
        if (cardRef.current && !cardRef.current.contains(e.target as Node)) {
          onClose()
        }
      }}
      onDragOver={(e) => {
        // Capture drag events on the backdrop so we can detect "user
        // dragged a child outside the popover card" → eject candidate.
        if (!draggedRef.current) return
        const card = cardRef.current
        if (!card) return
        const rect = card.getBoundingClientRect()
        const outside =
          e.clientX < rect.left - POP_OUT_THRESHOLD_PX ||
          e.clientX > rect.right + POP_OUT_THRESHOLD_PX ||
          e.clientY < rect.top - POP_OUT_THRESHOLD_PX ||
          e.clientY > rect.bottom + POP_OUT_THRESHOLD_PX
        if (outside) {
          e.preventDefault()
          e.dataTransfer.dropEffect = 'move'
          setPopHint(true)
        } else {
          setPopHint(false)
        }
      }}
      onDrop={(e) => {
        // Drop outside the popover card → pop child out
        if (!draggedRef.current) return
        const card = cardRef.current
        if (!card) return
        const rect = card.getBoundingClientRect()
        const outside =
          e.clientX < rect.left - POP_OUT_THRESHOLD_PX ||
          e.clientX > rect.right + POP_OUT_THRESHOLD_PX ||
          e.clientY < rect.top - POP_OUT_THRESHOLD_PX ||
          e.clientY > rect.bottom + POP_OUT_THRESHOLD_PX
        if (outside) {
          e.preventDefault()
          onPopChild(draggedRef.current)
          draggedRef.current = null
          setDragOverId(null)
          setPopHint(false)
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
      {/* Pop-out hint overlay: tinted ring around the card when user
          drags a child outside, signalling "release to eject". */}
      {popHint ? (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 flex items-center justify-center"
          style={{
            background: `radial-gradient(circle at center, transparent 50%, ${folder.color}18 100%)`,
            transition: 'opacity 0.2s ease',
          }}
        >
          <span
            className="rounded-full px-4 py-1.5 text-xs"
            style={{
              backgroundColor: `${folder.color}30`,
              color: 'rgba(255, 255, 255, 0.85)',
              border: `1px solid ${folder.color}60`,
            }}
          >
            放開以移出資料夾
          </span>
        </div>
      ) : null}

      <div
        ref={cardRef}
        className="relative mx-4 flex flex-col overflow-hidden"
        style={{
          width: 'min(560px, 92vw)',
          maxHeight: '80vh',
          backgroundColor: 'rgba(26, 27, 46, 0.92)',
          border: `1px solid ${popHint ? folder.color + '60' : 'rgba(255, 255, 255, 0.08)'}`,
          borderRadius: '24px',
          boxShadow: '0 24px 64px rgba(0, 0, 0, 0.55)',
          transform: entered
            ? 'translate(0, 0) scale(1)'
            : `translate(${originX - window.innerWidth / 2}px, ${originY - window.innerHeight / 2}px) scale(0.25)`,
          opacity: entered ? 1 : 0,
          transformOrigin: 'center',
          transition:
            'transform 0.28s cubic-bezier(0.34, 1.2, 0.5, 1), opacity 0.2s ease, border 0.2s ease',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 pt-5 pb-3"
          style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}
        >
          <div className="flex items-center gap-3">
            <span className="text-2xl">{folder.icon}</span>
            <div>
              {editing && !folder.builtIn ? (
                <input
                  autoFocus
                  type="text"
                  value={draftName}
                  onChange={(e) => setDraftName(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename()
                    if (e.key === 'Escape') {
                      setDraftName(folder.name)
                      setEditing(false)
                    }
                  }}
                  className="text-base font-medium"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    borderBottom: `1px solid ${folder.color}`,
                    outline: 'none',
                    color: 'rgba(255, 255, 255, 0.95)',
                    padding: '0 0 2px 0',
                    minWidth: 160,
                  }}
                />
              ) : (
                <h2
                  className="text-base font-medium"
                  style={{
                    color: 'rgba(255, 255, 255, 0.9)',
                    cursor: folder.builtIn ? 'default' : 'text',
                  }}
                  onDoubleClick={() => {
                    if (!folder.builtIn) setEditing(true)
                  }}
                  title={folder.builtIn ? undefined : '雙擊重新命名'}
                >
                  {folder.name}
                </h2>
              )}
              <p className="text-[11px]" style={{ color: 'rgba(255, 255, 255, 0.4)' }}>
                {folder.description ?? '使用者建立的資料夾'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center text-sm"
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
          {items.length === 0 ? (
            <p className="text-center text-sm" style={{ color: 'rgba(255, 255, 255, 0.3)' }}>
              這個資料夾還是空的 — 把 App 拖進來吧
            </p>
          ) : (
            <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
              {items.map((tool) => {
                const isHovered = hoveredId === tool.id
                const isDragOver = dragOverId === tool.id
                return (
                  <button
                    type="button"
                    key={tool.id}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = 'move'
                      draggedRef.current = tool.id
                      e.currentTarget.style.opacity = '0.4'
                    }}
                    onDragOver={(e) => {
                      e.preventDefault()
                      e.dataTransfer.dropEffect = 'move'
                      if (draggedRef.current && draggedRef.current !== tool.id) {
                        setDragOverId(tool.id)
                      }
                    }}
                    onDragLeave={() => {
                      if (dragOverId === tool.id) setDragOverId(null)
                    }}
                    onDragEnd={(e) => {
                      e.currentTarget.style.opacity = '1'
                      draggedRef.current = null
                      setDragOverId(null)
                      setPopHint(false)
                    }}
                    onDrop={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      const from = draggedRef.current
                      if (from && from !== tool.id) {
                        onReorderChild(folder.id, from, tool.id)
                      }
                      draggedRef.current = null
                      setDragOverId(null)
                    }}
                    onClick={() => onOpenChild(tool)}
                    onMouseEnter={() => setHoveredId(tool.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    className="flex flex-col items-center gap-2 p-3"
                    style={{
                      background: isDragOver ? `${tool.color}18` : 'transparent',
                      border: 'none',
                      borderRadius: '14px',
                      cursor: 'pointer',
                      transform: isHovered && !isDragOver ? 'scale(1.05)' : 'scale(1)',
                      transition: 'transform 0.18s ease, background 0.18s ease',
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
              })}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

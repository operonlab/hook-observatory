import { useCallback, useEffect, useRef, useState } from 'react'

/** ms a draggable must hover over a folder/app before drop-into / auto-folder. */
export const HOVER_INTO_MS = 600

export type DragAction =
  | { kind: 'idle' }
  | { kind: 'reorder'; overId: string }
  | { kind: 'drop-into-folder'; folderId: string; progress: number }
  | { kind: 'stack-folder'; targetAppId: string; progress: number }

interface DragControllerOptions {
  /** Called when hover-into countdown completes and user releases. */
  onDropIntoFolder: (folderId: string, draggedId: string) => void
  /** Called when stack-folder countdown completes and user releases. */
  onStackFolder: (targetAppId: string, draggedId: string) => void
  /** Called for plain reorder drop. */
  onReorder: (fromId: string, toId: string) => void
}

interface OverPayload {
  id: string
  /** What kind of element are we over? */
  kind: 'app' | 'folder'
}

/**
 * State machine for the launcher's drag interactions.
 *
 * Why: native HTML5 DnD only gives us start/over/end/drop events. To
 * differentiate "user is hovering long enough to mean *drop into*" from
 * "user is just passing through to reorder", we measure dwell time and
 * publish an interpolated progress (0→1) for the conic-gradient ring.
 */
export function useDragController({
  onDropIntoFolder,
  onStackFolder,
  onReorder,
}: DragControllerOptions) {
  const draggedId = useRef<string | null>(null)
  const overPayload = useRef<OverPayload | null>(null)
  const dwellStartedAt = useRef<number | null>(null)
  const rafHandle = useRef<number | null>(null)
  const [action, setAction] = useState<DragAction>({ kind: 'idle' })

  const stopTimer = useCallback(() => {
    if (rafHandle.current != null) {
      cancelAnimationFrame(rafHandle.current)
      rafHandle.current = null
    }
    dwellStartedAt.current = null
  }, [])

  const reset = useCallback(() => {
    draggedId.current = null
    overPayload.current = null
    stopTimer()
    setAction({ kind: 'idle' })
  }, [stopTimer])

  const tick = useCallback(() => {
    rafHandle.current = null
    const started = dwellStartedAt.current
    const over = overPayload.current
    const dragged = draggedId.current
    if (started == null || over == null || dragged == null) {
      setAction({ kind: 'idle' })
      return
    }
    const elapsed = performance.now() - started
    const progress = Math.min(1, elapsed / HOVER_INTO_MS)
    if (over.kind === 'folder') {
      setAction({ kind: 'drop-into-folder', folderId: over.id, progress })
    } else if (over.kind === 'app') {
      // Only show stack-folder hint after we've started the dwell —
      // for the first ~120ms keep the reorder hint to avoid flicker.
      if (progress < 0.2) setAction({ kind: 'reorder', overId: over.id })
      else setAction({ kind: 'stack-folder', targetAppId: over.id, progress })
    }
    if (progress < 1) {
      rafHandle.current = requestAnimationFrame(tick)
    }
  }, [])

  const onDragStart = useCallback((id: string) => {
    draggedId.current = id
    setAction({ kind: 'idle' })
  }, [])

  const onDragOver = useCallback(
    (target: OverPayload | null) => {
      const dragged = draggedId.current
      if (!dragged || !target || target.id === dragged) {
        if (overPayload.current) {
          overPayload.current = null
          stopTimer()
          setAction({ kind: 'idle' })
        }
        return
      }
      if (overPayload.current?.id === target.id && overPayload.current.kind === target.kind) {
        // Already tracking this target — let the rAF tick keep ticking
        return
      }
      // Switched target → restart dwell
      overPayload.current = target
      dwellStartedAt.current = performance.now()
      if (rafHandle.current == null) {
        rafHandle.current = requestAnimationFrame(tick)
      }
      // Fire an immediate reorder hint so the user sees feedback before
      // the dwell threshold kicks in (UX: tiny delay feels broken).
      setAction({ kind: 'reorder', overId: target.id })
    },
    [stopTimer, tick],
  )

  const onDragLeaveTarget = useCallback(
    (id: string) => {
      if (overPayload.current?.id === id) {
        overPayload.current = null
        stopTimer()
        setAction({ kind: 'idle' })
      }
    },
    [stopTimer],
  )

  const onDrop = useCallback(() => {
    const dragged = draggedId.current
    const over = overPayload.current
    if (!dragged || !over || over.id === dragged) {
      reset()
      return
    }
    const elapsed = dwellStartedAt.current != null ? performance.now() - dwellStartedAt.current : 0
    const long = elapsed >= HOVER_INTO_MS

    if (over.kind === 'folder') {
      // Folder: short dwell or long dwell both drop-into (folders never reorder via app drop)
      onDropIntoFolder(over.id, dragged)
    } else if (long) {
      onStackFolder(over.id, dragged)
    } else {
      onReorder(dragged, over.id)
    }
    reset()
  }, [onDropIntoFolder, onStackFolder, onReorder, reset])

  const onDragEnd = useCallback(() => {
    reset()
  }, [reset])

  useEffect(() => stopTimer, [stopTimer])

  return {
    action,
    draggedId: draggedId.current,
    onDragStart,
    onDragOver,
    onDragLeaveTarget,
    onDrop,
    onDragEnd,
  }
}

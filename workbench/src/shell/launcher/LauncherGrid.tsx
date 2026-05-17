import { useCallback } from 'react'
import type { LauncherItem } from '@/types'
import AppCard from './AppCard'
import FolderCard from './FolderCard'
import { useDragController } from './useDragController'

export interface LauncherGridProps {
  items: LauncherItem[]
  getFolderChildren: (folderId: string) => LauncherItem[]
  hoveredId: string | null
  onHover: (id: string | null) => void
  onOpenApp: (app: LauncherItem, rect: DOMRect) => void
  onOpenFolder: (folder: LauncherItem, rect: DOMRect) => void
  onHide: (id: string) => void
  onReorder: (fromId: string, toId: string) => void
  onDropIntoFolder: (folderId: string, draggedId: string) => void
  onStackFolder: (targetAppId: string, draggedId: string) => void
}

/**
 * Top-level launcher grid. Coordinates a `useDragController` so each card can
 * report its own drag events without each card owning state — the controller
 * publishes the current high-level `DragAction` and the grid passes the right
 * slice down to each card.
 */
export default function LauncherGrid({
  items,
  getFolderChildren,
  hoveredId,
  onHover,
  onOpenApp,
  onOpenFolder,
  onHide,
  onReorder,
  onDropIntoFolder,
  onStackFolder,
}: LauncherGridProps) {
  const controller = useDragController({
    onDropIntoFolder,
    onStackFolder,
    onReorder,
  })

  const { action } = controller

  const stateFor = useCallback(
    (id: string): { drag: 'reorder' | 'stack' | null; progress: number; folderArmed: boolean } => {
      if (action.kind === 'reorder' && action.overId === id) {
        return { drag: 'reorder', progress: 0, folderArmed: false }
      }
      if (action.kind === 'stack-folder' && action.targetAppId === id) {
        return { drag: 'stack', progress: action.progress, folderArmed: false }
      }
      if (action.kind === 'drop-into-folder' && action.folderId === id) {
        return { drag: null, progress: action.progress, folderArmed: true }
      }
      return { drag: null, progress: 0, folderArmed: false }
    },
    [action],
  )

  return (
    <div className="grid grid-cols-1 gap-px sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => {
        if (item.kind === 'folder') {
          const s = stateFor(item.id)
          const previewChildren = getFolderChildren(item.id).slice(0, 4)
          return (
            <FolderCard
              key={item.id}
              folder={item}
              previewChildren={previewChildren}
              isHovered={hoveredId === item.id}
              isArmed={s.folderArmed}
              armProgress={s.folderArmed ? s.progress : 0}
              onHover={onHover}
              onClick={(rect) => onOpenFolder(item, rect)}
              onHide={() => onHide(item.id)}
              onDragStart={() => controller.onDragStart(item.id)}
              onDragOver={(e) => {
                e.preventDefault()
                e.dataTransfer.dropEffect = 'move'
                controller.onDragOver({ id: item.id, kind: 'folder' })
              }}
              onDragLeave={() => controller.onDragLeaveTarget(item.id)}
              onDragEnd={controller.onDragEnd}
              onDrop={(e) => {
                e.preventDefault()
                controller.onDrop()
              }}
            />
          )
        }

        const s = stateFor(item.id)
        return (
          <AppCard
            key={item.id}
            app={item}
            isHovered={hoveredId === item.id}
            dragState={s.drag}
            stackProgress={s.drag === 'stack' ? s.progress : 0}
            draggable={item.status !== 'coming-soon'}
            onHover={onHover}
            onClick={(rect) => onOpenApp(item, rect)}
            onHide={() => onHide(item.id)}
            onDragStart={() => controller.onDragStart(item.id)}
            onDragOver={(e) => {
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
              controller.onDragOver({ id: item.id, kind: 'app' })
            }}
            onDragLeave={() => controller.onDragLeaveTarget(item.id)}
            onDragEnd={controller.onDragEnd}
            onDrop={(e) => {
              e.preventDefault()
              controller.onDrop()
            }}
          />
        )
      })}
    </div>
  )
}

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { useLauncherLayout } from '@/hooks/useLauncherLayout'
import FolderPopover from '@/shell/launcher/FolderPopover'
import LauncherGrid from '@/shell/launcher/LauncherGrid'
import type { LauncherItem } from '@/types'

export default function Home() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [openFolder, setOpenFolder] = useState<LauncherItem | null>(null)
  const [folderAnchor, setFolderAnchor] = useState<DOMRect | null>(null)

  const {
    sortedInternal,
    sortedExternal,
    comingSoon,
    hiddenApps,
    getFolderChildren,
    reorderTopLevel,
    reorderInFolder,
    dropIntoFolder,
    popFromFolder,
    createFolderFromStack,
    renameFolder,
    hide,
    unhide,
  } = useLauncherLayout()

  const openApp = (app: LauncherItem) => {
    if (app.externalUrl) {
      window.location.href = app.externalUrl
    } else if (app.path) {
      navigate(app.path)
    }
  }

  const openFolderCard = (folder: LauncherItem, rect: DOMRect) => {
    setOpenFolder(folder)
    setFolderAnchor(rect)
  }

  const closeFolder = () => {
    setOpenFolder(null)
  }

  const folderChildren = openFolder ? getFolderChildren(openFolder.id) : []

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
          拖拽調整順序 · 拖到資料夾停留即放入 · 兩 App 疊起建資料夾 · 長按隱藏
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
        <LauncherGrid
          items={sortedInternal}
          getFolderChildren={getFolderChildren}
          hoveredId={hoveredId}
          onHover={setHoveredId}
          onOpenApp={openApp}
          onOpenFolder={openFolderCard}
          onHide={hide}
          onReorder={(from, to) => reorderTopLevel('internal', from, to)}
          onDropIntoFolder={dropIntoFolder}
          onStackFolder={createFolderFromStack}
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
          <LauncherGrid
            items={sortedExternal}
            getFolderChildren={getFolderChildren}
            hoveredId={hoveredId}
            onHover={setHoveredId}
            onOpenApp={openApp}
            onOpenFolder={openFolderCard}
            onHide={hide}
            onReorder={(from, to) => reorderTopLevel('external', from, to)}
            onDropIntoFolder={dropIntoFolder}
            onStackFolder={createFolderFromStack}
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
                className="group flex items-center gap-2 px-3 py-1.5"
                style={{
                  backgroundColor: `${app.color}10`,
                  border: `1px solid ${app.color}30`,
                  borderRadius: '6px',
                  opacity: 0.6,
                  transition: 'all 0.2s ease',
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

      <FolderPopover
        folder={openFolder}
        anchorRect={folderAnchor}
        children={folderChildren}
        onClose={closeFolder}
        onOpenChild={(child) => {
          closeFolder()
          openApp(child)
        }}
        onReorderChild={reorderInFolder}
        onPopChild={popFromFolder}
        onRename={renameFolder}
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

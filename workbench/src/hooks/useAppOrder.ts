import { useCallback, useSyncExternalStore } from 'react'
import { APP_LIST } from '@/shared/constants/apps'
import type { AppInfo } from '@/types'

const STORAGE_KEY = 'workshop-app-order'

type SavedOrder = { internal: string[]; external: string[] }

function getSnapshot(): SavedOrder | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

// Simple pub-sub so useSyncExternalStore re-renders on writes
let listeners: (() => void)[] = []
let cachedSnapshot = getSnapshot()

function subscribe(cb: () => void) {
  listeners = [...listeners, cb]
  return () => {
    listeners = listeners.filter((l) => l !== cb)
  }
}

function emitChange() {
  cachedSnapshot = getSnapshot()
  for (const l of listeners) l()
}

function getSnapshotCached() {
  return cachedSnapshot
}

function sortApps(apps: AppInfo[], savedIds: string[] | undefined): AppInfo[] {
  if (!savedIds?.length) return apps
  const idxMap = new Map(savedIds.map((id, i) => [id, i]))
  return [...apps].sort((a, b) => {
    const ai = idxMap.get(a.id) ?? Infinity
    const bi = idxMap.get(b.id) ?? Infinity
    return ai - bi
  })
}

export function useAppOrder() {
  const saved = useSyncExternalStore(subscribe, getSnapshotCached, () => null)

  const internal = APP_LIST.filter((a) => a.status === 'available')
  const external = APP_LIST.filter((a) => a.status === 'external')
  const comingSoon = APP_LIST.filter((a) => a.status === 'coming-soon')

  const sortedInternal = sortApps(internal, saved?.internal)
  const sortedExternal = sortApps(external, saved?.external)

  const reorder = useCallback(
    (section: 'internal' | 'external', fromId: string, toId: string) => {
      const list = section === 'internal' ? [...sortedInternal] : [...sortedExternal]
      const fromIdx = list.findIndex((a) => a.id === fromId)
      const toIdx = list.findIndex((a) => a.id === toId)
      if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return

      const [moved] = list.splice(fromIdx, 1)
      list.splice(toIdx, 0, moved)

      const prev = getSnapshot()
      const next: SavedOrder = {
        internal: section === 'internal' ? list.map((a) => a.id) : (prev?.internal ?? []),
        external: section === 'external' ? list.map((a) => a.id) : (prev?.external ?? []),
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      emitChange()
    },
    [sortedInternal, sortedExternal],
  )

  // All available apps in user's order (for AppLauncher)
  const allOrdered = [...sortedInternal, ...sortedExternal]

  return { sortedInternal, sortedExternal, comingSoon, allOrdered, reorder }
}

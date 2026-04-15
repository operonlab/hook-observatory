import { useCallback, useEffect, useSyncExternalStore } from 'react'
import { getPreferences, updatePreferences } from '@/api/gateway'
import { APP_LIST } from '@/shared/constants/apps'
import type { AppInfo } from '@/types'

const STORAGE_KEY = 'workshop-app-order'

type SavedOrder = { internal: string[]; external: string[]; hidden?: string[] }

// --- Local cache (localStorage as offline fallback + instant UI) ---

function readCache(): SavedOrder | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function writeCache(order: SavedOrder) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(order))
  } catch {
    // QuotaExceededError in private browsing — ignore
  }
}

// Simple pub-sub so useSyncExternalStore re-renders on writes
let listeners: (() => void)[] = []
let cachedSnapshot = readCache()

function subscribe(cb: () => void) {
  listeners = [...listeners, cb]
  return () => {
    listeners = listeners.filter((l) => l !== cb)
  }
}

function emitChange() {
  cachedSnapshot = readCache()
  for (const l of listeners) l()
}

function getSnapshotCached() {
  return cachedSnapshot
}

// --- Backend sync ---

let synced = false

async function syncFromBackend() {
  if (synced) return
  try {
    const prefs = await getPreferences()
    const remote = prefs.app_order as SavedOrder | undefined
    if (remote) {
      writeCache(remote)
      emitChange()
    }
    synced = true
  } catch {
    // Offline or not authenticated — use local cache
  }
}

async function persistToBackend(order: SavedOrder) {
  try {
    await updatePreferences({ app_order: order })
  } catch {
    // Offline — local cache is already written, will sync next time
  }
}

// --- Sorting ---

function sortApps(apps: AppInfo[], savedIds: string[] | undefined): AppInfo[] {
  if (!savedIds?.length) return apps
  const idxMap = new Map(savedIds.map((id, i) => [id, i]))
  return [...apps].sort((a, b) => {
    const ai = idxMap.get(a.id) ?? Infinity
    const bi = idxMap.get(b.id) ?? Infinity
    return ai - bi
  })
}

// --- Hook ---

function persistMerged(patch: Partial<SavedOrder>) {
  const prev = readCache()
  const next: SavedOrder = {
    internal: patch.internal ?? prev?.internal ?? [],
    external: patch.external ?? prev?.external ?? [],
    hidden: patch.hidden ?? prev?.hidden ?? [],
  }
  writeCache(next)
  emitChange()
  persistToBackend(next)
}

export function useAppOrder() {
  const saved = useSyncExternalStore(subscribe, getSnapshotCached, () => null)

  useEffect(() => {
    syncFromBackend()
  }, [])

  const hiddenSet = new Set(saved?.hidden ?? [])

  const internal = APP_LIST.filter((a) => a.status === 'available' && !hiddenSet.has(a.id))
  const external = APP_LIST.filter((a) => a.status === 'external' && !hiddenSet.has(a.id))
  const comingSoon = APP_LIST.filter((a) => a.status === 'coming-soon')

  const sortedInternal = sortApps(internal, saved?.internal)
  const sortedExternal = sortApps(external, saved?.external)

  const hiddenApps = APP_LIST.filter(
    (a) => hiddenSet.has(a.id) && (a.status === 'available' || a.status === 'external'),
  )

  const reorder = useCallback(
    (section: 'internal' | 'external', fromId: string, toId: string) => {
      const list = section === 'internal' ? [...sortedInternal] : [...sortedExternal]
      const fromIdx = list.findIndex((a) => a.id === fromId)
      const toIdx = list.findIndex((a) => a.id === toId)
      if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return

      const [moved] = list.splice(fromIdx, 1)
      list.splice(toIdx, 0, moved)

      const patch: Partial<SavedOrder> =
        section === 'internal'
          ? { internal: list.map((a) => a.id) }
          : { external: list.map((a) => a.id) }
      persistMerged(patch)
    },
    [sortedInternal, sortedExternal],
  )

  const hide = useCallback((id: string) => {
    const prev = readCache()
    const prevHidden = prev?.hidden ?? []
    if (prevHidden.includes(id)) return
    persistMerged({ hidden: [...prevHidden, id] })
  }, [])

  const unhide = useCallback((id: string) => {
    const prev = readCache()
    const prevHidden = prev?.hidden ?? []
    if (!prevHidden.includes(id)) return
    persistMerged({ hidden: prevHidden.filter((x) => x !== id) })
  }, [])

  const allOrdered = [...sortedInternal, ...sortedExternal]

  return {
    sortedInternal,
    sortedExternal,
    comingSoon,
    hiddenApps,
    allOrdered,
    reorder,
    hide,
    unhide,
  }
}

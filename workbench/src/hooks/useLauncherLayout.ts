import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react'
import { getPreferences, updatePreferences } from '@/api/gateway'
import { buildDefaultLayout, LAUNCHER_ITEMS } from '@/shared/constants/apps'
import type { AppLayoutV2, LauncherItem } from '@/types'

const STORAGE_KEY = 'workshop-app-layout'
const LEGACY_KEY = 'workshop-app-order'

type Section = 'internal' | 'external'

// ─────────────────────────────────────────────────────────────────
// v1 → v2 migration
// ─────────────────────────────────────────────────────────────────

interface AppLayoutV1 {
  internal?: string[]
  external?: string[]
  hidden?: string[]
}

function isV2(layout: unknown): layout is AppLayoutV2 {
  return (
    typeof layout === 'object' && layout !== null && (layout as { version?: number }).version === 2
  )
}

function migrateV1(v1: AppLayoutV1): AppLayoutV2 {
  const base = buildDefaultLayout()
  // Preserve any ordering the user already set; fall back to defaults.
  // Old v1 didn't know about folders, so all v1 ids land at top-level —
  // we then move any default-folder children back into their folder so
  // toolbox content doesn't suddenly explode onto the launcher grid.
  const v1Internal = v1.internal ?? []
  const v1External = v1.external ?? []
  const v1Hidden = v1.hidden ?? []

  // Strip ids that belong to a built-in folder by default — keep them
  // inside the folder. (Toolbox children sitting at top-level in v1 was
  // never the user's choice; the launcher just couldn't render them.)
  const folderChildren = new Set<string>()
  for (const children of Object.values(base.folders)) {
    for (const c of children) folderChildren.add(c)
  }

  const filteredInternal = v1Internal.filter((id) => !folderChildren.has(id))
  const filteredExternal = v1External.filter((id) => !folderChildren.has(id))

  // Add any ids the user has but we don't know about → append to defaults.
  const merge = (saved: string[], def: string[]) => {
    const seen = new Set(saved)
    return [...saved, ...def.filter((id) => !seen.has(id))]
  }

  return {
    ...base,
    internal: merge(filteredInternal, base.internal),
    external: merge(filteredExternal, base.external),
    hidden: v1Hidden,
  }
}

function normalize(raw: unknown): AppLayoutV2 {
  if (isV2(raw)) {
    // Trust v2 but heal missing fields just in case.
    const def = buildDefaultLayout()
    return {
      version: 2,
      internal: Array.isArray(raw.internal) ? raw.internal : def.internal,
      external: Array.isArray(raw.external) ? raw.external : def.external,
      folders: typeof raw.folders === 'object' && raw.folders !== null ? raw.folders : def.folders,
      userFolders:
        typeof raw.userFolders === 'object' && raw.userFolders !== null ? raw.userFolders : {},
      hidden: Array.isArray(raw.hidden) ? raw.hidden : [],
    }
  }
  if (typeof raw === 'object' && raw !== null) {
    return migrateV1(raw as AppLayoutV1)
  }
  return buildDefaultLayout()
}

// ─────────────────────────────────────────────────────────────────
// localStorage cache + pubsub
// ─────────────────────────────────────────────────────────────────

function readCache(): AppLayoutV2 {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return normalize(JSON.parse(raw))
    // Try legacy key if v2 cache absent
    const legacy = localStorage.getItem(LEGACY_KEY)
    if (legacy) return normalize(JSON.parse(legacy))
  } catch {
    // ignore parse errors
  }
  return buildDefaultLayout()
}

function writeCache(layout: AppLayoutV2) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layout))
  } catch {
    // QuotaExceededError in private browsing — ignore
  }
}

let listeners: (() => void)[] = []
let cachedSnapshot: AppLayoutV2 = readCache()

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

function getSnapshot() {
  return cachedSnapshot
}

// ─────────────────────────────────────────────────────────────────
// Backend sync (one-shot per session)
// ─────────────────────────────────────────────────────────────────

let synced = false

/** Returns true if localStorage already has a v2 layout written. */
function localIsV2(): boolean {
  return typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY) !== null
}

async function syncFromBackend() {
  if (synced) return
  synced = true
  try {
    const prefs = await getPreferences()
    const remote = prefs.app_order
    if (!remote) return

    // Case 1: backend already has v2 — trust it (multi-device sync).
    if (isV2(remote)) {
      const normalized = normalize(remote)
      writeCache(normalized)
      emitChange()
      return
    }

    // Case 2: backend stuck on v1 (or earlier) but local already migrated
    // to v2 — local has user mutations (drag-into-folder, rename, etc.)
    // that v1 can't represent. Push local up rather than clobbering it
    // with the migration of a stale snapshot.
    if (localIsV2()) {
      const local = readCache()
      void persistToBackend(local)
      return
    }

    // Case 3: first launch on this device — take backend v1 (will be
    // re-persisted as v2 on the next mutation).
    const normalized = normalize(remote)
    writeCache(normalized)
    emitChange()
  } catch {
    // Offline or unauthenticated — use cache
  }
}

async function persistToBackend(layout: AppLayoutV2) {
  try {
    await updatePreferences({ app_order: layout })
  } catch {
    // Offline — cache already written, will sync on next mutation
  }
}

function commit(layout: AppLayoutV2) {
  writeCache(layout)
  emitChange()
  void persistToBackend(layout)
}

// ─────────────────────────────────────────────────────────────────
// Pure layout operations (exported for tests, used internally)
// ─────────────────────────────────────────────────────────────────

function sectionOf(layout: AppLayoutV2, id: string): Section | null {
  if (layout.internal.includes(id)) return 'internal'
  if (layout.external.includes(id)) return 'external'
  return null
}

function findParentFolder(layout: AppLayoutV2, id: string): string | null {
  for (const [folderId, children] of Object.entries(layout.folders)) {
    if (children.includes(id)) return folderId
  }
  return null
}

function removeFromAll(layout: AppLayoutV2, id: string): AppLayoutV2 {
  const internal = layout.internal.filter((x) => x !== id)
  const external = layout.external.filter((x) => x !== id)
  const folders: Record<string, string[]> = {}
  for (const [fid, children] of Object.entries(layout.folders)) {
    const filtered = children.filter((x) => x !== id)
    if (filtered.length > 0) folders[fid] = filtered
  }
  return { ...layout, internal, external, folders }
}

function nanoid(): string {
  // 6 chars, time-prefixed for sort stability — sufficient for folder ids
  return Date.now().toString(36).slice(-4) + Math.random().toString(36).slice(2, 4)
}

// ─────────────────────────────────────────────────────────────────
// Public hook
// ─────────────────────────────────────────────────────────────────

export function useLauncherLayout() {
  const layout = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  useEffect(() => {
    void syncFromBackend()
  }, [])

  // Resolve user folders + apply per-user overrides to built-in folders.
  // userFolders is partial — fields the user hasn't touched fall back to
  // the apps.ts defaults (for built-ins) or sensible defaults (for new
  // user folders).
  const itemMap = useMemo(() => {
    const map = new Map<string, LauncherItem>()
    for (const item of LAUNCHER_ITEMS) map.set(item.id, item)
    for (const [id, meta] of Object.entries(layout.userFolders)) {
      const existing = map.get(id)
      if (existing && existing.kind === 'folder') {
        // Override a built-in folder's fields with user edits
        map.set(id, {
          ...existing,
          name: meta.name ?? existing.name,
          description: meta.description ?? existing.description,
          icon: meta.icon ?? existing.icon,
          color: meta.color ?? existing.color,
        })
      } else {
        // Brand-new user folder
        map.set(id, {
          id,
          kind: 'folder',
          name: meta.name ?? '新資料夾',
          description: meta.description ?? '使用者建立的資料夾',
          icon: meta.icon ?? '📁',
          color: meta.color ?? '#89dceb',
          // user folders default to external section bucket
          status: 'external',
          builtIn: false,
        })
      }
    }
    return map
  }, [layout.userFolders])

  const hiddenSet = useMemo(() => new Set(layout.hidden), [layout.hidden])

  const resolve = useCallback(
    (ids: string[]): LauncherItem[] => {
      const out: LauncherItem[] = []
      for (const id of ids) {
        const item = itemMap.get(id)
        if (item && !hiddenSet.has(id)) out.push(item)
      }
      return out
    },
    [itemMap, hiddenSet],
  )

  const sortedInternal = useMemo(() => resolve(layout.internal), [resolve, layout.internal])
  const sortedExternal = useMemo(() => resolve(layout.external), [resolve, layout.external])

  const comingSoon = useMemo(
    () => LAUNCHER_ITEMS.filter((a) => a.kind === 'app' && a.status === 'coming-soon'),
    [],
  )

  const hiddenApps = useMemo(() => {
    const out: LauncherItem[] = []
    for (const id of layout.hidden) {
      const item = itemMap.get(id)
      if (item && (item.status === 'available' || item.status === 'external')) {
        out.push(item)
      }
    }
    return out
  }, [itemMap, layout.hidden])

  // Flattened apps list (for header drop-down — folders don't make sense there)
  const flatApps = useMemo(() => {
    const out: LauncherItem[] = []
    const visit = (ids: string[]) => {
      for (const id of ids) {
        const item = itemMap.get(id)
        if (!item || hiddenSet.has(id)) continue
        if (item.kind === 'app') out.push(item)
        else {
          const children = layout.folders[id] ?? []
          visit(children)
        }
      }
    }
    visit(layout.internal)
    visit(layout.external)
    return out
  }, [itemMap, hiddenSet, layout.internal, layout.external, layout.folders])

  /** Get children of a folder, resolved to LauncherItem[]. */
  const getFolderChildren = useCallback(
    (folderId: string): LauncherItem[] => {
      const ids = layout.folders[folderId] ?? []
      return resolve(ids)
    },
    [layout.folders, resolve],
  )

  /**
   * Resolve a single id to its current LauncherItem (or undefined). Use this
   * over storing a LauncherItem in component state — items change as the
   * user edits folder metadata, and stored snapshots go stale.
   */
  const getItem = useCallback(
    (id: string | null): LauncherItem | null => {
      if (!id) return null
      return itemMap.get(id) ?? null
    },
    [itemMap],
  )

  // ── Mutations ──────────────────────────────────────────────────

  /** Reorder within a section (top-level swap). No-op across sections. */
  const reorderTopLevel = useCallback(
    (section: Section, fromId: string, toId: string) => {
      const list = [...(section === 'internal' ? layout.internal : layout.external)]
      const fromIdx = list.indexOf(fromId)
      const toIdx = list.indexOf(toId)
      if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return
      const [moved] = list.splice(fromIdx, 1)
      list.splice(toIdx, 0, moved)
      commit({ ...layout, [section]: list } as AppLayoutV2)
    },
    [layout],
  )

  /** Reorder app within a folder. */
  const reorderInFolder = useCallback(
    (folderId: string, fromId: string, toId: string) => {
      const list = [...(layout.folders[folderId] ?? [])]
      const fromIdx = list.indexOf(fromId)
      const toIdx = list.indexOf(toId)
      if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return
      const [moved] = list.splice(fromIdx, 1)
      list.splice(toIdx, 0, moved)
      commit({
        ...layout,
        folders: { ...layout.folders, [folderId]: list },
      })
    },
    [layout],
  )

  /** Drop app `appId` into folder `folderId` (append at end). */
  const dropIntoFolder = useCallback(
    (folderId: string, appId: string) => {
      const folder = itemMap.get(folderId)
      if (!folder || folder.kind !== 'folder') return
      const app = itemMap.get(appId)
      if (!app || app.kind !== 'app') return
      // already inside this folder?
      const current = layout.folders[folderId] ?? []
      if (current.includes(appId)) return
      const cleaned = removeFromAll(layout, appId)
      commit({
        ...cleaned,
        folders: { ...cleaned.folders, [folderId]: [...current, appId] },
      })
    },
    [layout, itemMap],
  )

  /** Pop app out of its folder back to the folder's section. */
  const popFromFolder = useCallback(
    (appId: string, targetSection?: Section) => {
      const parent = findParentFolder(layout, appId)
      if (!parent) return
      const folderSection = sectionOf(layout, parent) ?? 'external'
      const dest = targetSection ?? folderSection

      // Remove from folder
      const folderChildren = (layout.folders[parent] ?? []).filter((x) => x !== appId)
      const folders = { ...layout.folders }
      if (folderChildren.length > 0) folders[parent] = folderChildren
      else delete folders[parent]

      // Append to section top-level (after the folder itself)
      const list = [...(dest === 'internal' ? layout.internal : layout.external)]
      const folderIdx = list.indexOf(parent)
      const insertAt = folderIdx >= 0 ? folderIdx + 1 : list.length
      list.splice(insertAt, 0, appId)

      // Auto-delete empty non-builtIn folder
      const folderItem = itemMap.get(parent)
      let userFolders = layout.userFolders
      let internal = layout.internal
      let external = layout.external
      if (folderChildren.length === 0 && folderItem && folderItem.builtIn !== true) {
        delete folders[parent]
        internal = internal.filter((x) => x !== parent)
        external = external.filter((x) => x !== parent)
        const { [parent]: _removed, ...rest } = userFolders
        userFolders = rest
      }

      commit({
        ...layout,
        internal: dest === 'internal' ? list : internal,
        external: dest === 'external' ? list : external,
        folders,
        userFolders,
      })
    },
    [layout, itemMap],
  )

  /**
   * Stack `draggedAppId` onto `targetAppId` to create a new user folder.
   * The new folder takes the target's section + slot, with both apps inside
   * (target first, dragged second — matches iOS behaviour).
   */
  const createFolderFromStack = useCallback(
    (targetAppId: string, draggedAppId: string) => {
      if (targetAppId === draggedAppId) return
      const target = itemMap.get(targetAppId)
      const dragged = itemMap.get(draggedAppId)
      if (!target || !dragged) return
      if (target.kind !== 'app' || dragged.kind !== 'app') return

      const targetSection = sectionOf(layout, targetAppId)
      if (!targetSection) return // target buried in folder; abort

      const folderId = `folder-${nanoid()}`
      const sectionList = [...(targetSection === 'internal' ? layout.internal : layout.external)]
      const targetIdx = sectionList.indexOf(targetAppId)
      if (targetIdx === -1) return
      // replace target with new folder id
      sectionList.splice(targetIdx, 1, folderId)
      // remove dragged from wherever it was
      const cleaned = removeFromAll(
        { ...layout, [targetSection]: sectionList } as AppLayoutV2,
        draggedAppId,
      )

      commit({
        ...cleaned,
        folders: {
          ...cleaned.folders,
          [folderId]: [targetAppId, draggedAppId],
        },
        userFolders: {
          ...cleaned.userFolders,
          [folderId]: { name: '新資料夾', icon: '📁', color: '#89dceb' },
        },
      })
      return folderId
    },
    [layout, itemMap],
  )

  /**
   * Patch folder metadata (name / description / icon / color). Works for
   * both user folders and built-in ones — built-in defaults stay in apps.ts,
   * the patch lives in `userFolders` and overrides on read.
   */
  const updateFolder = useCallback(
    (
      folderId: string,
      patch: { name?: string; description?: string; icon?: string; color?: string },
    ) => {
      const folder = itemMap.get(folderId)
      if (!folder || folder.kind !== 'folder') return
      const cleaned: typeof patch = {}
      if (patch.name !== undefined) cleaned.name = patch.name.trim() || '未命名資料夾'
      if (patch.description !== undefined) cleaned.description = patch.description.trim()
      if (patch.icon !== undefined) cleaned.icon = patch.icon
      if (patch.color !== undefined) cleaned.color = patch.color
      commit({
        ...layout,
        userFolders: {
          ...layout.userFolders,
          [folderId]: {
            ...(layout.userFolders[folderId] ?? {}),
            ...cleaned,
          },
        },
      })
    },
    [layout, itemMap],
  )

  /** Back-compat alias — old call sites use renameFolder(id, name). */
  const renameFolder = useCallback(
    (folderId: string, name: string) => updateFolder(folderId, { name }),
    [updateFolder],
  )

  const hide = useCallback(
    (id: string) => {
      if (layout.hidden.includes(id)) return
      commit({ ...layout, hidden: [...layout.hidden, id] })
    },
    [layout],
  )

  const unhide = useCallback(
    (id: string) => {
      if (!layout.hidden.includes(id)) return
      commit({ ...layout, hidden: layout.hidden.filter((x) => x !== id) })
    },
    [layout],
  )

  return {
    layout,
    sortedInternal,
    sortedExternal,
    comingSoon,
    hiddenApps,
    flatApps,
    getFolderChildren,
    getItem,
    reorderTopLevel,
    reorderInFolder,
    dropIntoFolder,
    popFromFolder,
    createFolderFromStack,
    renameFolder,
    updateFolder,
    hide,
    unhide,
  }
}

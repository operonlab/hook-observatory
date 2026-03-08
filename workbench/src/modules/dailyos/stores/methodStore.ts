import { create } from 'zustand'
import { configApi, methodApi, planApi } from '../api'
import type { DailyPlan, Method, MethodConfig, MethodSelection, PlanItem } from '../types'

/**
 * Deep merge method.config with selection.overrides to produce the effective config.
 * Overrides take precedence; arrays are replaced (not concatenated).
 */
function deepMerge<T extends Record<string, unknown>>(base: T, overrides: Partial<T>): T {
  const result = { ...base } as Record<string, unknown>
  for (const key of Object.keys(overrides)) {
    const baseVal = result[key]
    const overVal = (overrides as Record<string, unknown>)[key]
    if (
      overVal !== null &&
      typeof overVal === 'object' &&
      !Array.isArray(overVal) &&
      baseVal !== null &&
      typeof baseVal === 'object' &&
      !Array.isArray(baseVal)
    ) {
      result[key] = deepMerge(
        baseVal as Record<string, unknown>,
        overVal as Record<string, unknown>,
      )
    } else {
      result[key] = overVal
    }
  }
  return result as T
}

function buildEffectiveConfig(
  method: Method | null,
  selection: MethodSelection | null,
): MethodConfig | null {
  if (!method) return null
  const base = method.config || {}
  if (!selection?.overrides) return base
  return deepMerge(base, selection.overrides) as MethodConfig
}

interface MethodStore {
  // Active method
  activeMethod: Method | null
  activeSelection: MethodSelection | null
  effectiveConfig: MethodConfig | null

  // Today's plan
  todayPlan: DailyPlan | null
  planItems: PlanItem[]

  // Methods list (for MethodsPage)
  methods: Method[]
  methodsLoading: boolean

  // Loading states
  loading: boolean
  error: string | null

  // Actions
  fetchActiveMethod: () => Promise<void>
  fetchTodayPlan: () => Promise<void>
  fetchMethods: (includePresets?: boolean) => Promise<void>
  switchMethod: (methodId: string, overrides?: Record<string, unknown>) => Promise<void>
  toggleItem: (itemId: string) => void
  moveRight: (itemId: string) => void
  moveLeft: (itemId: string) => void
  transitionPlan: (status: string) => Promise<void>
  updatePlanItems: (items: PlanItem[]) => Promise<void>
  reset: () => void
}

const initialState = {
  activeMethod: null,
  activeSelection: null,
  effectiveConfig: null,
  todayPlan: null,
  planItems: [],
  methods: [],
  methodsLoading: false,
  loading: false,
  error: null,
}

export const useMethodStore = create<MethodStore>()((set, get) => ({
  ...initialState,

  fetchActiveMethod: async () => {
    set({ loading: true, error: null })
    try {
      const selection = await configApi.getActive().catch(() => null)
      const method = selection?.method || null
      set({
        activeSelection: selection,
        activeMethod: method,
        effectiveConfig: buildEffectiveConfig(method, selection),
      })
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to fetch active method' })
    } finally {
      set({ loading: false })
    }
  },

  fetchTodayPlan: async () => {
    set({ loading: true, error: null })
    try {
      const plan = await planApi.today().catch(() => null)
      set({
        todayPlan: plan,
        planItems: plan?.items || [],
      })
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to fetch today plan' })
    } finally {
      set({ loading: false })
    }
  },

  fetchMethods: async (includePresets = true) => {
    set({ methodsLoading: true, error: null })
    try {
      const result = await methodApi.listAll({ include_presets: includePresets, page_size: 50 })
      set({ methods: result.items })
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to fetch methods' })
    } finally {
      set({ methodsLoading: false })
    }
  },

  switchMethod: async (methodId: string, overrides?: Record<string, unknown>) => {
    set({ loading: true, error: null })
    try {
      const selection = await configApi.switchMethod({ method_id: methodId, overrides })
      const method = selection?.method || null
      set({
        activeSelection: selection,
        activeMethod: method,
        effectiveConfig: buildEffectiveConfig(method, selection),
      })
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to switch method' })
    } finally {
      set({ loading: false })
    }
  },

  toggleItem: (itemId: string) => {
    const { todayPlan, planItems } = get()
    if (!todayPlan) return

    const updatedItems = planItems.map((i) =>
      i.id === itemId
        ? { ...i, status: (i.status === 'done' ? 'pending' : 'done') as PlanItem['status'] }
        : i,
    )

    // Optimistic update
    set({ planItems: updatedItems, todayPlan: { ...todayPlan, items: updatedItems } })

    // Persist to server, revert on error
    planApi.update(todayPlan.id, { items: updatedItems }).catch(() => {
      set({ planItems: todayPlan.items, todayPlan })
    })
  },

  moveRight: (itemId: string) => {
    const { todayPlan, planItems } = get()
    if (!todayPlan) return

    const item = planItems.find((i) => i.id === itemId)
    if (!item) return

    // 3-state kanban: todo (pending) -> doing (category=doing) -> done
    let updatedItems: PlanItem[]
    if (item.category === 'doing') {
      updatedItems = planItems.map((i) =>
        i.id === itemId
          ? { ...i, status: 'done' as PlanItem['status'], category: undefined }
          : i,
      )
    } else {
      updatedItems = planItems.map((i) =>
        i.id === itemId ? { ...i, category: 'doing' } : i,
      )
    }

    set({ planItems: updatedItems, todayPlan: { ...todayPlan, items: updatedItems } })
    planApi.update(todayPlan.id, { items: updatedItems }).catch(() => {
      set({ planItems: todayPlan.items, todayPlan })
    })
  },

  moveLeft: (itemId: string) => {
    const { todayPlan, planItems } = get()
    if (!todayPlan) return

    // doing -> todo: remove the "doing" category
    const updatedItems = planItems.map((i) =>
      i.id === itemId ? { ...i, category: undefined } : i,
    )

    set({ planItems: updatedItems, todayPlan: { ...todayPlan, items: updatedItems } })
    planApi.update(todayPlan.id, { items: updatedItems }).catch(() => {
      set({ planItems: todayPlan.items, todayPlan })
    })
  },

  transitionPlan: async (status: string) => {
    const { todayPlan } = get()
    if (!todayPlan) return
    try {
      const updated = await planApi.transition(todayPlan.id, status)
      set({ todayPlan: updated, planItems: updated.items })
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to transition plan' })
    }
  },

  updatePlanItems: async (items: PlanItem[]) => {
    const { todayPlan } = get()
    if (!todayPlan) return
    set({ planItems: items, todayPlan: { ...todayPlan, items } })
    try {
      await planApi.update(todayPlan.id, { items })
    } catch (err) {
      // Revert on error
      set({ planItems: todayPlan.items, todayPlan })
      set({ error: err instanceof Error ? err.message : 'Failed to update plan items' })
    }
  },

  reset: () => set(initialState),
}))


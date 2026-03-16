import { create } from 'zustand'
import { configApi, methodApi, planApi, recurringApi, spanApi, taskGroupApi } from '../api'
import type {
  ActivitySpan,
  ActivitySpanCreate,
  ActivitySpanUpdate,
  DailyPlan,
  LayoutType,
  Method,
  MethodConfig,
  MethodSelection,
  PlanItem,
  RecurringItem,
  RecurringItemCreate,
  RecurringItemUpdate,
  TaskGroup,
  TaskGroupCreate,
  TaskGroupUpdate,
} from '../types'

/**
 * Merge configs from all active selections into a composite config.
 * Primary selection takes precedence; secondary selections fill gaps.
 */
function buildCompositeConfig(selections: MethodSelection[]): MethodConfig {
  if (selections.length === 0) return {}
  const primary = selections[0]?.method?.config || {}
  const overrides = selections[0]?.overrides || {}
  const composite: MethodConfig = { ...primary, ...overrides }

  for (let i = 1; i < selections.length; i++) {
    const cfg = {
      ...(selections[i]?.method?.config || {}),
      ...(selections[i]?.overrides || {}),
    }
    if (cfg.frog && !composite.frog) composite.frog = cfg.frog
    if (cfg.time_awareness && !composite.time_awareness)
      composite.time_awareness = cfg.time_awareness
    if (cfg.review_cycle) {
      composite.review_cycle = { ...composite.review_cycle }
      for (const [k, v] of Object.entries(cfg.review_cycle)) {
        if (!(k in (composite.review_cycle || {}))) {
          ;(composite.review_cycle as Record<string, unknown>)[k] = v
        }
      }
    }
    if (cfg.categories && !composite.categories) composite.categories = cfg.categories
    if (cfg.completion_rule && !composite.completion_rule)
      composite.completion_rule = cfg.completion_rule
    if (cfg.overflow && !composite.overflow) composite.overflow = cfg.overflow
    if (cfg.ui_hints) {
      composite.ui_hints = { ...composite.ui_hints }
      for (const [k, v] of Object.entries(cfg.ui_hints)) {
        if (!(k in (composite.ui_hints || {}))) {
          ;(composite.ui_hints as Record<string, unknown>)[k] = v
        }
      }
    }
  }
  return composite
}

interface MethodStore {
  // Active selections (supports composite methods)
  activeSelections: MethodSelection[]
  primaryMethod: Method | null
  layoutType: LayoutType
  compositeConfig: MethodConfig

  // Current plan (any date)
  currentDate: string | null
  currentPlan: DailyPlan | null
  planItems: PlanItem[]

  // Methods list (for MethodsPage)
  methods: Method[]
  methodsLoading: boolean

  // Recurring items
  recurringItems: RecurringItem[]
  recurringLoading: boolean

  // Task groups
  taskGroups: TaskGroup[]
  taskGroupsLoading: boolean
  hiddenGroupIds: Set<string>

  // Loading states
  loading: boolean
  planLoading: boolean
  error: string | null

  // Actions — data fetching
  fetchActiveMethod: () => Promise<void>
  fetchPlan: (date?: string) => Promise<void>
  fetchMethods: (includePresets?: boolean) => Promise<void>
  activateMethod: (methodId: string, overrides?: Record<string, unknown>) => Promise<void>

  // Actions — layout control
  setPrimary: (methodId: string) => void

  // Actions — plan item mutations (optimistic + rollback)
  addItem: (title: string, extra?: Partial<PlanItem>) => void
  removeItem: (itemId: string) => void
  editItem: (itemId: string, updates: Partial<PlanItem>) => void
  reorderItem: (itemId: string, direction: 'up' | 'down') => void
  reorderItems: (orderedIds: string[]) => void
  toggleItem: (itemId: string) => void
  assignCategory: (itemId: string, categoryId: string) => void
  scheduleItem: (itemId: string, time: string | undefined) => void
  moveRight: (itemId: string) => void
  moveLeft: (itemId: string) => void

  // Actions — recurring items
  fetchRecurringItems: () => Promise<void>
  addRecurringItem: (data: RecurringItemCreate) => Promise<void>
  updateRecurringItem: (id: string, data: RecurringItemUpdate) => Promise<void>
  removeRecurringItem: (id: string) => Promise<void>

  // Actions — task groups
  fetchTaskGroups: () => Promise<void>
  addTaskGroup: (data: TaskGroupCreate) => Promise<void>
  updateTaskGroup: (id: string, data: TaskGroupUpdate) => Promise<void>
  removeTaskGroup: (id: string) => Promise<void>
  toggleGroupVisibility: (groupId: string) => void

  // Activity spans
  activitySpans: ActivitySpan[]
  spansLoading: boolean
  fetchActivitySpans: (dateFrom?: string, dateTo?: string) => Promise<void>
  addActivitySpan: (data: ActivitySpanCreate) => Promise<void>
  updateActivitySpan: (id: string, data: ActivitySpanUpdate) => Promise<void>
  removeActivitySpan: (id: string) => Promise<void>

  // Actions — plan lifecycle
  transitionPlan: (status: string) => Promise<void>
  completeReview: (reflection: string) => Promise<void>
  updatePlanItems: (items: PlanItem[]) => Promise<void>

  reset: () => void
}

function loadHiddenGroupIds(): Set<string> {
  try {
    const raw = localStorage.getItem('dailyos:hiddenGroupIds')
    return raw ? new Set(JSON.parse(raw)) : new Set()
  } catch {
    return new Set()
  }
}

function saveHiddenGroupIds(ids: Set<string>) {
  localStorage.setItem('dailyos:hiddenGroupIds', JSON.stringify([...ids]))
}

const initialState = {
  activeSelections: [] as MethodSelection[],
  primaryMethod: null as Method | null,
  layoutType: 'list' as LayoutType,
  compositeConfig: {} as MethodConfig,
  currentDate: null as string | null,
  currentPlan: null as DailyPlan | null,
  planItems: [] as PlanItem[],
  methods: [] as Method[],
  methodsLoading: false,
  recurringItems: [] as RecurringItem[],
  recurringLoading: false,
  taskGroups: [] as TaskGroup[],
  taskGroupsLoading: false,
  hiddenGroupIds: loadHiddenGroupIds(),
  activitySpans: [] as ActivitySpan[],
  spansLoading: false,
  loading: false,
  planLoading: false,
  error: null as string | null,
}

export const useMethodStore = create<MethodStore>()((set, get) => ({
  ...initialState,

  fetchActiveMethod: async () => {
    set({ loading: true, error: null })
    try {
      const selections = await configApi.getActive().catch(() => [] as MethodSelection[])
      const primary = selections.length > 0 ? selections[0]?.method || null : null
      set({
        activeSelections: selections,
        primaryMethod: primary,
        layoutType: primary?.layout_type || 'list',
        compositeConfig: buildCompositeConfig(selections),
      })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to fetch active method',
      })
    } finally {
      set({ loading: false })
    }
  },

  fetchPlan: async (date?: string) => {
    set({ planLoading: true, error: null })
    try {
      const plan = date
        ? await planApi.forDate(date).catch(() => null)
        : await planApi.today().catch(() => null)
      set({
        currentDate: date || plan?.plan_date || null,
        currentPlan: plan,
        planItems: plan?.items || [],
      })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to fetch plan',
      })
    } finally {
      set({ planLoading: false })
    }
  },

  fetchMethods: async (includePresets = true) => {
    set({ methodsLoading: true, error: null })
    try {
      const result = await methodApi.listAll({
        include_presets: includePresets,
        page_size: 50,
      })
      set({ methods: result.items })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to fetch methods',
      })
    } finally {
      set({ methodsLoading: false })
    }
  },

  setPrimary: (methodId: string) => {
    const { activeSelections } = get()
    const sel = activeSelections.find((s) => s.method_id === methodId)
    if (!sel?.method) return
    const method = sel.method
    // Reorder: move this selection to front so it becomes primary
    const reordered = [sel, ...activeSelections.filter((s) => s.id !== sel.id)]
    set({
      activeSelections: reordered,
      primaryMethod: method,
      layoutType: method.layout_type || 'list',
      compositeConfig: buildCompositeConfig(reordered),
    })
  },

  activateMethod: async (methodId: string, overrides?: Record<string, unknown>) => {
    set({ loading: true, error: null })
    try {
      await configApi.activate({ method_id: methodId, overrides })
      await get().fetchActiveMethod()
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to activate method',
        loading: false,
      })
    }
  },

  addItem: (title: string, extra?: Partial<PlanItem>) => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const maxOrder = planItems.reduce((max, i) => Math.max(max, i.sort_order), 0)
    const newItem: PlanItem = {
      id: crypto.randomUUID(),
      title,
      status: 'pending',
      sort_order: maxOrder + 1,
      ...extra,
    }
    const updatedItems = [...planItems, newItem]
    set({ planItems: updatedItems, currentPlan: { ...currentPlan, items: updatedItems } })
    planApi.update(currentPlan.id, { items: updatedItems }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  removeItem: (itemId: string) => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const updatedItems = planItems.filter((i) => i.id !== itemId)
    set({ planItems: updatedItems, currentPlan: { ...currentPlan, items: updatedItems } })
    planApi.update(currentPlan.id, { items: updatedItems }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  editItem: (itemId: string, updates: Partial<PlanItem>) => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const updatedItems = planItems.map((i) => (i.id === itemId ? { ...i, ...updates } : i))
    set({ planItems: updatedItems, currentPlan: { ...currentPlan, items: updatedItems } })
    planApi.update(currentPlan.id, { items: updatedItems }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  reorderItem: (itemId: string, direction: 'up' | 'down') => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const sorted = [...planItems].sort((a, b) => a.sort_order - b.sort_order)
    const idx = sorted.findIndex((i) => i.id === itemId)
    if (idx < 0) return
    const swapIdx = direction === 'up' ? idx - 1 : idx + 1
    if (swapIdx < 0 || swapIdx >= sorted.length) return
    const temp = sorted[idx].sort_order
    sorted[idx] = { ...sorted[idx], sort_order: sorted[swapIdx].sort_order }
    sorted[swapIdx] = { ...sorted[swapIdx], sort_order: temp }
    set({ planItems: sorted, currentPlan: { ...currentPlan, items: sorted } })
    planApi.update(currentPlan.id, { items: sorted }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  reorderItems: (orderedIds: string[]) => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const updatedItems = planItems.map((item) => {
      const newOrder = orderedIds.indexOf(item.id)
      return newOrder >= 0 ? { ...item, sort_order: newOrder } : item
    })
    set({ planItems: updatedItems, currentPlan: { ...currentPlan, items: updatedItems } })
    planApi.update(currentPlan.id, { items: updatedItems }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  toggleItem: (itemId: string) => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const updatedItems = planItems.map((i) =>
      i.id === itemId
        ? {
            ...i,
            status: (i.status === 'done' ? 'pending' : 'done') as PlanItem['status'],
          }
        : i,
    )
    set({
      planItems: updatedItems,
      currentPlan: { ...currentPlan, items: updatedItems },
    })
    planApi.update(currentPlan.id, { items: updatedItems }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  assignCategory: (itemId: string, categoryId: string) => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const updatedItems = planItems.map((i) =>
      i.id === itemId ? { ...i, category: categoryId || undefined } : i,
    )
    set({
      planItems: updatedItems,
      currentPlan: { ...currentPlan, items: updatedItems },
    })
    planApi.update(currentPlan.id, { items: updatedItems }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  scheduleItem: (itemId: string, time: string | undefined) => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const updatedItems = planItems.map((i) =>
      i.id === itemId ? { ...i, scheduled_time: time } : i,
    )
    set({ planItems: updatedItems, currentPlan: { ...currentPlan, items: updatedItems } })
    planApi.update(currentPlan.id, { items: updatedItems }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  moveRight: (itemId: string) => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const item = planItems.find((i) => i.id === itemId)
    if (!item) return
    let updatedItems: PlanItem[]
    if (item.category === 'doing') {
      updatedItems = planItems.map((i) =>
        i.id === itemId ? { ...i, status: 'done' as PlanItem['status'], category: undefined } : i,
      )
    } else {
      updatedItems = planItems.map((i) => (i.id === itemId ? { ...i, category: 'doing' } : i))
    }
    set({
      planItems: updatedItems,
      currentPlan: { ...currentPlan, items: updatedItems },
    })
    planApi.update(currentPlan.id, { items: updatedItems }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  moveLeft: (itemId: string) => {
    const { currentPlan, planItems } = get()
    if (!currentPlan) return
    const item = planItems.find((i) => i.id === itemId)
    if (!item) return
    let updatedItems: PlanItem[]
    if (item.status === 'done') {
      // Undo done → back to doing
      updatedItems = planItems.map((i) =>
        i.id === itemId ? { ...i, status: 'pending' as PlanItem['status'], category: 'doing' } : i,
      )
    } else if (item.category === 'doing') {
      // Doing → todo (remove category)
      updatedItems = planItems.map((i) => (i.id === itemId ? { ...i, category: undefined } : i))
    } else {
      updatedItems = planItems.map((i) => (i.id === itemId ? { ...i, category: undefined } : i))
    }
    set({ planItems: updatedItems, currentPlan: { ...currentPlan, items: updatedItems } })
    planApi.update(currentPlan.id, { items: updatedItems }).catch((err) => {
      console.error('Operation failed:', err)
      set({ planItems: currentPlan.items, currentPlan })
    })
  },

  fetchRecurringItems: async () => {
    set({ recurringLoading: true })
    try {
      const items = await recurringApi.list()
      set({ recurringItems: items })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to fetch recurring items',
      })
    } finally {
      set({ recurringLoading: false })
    }
  },

  addRecurringItem: async (data: RecurringItemCreate) => {
    try {
      const item = await recurringApi.create(data)
      set({ recurringItems: [...get().recurringItems, item] })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to add recurring item',
      })
    }
  },

  updateRecurringItem: async (id: string, data: RecurringItemUpdate) => {
    const prev = get().recurringItems
    set({
      recurringItems: prev.map((i) => (i.id === id ? { ...i, ...data } : i)),
    })
    try {
      const updated = await recurringApi.update(id, data)
      set({
        recurringItems: get().recurringItems.map((i) => (i.id === id ? updated : i)),
      })
    } catch (err) {
      set({
        recurringItems: prev,
        error: err instanceof Error ? err.message : 'Failed to update recurring item',
      })
    }
  },

  removeRecurringItem: async (id: string) => {
    const prev = get().recurringItems
    set({ recurringItems: prev.filter((i) => i.id !== id) })
    try {
      await recurringApi.remove(id)
    } catch (err) {
      set({
        recurringItems: prev,
        error: err instanceof Error ? err.message : 'Failed to remove recurring item',
      })
    }
  },

  transitionPlan: async (status: string) => {
    const { currentPlan } = get()
    if (!currentPlan) return
    try {
      const updated = await planApi.transition(currentPlan.id, status)
      set({ currentPlan: updated, planItems: updated.items })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to transition plan',
      })
    }
  },

  completeReview: async (reflection: string) => {
    const { currentPlan } = get()
    if (!currentPlan) return
    try {
      await planApi.update(currentPlan.id, { reflection })
      const updated = await planApi.transition(currentPlan.id, 'completed')
      set({ currentPlan: updated, planItems: updated.items })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to complete review',
      })
    }
  },

  updatePlanItems: async (items: PlanItem[]) => {
    const { currentPlan } = get()
    if (!currentPlan) return
    set({ planItems: items, currentPlan: { ...currentPlan, items } })
    try {
      await planApi.update(currentPlan.id, { items })
    } catch (err) {
      set({ planItems: currentPlan.items, currentPlan })
      set({
        error: err instanceof Error ? err.message : 'Failed to update plan items',
      })
    }
  },

  fetchTaskGroups: async () => {
    set({ taskGroupsLoading: true })
    try {
      const groups = await taskGroupApi.list()
      set({ taskGroups: groups })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to fetch task groups',
      })
    } finally {
      set({ taskGroupsLoading: false })
    }
  },

  addTaskGroup: async (data: TaskGroupCreate) => {
    try {
      const group = await taskGroupApi.create(data)
      set({ taskGroups: [...get().taskGroups, group] })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to create task group',
      })
    }
  },

  updateTaskGroup: async (id: string, data: TaskGroupUpdate) => {
    const prev = get().taskGroups
    set({ taskGroups: prev.map((g) => (g.id === id ? { ...g, ...data } : g)) })
    try {
      const updated = await taskGroupApi.update(id, data)
      set({ taskGroups: get().taskGroups.map((g) => (g.id === id ? updated : g)) })
    } catch (err) {
      set({
        taskGroups: prev,
        error: err instanceof Error ? err.message : 'Failed to update task group',
      })
    }
  },

  removeTaskGroup: async (id: string) => {
    const prev = get().taskGroups
    set({ taskGroups: prev.filter((g) => g.id !== id) })
    try {
      await taskGroupApi.remove(id)
    } catch (err) {
      set({
        taskGroups: prev,
        error: err instanceof Error ? err.message : 'Failed to remove task group',
      })
    }
  },

  toggleGroupVisibility: (groupId: string) => {
    const hidden = new Set(get().hiddenGroupIds)
    if (hidden.has(groupId)) {
      hidden.delete(groupId)
    } else {
      hidden.add(groupId)
    }
    saveHiddenGroupIds(hidden)
    set({ hiddenGroupIds: hidden })
  },

  fetchActivitySpans: async (dateFrom?: string, dateTo?: string) => {
    set({ spansLoading: true })
    try {
      const spans = await spanApi.list({ date_from: dateFrom, date_to: dateTo })
      set({ activitySpans: spans })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to fetch activity spans',
      })
    } finally {
      set({ spansLoading: false })
    }
  },

  addActivitySpan: async (data: ActivitySpanCreate) => {
    try {
      const span = await spanApi.create(data)
      set({ activitySpans: [...get().activitySpans, span] })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to add activity span',
      })
    }
  },

  updateActivitySpan: async (id: string, data: ActivitySpanUpdate) => {
    const prev = get().activitySpans
    set({
      activitySpans: prev.map((s) => (s.id === id ? { ...s, ...data } : s)),
    })
    try {
      const updated = await spanApi.update(id, data)
      set({
        activitySpans: get().activitySpans.map((s) => (s.id === id ? updated : s)),
      })
    } catch (err) {
      set({
        activitySpans: prev,
        error: err instanceof Error ? err.message : 'Failed to update activity span',
      })
    }
  },

  removeActivitySpan: async (id: string) => {
    const prev = get().activitySpans
    set({ activitySpans: prev.filter((s) => s.id !== id) })
    try {
      await spanApi.remove(id)
    } catch (err) {
      set({
        activitySpans: prev,
        error: err instanceof Error ? err.message : 'Failed to remove activity span',
      })
    }
  },

  reset: () => set(initialState),
}))

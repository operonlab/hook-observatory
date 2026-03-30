import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import type { WidgetInstance } from '../types/widget'

const STORAGE_KEY = 'dashboard-widgets'

function loadWidgets(): WidgetInstance[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveWidgets(widgets: WidgetInstance[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(widgets))
  } catch {
    // QuotaExceededError in private browsing — ignore
  }
}

interface DashboardState {
  widgets: WidgetInstance[]
  editing: boolean

  setEditing: (v: boolean) => void
  addWidget: (widget: WidgetInstance) => void
  removeWidget: (id: string) => void
  updateLayout: (id: string, layout: WidgetInstance['layout']) => void
  updateAllLayouts: (
    layouts: Array<{ i: string; x: number; y: number; w: number; h: number }>,
  ) => void
}

export const useDashboardStore = create<DashboardState>()(
  devtools(
    (set, get) => ({
      widgets: loadWidgets(),
      editing: false,

      setEditing: (v) => set({ editing: v }),

      addWidget: (widget) => {
        const next = [...get().widgets, widget]
        saveWidgets(next)
        set({ widgets: next })
      },

      removeWidget: (id) => {
        const next = get().widgets.filter((w) => w.id !== id)
        saveWidgets(next)
        set({ widgets: next })
      },

      updateLayout: (id, layout) => {
        const next = get().widgets.map((w) => (w.id === id ? { ...w, layout } : w))
        saveWidgets(next)
        set({ widgets: next })
      },

      updateAllLayouts: (layouts) => {
        const next = get().widgets.map((w) => {
          const l = layouts.find((item) => item.i === w.id)
          return l ? { ...w, layout: { x: l.x, y: l.y, w: l.w, h: l.h } } : w
        })
        saveWidgets(next)
        set({ widgets: next })
      },
    }),
    { name: 'dashboardStore' },
  ),
)

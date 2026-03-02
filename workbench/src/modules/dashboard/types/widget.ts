import type React from 'react'

/** Size categories for widget defaults */
export type WidgetSize = 'small' | 'medium' | 'large' | 'wide' | 'tall'

/** Props injected into every widget by WidgetShell */
export interface WidgetProps {
  containerWidth: number
  containerHeight: number
  instanceId: string
}

/** Manifest describing a widget type in the registry */
export interface WidgetManifest {
  /** Unique widget type id, e.g. "clock", "notes" */
  id: string
  /** Display name */
  name: string
  /** Short description */
  description: string
  /** Emoji or icon string */
  icon: string
  /** Default grid size category */
  defaultSize: WidgetSize
  /** Default grid dimensions { w, h } in grid units */
  defaultLayout: { w: number; h: number }
  /** Minimum grid dimensions */
  minLayout?: { w: number; h: number }
  /** Maximum grid dimensions */
  maxLayout?: { w: number; h: number }
  /** Lazy-loaded component */
  component: () => Promise<{ default: React.ComponentType<WidgetProps> }>
  /** Optional: which modules this widget is related to */
  modules?: string[]
  /** Optional: tags for filtering in gallery */
  tags?: string[]
}

/** A placed widget instance on the dashboard */
export interface WidgetInstance {
  /** Unique instance id (UUID) */
  id: string
  /** References WidgetManifest.id */
  widgetId: string
  /** react-grid-layout item */
  layout: {
    x: number
    y: number
    w: number
    h: number
  }
}

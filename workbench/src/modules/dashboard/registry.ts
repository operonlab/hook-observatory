import type { WidgetManifest } from './types/widget'

const widgetRegistry = new Map<string, WidgetManifest>()

export function registerWidget(manifest: WidgetManifest): void {
  widgetRegistry.set(manifest.id, manifest)
}

export function getWidget(id: string): WidgetManifest | undefined {
  return widgetRegistry.get(id)
}

export function getAllWidgets(): WidgetManifest[] {
  return Array.from(widgetRegistry.values())
}

// --- Built-in placeholder widgets ---

registerWidget({
  id: 'clock',
  name: '時鐘',
  description: '顯示目前時間',
  icon: '🕐',
  defaultSize: 'small',
  defaultLayout: { w: 2, h: 2 },
  minLayout: { w: 2, h: 2 },
  component: () =>
    import('./components/PlaceholderWidget').then((m) => ({
      default: m.ClockWidget,
    })),
  tags: ['utility'],
})

registerWidget({
  id: 'notes',
  name: '便條紙',
  description: '快速筆記小工具',
  icon: '📝',
  defaultSize: 'medium',
  defaultLayout: { w: 3, h: 3 },
  minLayout: { w: 2, h: 2 },
  component: () =>
    import('./components/PlaceholderWidget').then((m) => ({
      default: m.NotesWidget,
    })),
  tags: ['utility'],
})

registerWidget({
  id: 'quick-links',
  name: '快速連結',
  description: '常用應用快捷入口',
  icon: '🔗',
  defaultSize: 'wide',
  defaultLayout: { w: 4, h: 2 },
  minLayout: { w: 3, h: 2 },
  component: () =>
    import('./components/PlaceholderWidget').then((m) => ({
      default: m.QuickLinksWidget,
    })),
  tags: ['navigation'],
})

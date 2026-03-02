import { Check, Pencil, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { ResponsiveGridLayout, useContainerWidth } from 'react-grid-layout'
import { getWidget } from '../registry'
import { useDashboardStore } from '../stores/dashboard'
import WidgetGallery from './WidgetGallery'
import WidgetShell from './WidgetShell'
import 'react-grid-layout/css/styles.css'

export default function DashboardCanvas() {
  const { widgets, editing, setEditing, removeWidget, updateAllLayouts } = useDashboardStore()
  const [showGallery, setShowGallery] = useState(false)
  const { width, containerRef, mounted } = useContainerWidth()

  const layouts = useMemo(() => {
    const items = widgets.map((w) => {
      const manifest = getWidget(w.widgetId)
      return {
        i: w.id,
        x: w.layout.x,
        y: w.layout.y,
        w: w.layout.w,
        h: w.layout.h,
        minW: manifest?.minLayout?.w ?? 1,
        minH: manifest?.minLayout?.h ?? 1,
        maxW: manifest?.maxLayout?.w,
        maxH: manifest?.maxLayout?.h,
        static: !editing,
      }
    })
    return { lg: items, md: items, sm: items, xs: items }
  }, [widgets, editing])

  function handleLayoutChange(
    layout: Array<{ i: string; x: number; y: number; w: number; h: number }>,
  ) {
    if (!editing) return
    updateAllLayouts(layout)
  }

  return (
    <div ref={containerRef} className="min-h-full" style={{ backgroundColor: '#1a1b2e' }}>
      {/* Toolbar */}
      <div
        className="sticky top-0 z-10 flex items-center justify-between px-5 py-3"
        style={{
          background: 'rgba(26, 27, 46, 0.9)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
        }}
      >
        <div className="flex items-center gap-2">
          <span
            className="text-xs uppercase tracking-wider"
            style={{
              color: 'rgba(255, 255, 255, 0.3)',
              letterSpacing: '0.15em',
            }}
          >
            Dashboard
          </span>
          {widgets.length > 0 && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: 'rgba(255, 255, 255, 0.06)',
                color: 'rgba(255, 255, 255, 0.3)',
              }}
            >
              {widgets.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setShowGallery(true)}
            className="flex h-7 items-center gap-1.5 px-2.5 text-xs rounded transition-colors"
            style={{
              backgroundColor: 'rgba(255, 255, 255, 0.06)',
              color: 'rgba(255, 255, 255, 0.55)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.1)'
              e.currentTarget.style.color = 'rgba(255, 255, 255, 0.8)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)'
              e.currentTarget.style.color = 'rgba(255, 255, 255, 0.55)'
            }}
          >
            <Plus size={13} />
            新增
          </button>
          <button
            type="button"
            onClick={() => setEditing(!editing)}
            className="flex h-7 items-center gap-1.5 px-2.5 text-xs rounded transition-colors"
            style={{
              backgroundColor: editing ? 'rgba(180, 190, 254, 0.12)' : 'rgba(255, 255, 255, 0.06)',
              color: editing ? 'var(--accent)' : 'rgba(255, 255, 255, 0.55)',
            }}
            onMouseEnter={(e) => {
              if (!editing) {
                e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.1)'
              }
            }}
            onMouseLeave={(e) => {
              if (!editing) {
                e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)'
              }
            }}
          >
            {editing ? <Check size={13} /> : <Pencil size={13} />}
            {editing ? '完成' : '編輯'}
          </button>
        </div>
      </div>

      {/* Grid */}
      {widgets.length === 0 ? (
        <div className="flex flex-col items-center justify-center pt-32 gap-4">
          <div
            className="flex h-16 w-16 items-center justify-center rounded-xl text-2xl"
            style={{ backgroundColor: 'rgba(255, 255, 255, 0.04)' }}
          >
            📐
          </div>
          <p className="text-sm" style={{ color: 'rgba(255, 255, 255, 0.35)' }}>
            還沒有 Widget
          </p>
          <button
            type="button"
            onClick={() => setShowGallery(true)}
            className="flex items-center gap-1.5 px-4 py-2 text-xs rounded transition-colors"
            style={{
              backgroundColor: 'rgba(180, 190, 254, 0.1)',
              color: 'var(--accent)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(180, 190, 254, 0.18)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(180, 190, 254, 0.1)'
            }}
          >
            <Plus size={14} />
            新增第一個 Widget
          </button>
        </div>
      ) : (
        mounted && (
          <div className="px-4 py-2">
            <ResponsiveGridLayout
              className="layout"
              width={width}
              layouts={layouts}
              breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 0 }}
              cols={{ lg: 12, md: 8, sm: 4, xs: 2 }}
              rowHeight={80}
              isDraggable={editing}
              isResizable={editing}
              onLayoutChange={handleLayoutChange}
              compactor="vertical"
              margin={[12, 12]}
            >
              {widgets.map((w) => {
                const manifest = getWidget(w.widgetId)
                if (!manifest) return <div key={w.id} />
                return (
                  <div key={w.id}>
                    <WidgetShell
                      manifest={manifest}
                      instanceId={w.id}
                      editing={editing}
                      onRemove={() => removeWidget(w.id)}
                    />
                  </div>
                )
              })}
            </ResponsiveGridLayout>
          </div>
        )
      )}

      {showGallery && <WidgetGallery onClose={() => setShowGallery(false)} />}
    </div>
  )
}

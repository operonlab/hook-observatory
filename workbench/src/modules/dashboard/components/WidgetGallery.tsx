import { Plus, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { getAllWidgets } from '../registry'
import { useDashboardStore } from '../stores/dashboard'
import type { WidgetInstance } from '../types/widget'

interface WidgetGalleryProps {
  onClose: () => void
}

export default function WidgetGallery({ onClose }: WidgetGalleryProps) {
  const addWidget = useDashboardStore((s) => s.addWidget)
  const widgets = getAllWidgets()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [onClose])

  function handleAdd(widgetId: string) {
    const manifest = widgets.find((w) => w.id === widgetId)
    if (!manifest) return

    const instance: WidgetInstance = {
      id: `${widgetId}-${Date.now()}`,
      widgetId,
      layout: {
        x: 0,
        y: Infinity, // RGL puts it at the bottom
        w: manifest.defaultLayout.w,
        h: manifest.defaultLayout.h,
      },
    }
    addWidget(instance)
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
    >
      <div
        ref={ref}
        className="w-full max-w-sm mx-4 overflow-hidden shadow-2xl"
        style={{
          backgroundColor: 'rgba(20, 20, 30, 0.98)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '8px',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.06)' }}
        >
          <span className="text-sm font-medium" style={{ color: 'rgba(255, 255, 255, 0.8)' }}>
            新增 Widget
          </span>
          <button
            type="button"
            onClick={onClose}
            className="flex h-6 w-6 items-center justify-center rounded transition-colors"
            style={{ color: 'rgba(255, 255, 255, 0.35)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'rgba(255, 255, 255, 0.7)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'rgba(255, 255, 255, 0.35)'
            }}
          >
            <X size={14} />
          </button>
        </div>

        {/* Widget list */}
        <div className="p-3 flex flex-col gap-1.5 max-h-80 overflow-y-auto">
          {widgets.map((w) => (
            <button
              type="button"
              key={w.id}
              onClick={() => handleAdd(w.id)}
              className="flex items-center gap-3 px-3 py-3 text-left transition-colors rounded"
              style={{ backgroundColor: 'transparent' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.04)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
              }}
            >
              <span
                className="flex h-9 w-9 items-center justify-center text-lg rounded"
                style={{ backgroundColor: 'rgba(255, 255, 255, 0.06)' }}
              >
                {w.icon}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium" style={{ color: 'rgba(255, 255, 255, 0.75)' }}>
                  {w.name}
                </div>
                <div className="text-[11px] mt-0.5" style={{ color: 'rgba(255, 255, 255, 0.3)' }}>
                  {w.description}
                </div>
              </div>
              <Plus size={14} style={{ color: 'rgba(255, 255, 255, 0.25)' }} />
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

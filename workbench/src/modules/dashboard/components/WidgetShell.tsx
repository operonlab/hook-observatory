import { X } from 'lucide-react'
import React, { useEffect, useRef, useState } from 'react'
import type { WidgetManifest, WidgetProps } from '../types/widget'

interface WidgetShellProps {
  manifest: WidgetManifest
  instanceId: string
  editing: boolean
  onRemove: () => void
}

class WidgetErrorBoundary extends React.Component<
  { children: React.ReactNode; name: string },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-2 p-4">
          <span className="text-sm" style={{ color: 'var(--red)' }}>
            Widget 錯誤
          </span>
          <span className="text-xs text-center" style={{ color: 'rgba(255, 255, 255, 0.35)' }}>
            {this.props.name}: {this.state.error.message}
          </span>
        </div>
      )
    }
    return this.props.children
  }
}

export default function WidgetShell({ manifest, instanceId, editing, onRemove }: WidgetShellProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [LazyComponent, setLazyComponent] = useState<React.ComponentType<WidgetProps> | null>(null)

  // Lazy load the widget component
  useEffect(() => {
    manifest.component().then((mod) => setLazyComponent(() => mod.default))
  }, [manifest])

  // ResizeObserver for container size
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        setSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        })
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full overflow-hidden"
      style={{
        backgroundColor: 'rgba(255, 255, 255, 0.03)',
        border: editing
          ? '1px dashed rgba(255, 255, 255, 0.15)'
          : '1px solid rgba(255, 255, 255, 0.06)',
        borderRadius: '8px',
      }}
    >
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-3 py-1.5"
        style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.04)' }}
      >
        <div className="flex items-center gap-1.5">
          <span className="text-xs">{manifest.icon}</span>
          <span className="text-[10px] font-medium" style={{ color: 'rgba(255, 255, 255, 0.45)' }}>
            {manifest.name}
          </span>
        </div>
        {editing && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onRemove()
            }}
            className="flex h-5 w-5 items-center justify-center rounded transition-colors"
            style={{ color: 'rgba(255, 255, 255, 0.3)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--red)'
              e.currentTarget.style.backgroundColor = 'rgba(243, 139, 168, 0.1)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'rgba(255, 255, 255, 0.3)'
              e.currentTarget.style.backgroundColor = 'transparent'
            }}
            aria-label="移除 widget"
          >
            <X size={12} />
          </button>
        )}
      </div>

      {/* Widget content */}
      <div className="h-[calc(100%-32px)]">
        <WidgetErrorBoundary name={manifest.name}>
          {LazyComponent ? (
            <LazyComponent
              containerWidth={size.width}
              containerHeight={size.height - 32}
              instanceId={instanceId}
            />
          ) : (
            <div className="flex h-full items-center justify-center">
              <div
                className="h-4 w-4 animate-spin rounded-full border border-t-transparent"
                style={{
                  borderColor: 'var(--accent)',
                  borderTopColor: 'transparent',
                }}
              />
            </div>
          )}
        </WidgetErrorBoundary>
      </div>
    </div>
  )
}

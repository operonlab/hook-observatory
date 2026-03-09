import { Copy, LayoutGrid, X, Zap } from 'lucide-react'
import type { Method } from '../types'
import LayoutPreview from './LayoutPreview'

const LAYOUT_LABELS: Record<string, string> = {
  list: '清單',
  columns: '分欄',
  timeline: '時間軸',
  grid: '矩陣',
  kanban: '看板',
}

const DIMENSION_LABELS: Record<string, string> = {
  prioritization: '優先排序',
  execution: '執行節奏',
  flow: '工作流',
  ritual: '每日儀式',
}

interface MethodCardProps {
  method: Method
  onActivate?: (method: Method) => void
  onDeactivate?: (method: Method) => void
  onClone?: (method: Method) => void
  isActive?: boolean
}

export default function MethodCard({
  method,
  onActivate,
  onDeactivate,
  onClone,
  isActive,
}: MethodCardProps) {
  const dimensions = method.config?.dimensions || []

  return (
    <div
      className="do-card p-4 do-fade-in"
      style={{
        borderColor: isActive ? 'var(--do-accent-dim)' : undefined,
      }}
    >
      {/* Layout Preview + Info */}
      <div className="flex gap-3 mb-3">
        {/* Mini layout preview */}
        <div className="w-24 shrink-0">
          <LayoutPreview layout={method.layout_type} color={method.color || '#89b4fa'} />
        </div>

        <div className="flex-1 min-w-0">
          {/* Header */}
          <div className="flex items-start justify-between gap-2 mb-1">
            <div className="flex items-center gap-1.5">
              <span className="text-base">{method.icon || '📋'}</span>
              <div>
                <h3 className="text-[13px] font-medium" style={{ color: 'var(--do-text)' }}>
                  {method.name}
                </h3>
                {method.name_zh && (
                  <span className="text-[11px]" style={{ color: 'var(--do-text-secondary)' }}>
                    {method.name_zh}
                  </span>
                )}
              </div>
            </div>
            {isActive && (
              <span
                className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-medium shrink-0"
                style={{
                  color: 'var(--do-accent)',
                  backgroundColor: 'var(--do-accent-alpha)',
                }}
              >
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full"
                  style={{
                    backgroundColor: 'var(--do-accent)',
                    animation: 'do-pulse-once 1.5s ease-in-out infinite',
                  }}
                />
                使用中
              </span>
            )}
          </div>

          {/* Description */}
          {method.description && (
            <p
              className="text-[11px] leading-relaxed line-clamp-3"
              style={{ color: 'var(--do-text-secondary)' }}
            >
              {method.description}
            </p>
          )}
        </div>
      </div>

      {/* Tags + Layout + Dimensions */}
      <div className="flex items-center gap-1.5 flex-wrap mb-3">
        <span
          className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded"
          style={{
            color: 'var(--do-accent)',
            backgroundColor: 'var(--do-accent-alpha)',
          }}
        >
          <LayoutGrid size={10} />
          {LAYOUT_LABELS[method.layout_type] || method.layout_type}
        </span>
        {dimensions.map((dim) => (
          <span
            key={dim}
            className="text-[10px] px-2 py-1 rounded"
            style={{
              color: '#89b4fa',
              backgroundColor: 'rgba(137, 180, 250, 0.12)',
            }}
          >
            {DIMENSION_LABELS[dim] || dim}
          </span>
        ))}
        {method.tags?.map((tag) => (
          <span
            key={tag}
            className="text-[10px] px-2 py-1 rounded"
            style={{
              color: 'var(--do-text-tertiary)',
              backgroundColor: 'var(--do-bg-surface)',
              border: '1px solid var(--do-border)',
            }}
          >
            {tag}
          </span>
        ))}
        {method.is_preset && (
          <span
            className="text-[10px] px-2 py-1 rounded"
            style={{
              color: '#f9e2af',
              backgroundColor: 'rgba(249, 226, 175, 0.15)',
            }}
          >
            系統預設
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2">
        {onActivate && !isActive && (
          <button
            type="button"
            onClick={() => onActivate(method)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium"
            style={{
              backgroundColor: 'var(--do-accent-alpha)',
              color: 'var(--do-accent)',
              border: '1px solid var(--do-accent-dim)',
              transition: 'background-color 150ms ease, border-color 150ms ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(203, 166, 247, 0.25)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--do-accent-alpha)'
            }}
          >
            <Zap size={12} />
            啟用
          </button>
        )}
        {onDeactivate && isActive && (
          <button
            type="button"
            onClick={() => onDeactivate(method)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium"
            style={{
              backgroundColor: 'rgba(243, 139, 168, 0.1)',
              color: '#f38ba8',
              border: '1px solid rgba(243, 139, 168, 0.25)',
              transition: 'background-color 150ms ease, border-color 150ms ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(243, 139, 168, 0.18)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(243, 139, 168, 0.1)'
            }}
          >
            <X size={12} />
            停用
          </button>
        )}
        {onClone && method.is_preset && (
          <button
            type="button"
            onClick={() => onClone(method)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium"
            style={{
              backgroundColor: 'var(--do-bg-surface)',
              color: 'var(--do-text-secondary)',
              border: '1px solid var(--do-border)',
              transition: 'background-color 150ms ease, color 150ms ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--do-border)'
              e.currentTarget.style.color = 'var(--do-text)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--do-bg-surface)'
              e.currentTarget.style.color = 'var(--do-text-secondary)'
            }}
          >
            <Copy size={12} />
            複製
          </button>
        )}
      </div>
    </div>
  )
}

import { Copy, X, Zap } from 'lucide-react'
import type { Method } from '../types'

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
      className="rounded-lg border p-4 transition-colors"
      style={{
        borderColor: isActive ? 'var(--do-accent-dim)' : 'var(--do-border)',
        backgroundColor: 'var(--do-bg-elevated)',
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-lg">{method.icon || '📋'}</span>
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
            className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0"
            style={{
              color: 'var(--do-accent)',
              backgroundColor: 'var(--do-accent-alpha)',
            }}
          >
            使用中
          </span>
        )}
      </div>

      {/* Description */}
      {method.description && (
        <p
          className="text-[12px] mb-3 leading-relaxed"
          style={{ color: 'var(--do-text-secondary)' }}
        >
          {method.description}
        </p>
      )}

      {/* Tags + Layout + Dimensions */}
      <div className="flex items-center gap-1.5 flex-wrap mb-3">
        <span
          className="text-[10px] px-1.5 py-0.5 rounded"
          style={{
            color: 'var(--do-text-tertiary)',
            backgroundColor: 'var(--do-bg-surface)',
          }}
        >
          {LAYOUT_LABELS[method.layout_type] || method.layout_type}
        </span>
        {dimensions.map((dim) => (
          <span
            key={dim}
            className="text-[10px] px-1.5 py-0.5 rounded"
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
            className="text-[10px] px-1.5 py-0.5 rounded"
            style={{
              color: 'var(--do-text-tertiary)',
              backgroundColor: 'var(--do-bg-surface)',
            }}
          >
            {tag}
          </span>
        ))}
        {method.is_preset && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded"
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
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors"
            style={{
              backgroundColor: 'var(--do-accent-alpha)',
              color: 'var(--do-accent)',
              border: '1px solid var(--do-accent-dim)',
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
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors"
            style={{
              backgroundColor: 'rgba(243, 139, 168, 0.1)',
              color: '#f38ba8',
              border: '1px solid rgba(243, 139, 168, 0.25)',
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
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors"
            style={{
              backgroundColor: 'var(--do-bg-surface)',
              color: 'var(--do-text-secondary)',
              border: '1px solid var(--do-border)',
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

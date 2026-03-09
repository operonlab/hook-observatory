import { Bug, ClipboardList, Clock, LayoutGrid, ListOrdered, Tag } from 'lucide-react'
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

interface HighlightItem {
  label: string
  icon: React.ReactNode
}

interface MethodInfoPanelProps {
  method: Method
}

export default function MethodInfoPanel({ method }: MethodInfoPanelProps) {
  const color = method.color || '#89b4fa'
  const config = method.config
  const dimensions = config?.dimensions || []

  const highlights: HighlightItem[] = []

  if (config?.frog?.enabled) {
    highlights.push({ label: '青蛙模式', icon: <Bug size={10} /> })
  }
  if (config?.time_awareness?.enabled) {
    highlights.push({ label: '時間感知', icon: <Clock size={10} /> })
  }
  if (config?.categories && config.categories.length > 0) {
    highlights.push({ label: `${config.categories.length} 個分類`, icon: <Tag size={10} /> })
  }
  if (config?.max_items != null) {
    highlights.push({ label: `最多 ${config.max_items} 項`, icon: <ListOrdered size={10} /> })
  }
  if (config?.sequential_strict) {
    highlights.push({ label: '嚴格順序', icon: <ClipboardList size={10} /> })
  }
  if (config?.completion_rule) {
    const modeLabels: Record<string, string> = {
      all: '全部完成',
      percentage: '百分比',
      frog_plus_percentage: '青蛙+百分比',
      weighted: '加權',
    }
    const modeLabel = modeLabels[config.completion_rule.mode] || config.completion_rule.mode
    highlights.push({ label: `完成規則: ${modeLabel}`, icon: <ClipboardList size={10} /> })
  }

  return (
    <div className="do-card p-4 space-y-3" style={{ borderColor: color + '33' }}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: color }} />
        <div className="min-w-0">
          <h3 className="text-[13px] font-medium truncate" style={{ color: 'var(--do-text)' }}>
            {method.name_zh || method.name}
          </h3>
          {method.name_zh && (
            <span className="text-[10px]" style={{ color: 'var(--do-text-muted)' }}>
              {method.name}
            </span>
          )}
        </div>
      </div>

      {/* Description */}
      {method.description && (
        <p
          className="text-[12px]"
          style={{ color: 'var(--do-text-secondary)', lineHeight: '1.65' }}
        >
          {method.description}
        </p>
      )}

      {/* Tags */}
      {(dimensions.length > 0 || highlights.length > 0) && (
        <>
          <div style={{ height: '1px', backgroundColor: 'var(--do-border)', opacity: 0.4 }} />
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* Layout type */}
            <span
              className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded font-medium"
              style={{ color, backgroundColor: color + '18' }}
            >
              <LayoutGrid size={10} />
              {LAYOUT_LABELS[method.layout_type] || method.layout_type}
            </span>

            {/* Dimensions */}
            {dimensions.map((dim) => (
              <span
                key={dim}
                className="text-[10px] px-2 py-0.5 rounded"
                style={{ color: '#89b4fa', backgroundColor: 'rgba(137, 180, 250, 0.12)' }}
              >
                {DIMENSION_LABELS[dim] || dim}
              </span>
            ))}

            {/* Config highlights */}
            {highlights.map((h) => (
              <span
                key={h.label}
                className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded"
                style={{
                  color: 'var(--do-text-tertiary)',
                  backgroundColor: 'var(--do-bg-surface)',
                  border: '1px solid var(--do-border)',
                }}
              >
                {h.icon}
                {h.label}
              </span>
            ))}

            {/* Tags */}
            {method.tags?.map((tag) => (
              <span
                key={tag}
                className="text-[10px] px-2 py-0.5 rounded"
                style={{
                  color: 'var(--do-text-tertiary)',
                  backgroundColor: 'var(--do-bg-surface)',
                  border: '1px solid var(--do-border)',
                }}
              >
                {tag}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

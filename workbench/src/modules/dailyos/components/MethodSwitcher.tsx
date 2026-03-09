import { Clock, Columns3, Grid2x2, Kanban, List, Settings } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useMethodStore } from '../stores/methodStore'
import type { Method } from '../types'

const LAYOUT_LABELS: Record<string, string> = {
  list: '清單',
  columns: '分欄',
  timeline: '時間軸',
  grid: '矩陣',
  kanban: '看板',
}

const LAYOUT_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  list: List,
  columns: Columns3,
  timeline: Clock,
  grid: Grid2x2,
  kanban: Kanban,
}

/**
 * Segmented tab bar for switching between planning methods.
 * Pure switching — method info is always visible in the sidebar.
 */
export default function MethodSwitcher() {
  const navigate = useNavigate()
  const {
    methods,
    activeSelections,
    primaryMethod,
    activateMethod,
    setPrimary,
    fetchMethods,
    methodsLoading,
  } = useMethodStore()
  const activeMethodIds = new Set(activeSelections.map((s) => s.method_id))

  if (methods.length === 0 && !methodsLoading) {
    fetchMethods()
  }

  if (methods.length === 0) return null

  const handleClick = (method: Method) => {
    if (method.id === primaryMethod?.id) return
    if (activeMethodIds.has(method.id)) {
      setPrimary(method.id)
    } else {
      activateMethod(method.id)
    }
  }

  return (
    <div
      className="flex items-stretch gap-1 p-1 rounded-lg overflow-x-auto"
      style={{ backgroundColor: 'var(--do-bg-surface)', border: '1px solid var(--do-border)' }}
    >
      {methods
        .filter((m) => m.is_preset)
        .map((method) => {
          const isActive = activeMethodIds.has(method.id)
          const isPrimary = method.id === primaryMethod?.id
          const LayoutIcon = LAYOUT_ICONS[method.layout_type]

          return (
            <button
              key={method.id}
              type="button"
              onClick={() => handleClick(method)}
              className="relative flex items-center gap-1.5 px-3 py-2 rounded-md text-[12px] font-medium whitespace-nowrap shrink-0 cursor-pointer"
              style={{
                backgroundColor: isPrimary
                  ? 'var(--do-accent-alpha)'
                  : isActive
                    ? 'rgba(137, 180, 250, 0.08)'
                    : 'transparent',
                color: isPrimary
                  ? 'var(--do-accent)'
                  : isActive
                    ? 'var(--do-text-secondary)'
                    : 'var(--do-text-muted)',
                transition: 'all 150ms ease',
                borderBottom: isPrimary ? '2px solid var(--do-accent)' : '2px solid transparent',
              }}
              onMouseEnter={(e) => {
                if (!isPrimary) {
                  e.currentTarget.style.backgroundColor = isActive
                    ? 'rgba(137, 180, 250, 0.14)'
                    : 'var(--do-bg-elevated)'
                }
              }}
              onMouseLeave={(e) => {
                if (!isPrimary) {
                  e.currentTarget.style.backgroundColor = isActive
                    ? 'rgba(137, 180, 250, 0.08)'
                    : 'transparent'
                }
              }}
              title={`${method.name_zh || method.name} — ${LAYOUT_LABELS[method.layout_type] || method.layout_type}`}
            >
              {LayoutIcon && <LayoutIcon size={13} />}
              <span>{method.name_zh || method.name}</span>
              {isPrimary && (
                <span className="text-[9px] opacity-60 ml-0.5">
                  {LAYOUT_LABELS[method.layout_type]}
                </span>
              )}
            </button>
          )
        })}

      {/* Settings button */}
      <button
        type="button"
        onClick={() => navigate('/dailyos/methods')}
        className="flex items-center px-2 py-2 rounded-md shrink-0 cursor-pointer ml-auto"
        style={{
          color: 'var(--do-text-muted)',
          transition: 'all 150ms ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = 'var(--do-bg-elevated)'
          e.currentTarget.style.color = 'var(--do-text-secondary)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = 'transparent'
          e.currentTarget.style.color = 'var(--do-text-muted)'
        }}
        title="管理方法論"
      >
        <Settings size={13} />
      </button>
    </div>
  )
}

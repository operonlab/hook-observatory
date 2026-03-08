import type { CategoryDef, MethodConfig, PlanItem } from '../../types'
import PlanItemRow from '../PlanItemRow'

interface GridLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
}

// Default Eisenhower quadrant colors
const QUADRANT_COLORS = ['#f38ba8', '#fab387', '#89b4fa', '#a6adc8']
const QUADRANT_BG = [
  'rgba(243, 139, 168, 0.08)',
  'rgba(250, 179, 135, 0.08)',
  'rgba(137, 180, 250, 0.08)',
  'rgba(166, 173, 200, 0.08)',
]

export default function GridLayout({ items, config, onToggle }: GridLayoutProps) {
  const categories = config.categories || []

  // Group items by category
  const grouped = new Map<string, PlanItem[]>()
  for (const cat of categories) {
    grouped.set(cat.id, [])
  }
  for (const item of items) {
    const catId = item.category || 'uncategorized'
    const list = grouped.get(catId) || []
    list.push(item)
    grouped.set(catId, list)
  }

  if (categories.length === 0) {
    return (
      <div
        className="rounded-lg border p-6 text-center text-[13px]"
        style={{ borderColor: 'var(--do-border)', color: 'var(--do-text-muted)' }}
      >
        此方法論尚未定義象限
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      {categories
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((cat: CategoryDef, idx: number) => {
          const catItems = grouped.get(cat.id) || []
          const color = cat.color || QUADRANT_COLORS[idx % QUADRANT_COLORS.length]
          const bg = QUADRANT_BG[idx % QUADRANT_BG.length]

          return (
            <div
              key={cat.id}
              className="rounded-lg border p-3 min-h-[160px]"
              style={{
                borderColor: 'var(--do-border)',
                backgroundColor: bg,
              }}
            >
              {/* Quadrant Header */}
              <div
                className="flex items-center gap-1.5 mb-2 pb-1.5 border-b"
                style={{ borderColor: 'var(--do-border)' }}
              >
                {cat.icon && <span className="text-sm">{cat.icon}</span>}
                <span className="text-[12px] font-medium" style={{ color }}>
                  {cat.name_zh || cat.name}
                </span>
                <span className="text-[10px] ml-auto" style={{ color: 'var(--do-text-muted)' }}>
                  {catItems.length}
                </span>
              </div>

              {/* Items */}
              <div className="space-y-1">
                {catItems.length === 0 ? (
                  <div
                    className="text-[10px] text-center py-2"
                    style={{ color: 'var(--do-text-muted)' }}
                  >
                    --
                  </div>
                ) : (
                  catItems
                    .sort((a, b) => a.sort_order - b.sort_order)
                    .map((item) => <PlanItemRow key={item.id} item={item} onToggle={onToggle} />)
                )}
              </div>
            </div>
          )
        })}
    </div>
  )
}

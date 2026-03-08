import type { CategoryDef, MethodConfig, PlanItem } from '../../types'
import PlanItemRow from '../PlanItemRow'

interface ColumnsLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
}

export default function ColumnsLayout({ items, config, onToggle }: ColumnsLayoutProps) {
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
        此方法論尚未定義分類
      </div>
    )
  }

  return (
    <div
      className="grid gap-4"
      style={{ gridTemplateColumns: `repeat(${Math.min(categories.length, 3)}, 1fr)` }}
    >
      {categories
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((cat: CategoryDef) => {
          const catItems = grouped.get(cat.id) || []
          const doneCount = catItems.filter((i) => i.status === 'done').length
          return (
            <div
              key={cat.id}
              className="rounded-lg border p-3"
              style={{
                borderColor: 'var(--do-border)',
                backgroundColor: 'var(--do-bg-elevated)',
              }}
            >
              {/* Column Header */}
              <div
                className="flex items-center justify-between mb-3 pb-2 border-b"
                style={{ borderColor: 'var(--do-border)' }}
              >
                <div className="flex items-center gap-1.5">
                  {cat.icon && <span className="text-sm">{cat.icon}</span>}
                  <span
                    className="text-[13px] font-medium"
                    style={{ color: cat.color || 'var(--do-text)' }}
                  >
                    {cat.name_zh || cat.name}
                  </span>
                </div>
                <span className="text-[11px]" style={{ color: 'var(--do-text-muted)' }}>
                  {doneCount}/{catItems.length}
                  {cat.max_items != null && ` (最多 ${cat.max_items})`}
                </span>
              </div>

              {/* Items */}
              <div className="space-y-1">
                {catItems.length === 0 ? (
                  <div
                    className="text-[11px] text-center py-3"
                    style={{ color: 'var(--do-text-muted)' }}
                  >
                    空
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

import type { CategoryDef, MethodConfig, PlanItem } from '../../types'
import PlanItemRow from '../PlanItemRow'

interface GridLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
  onAssignCategory?: (itemId: string, categoryId: string) => void
}

// Eisenhower quadrant metadata
const QUADRANT_META: Record<string, { hint: string; hintColor: string }> = {
  do: { hint: '立刻處理', hintColor: '#f38ba8' },
  schedule: { hint: '安排時間', hintColor: '#89b4fa' },
  delegate: { hint: '委派他人', hintColor: '#fab387' },
  eliminate: { hint: '考慮刪除', hintColor: '#a6adc8' },
}

// Default Eisenhower quadrant colors
const QUADRANT_COLORS = ['#f38ba8', '#fab387', '#89b4fa', '#a6adc8']
const QUADRANT_BG = [
  'rgba(243, 139, 168, 0.08)',
  'rgba(250, 179, 135, 0.08)',
  'rgba(137, 180, 250, 0.08)',
  'rgba(166, 173, 200, 0.08)',
]

export default function GridLayout({ items, config, onToggle, onAssignCategory }: GridLayoutProps) {
  const categories = config.categories || []

  // Sort categories by sort_order for correct evaluation order
  const sortedCategories = [...categories].sort((a, b) => a.sort_order - b.sort_order)

  // Group items by category
  const grouped = new Map<string, PlanItem[]>()
  const uncategorized: PlanItem[] = []
  for (const cat of sortedCategories) {
    grouped.set(cat.id, [])
  }
  for (const item of items) {
    const catId = item.category
    if (!catId || !grouped.has(catId)) {
      uncategorized.push(item)
    } else {
      const list = grouped.get(catId)!
      list.push(item)
    }
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

  // Build display grid: sort_order 0,1 on top row (urgent), 2,3 on bottom row (not urgent)
  // Left column = important, right column = not important
  // Eisenhower: Q1(do)=top-left, Q3(delegate)=top-right, Q2(schedule)=bottom-left, Q4(eliminate)=bottom-right
  // With our sort_order: do=0, delegate=1, schedule=2, eliminate=3
  // Grid layout: row 1 = [sort_order 0, sort_order 1], row 2 = [sort_order 2, sort_order 3]
  const gridCategories = sortedCategories.slice(0, 4)

  return (
    <div className="space-y-3">
      {/* Axis labels + Grid */}
      <div className="relative">
        {/* Top axis label */}
        <div
          className="flex justify-center mb-1.5"
        >
          <div className="flex items-center gap-3 text-[10px] font-medium" style={{ color: 'var(--do-text-tertiary)' }}>
            <span style={{ color: 'var(--do-urgent)' }}>緊急</span>
            <span>←</span>
            <span>→</span>
            <span style={{ color: 'var(--do-text-muted)' }}>不緊急</span>
          </div>
        </div>

        <div className="flex gap-1.5">
          {/* Left axis label */}
          <div className="flex flex-col items-center justify-center w-4 shrink-0">
            <span className="text-[10px] font-medium" style={{ color: 'var(--do-high)', writingMode: 'vertical-rl', textOrientation: 'mixed' }}>
              重要
            </span>
            <span className="text-[10px] my-1" style={{ color: 'var(--do-text-tertiary)', writingMode: 'vertical-rl' }}>
              ↑↓
            </span>
            <span className="text-[10px] font-medium" style={{ color: 'var(--do-text-muted)', writingMode: 'vertical-rl', textOrientation: 'mixed' }}>
              不重要
            </span>
          </div>

          {/* 2x2 Grid */}
          <div className="grid grid-cols-2 gap-2 flex-1">
            {gridCategories.map((cat: CategoryDef, idx: number) => {
              const catItems = grouped.get(cat.id) || []
              const color = cat.color || QUADRANT_COLORS[idx % QUADRANT_COLORS.length]
              const bg = QUADRANT_BG[idx % QUADRANT_BG.length]
              const meta = QUADRANT_META[cat.id]

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

                  {/* Action Hint */}
                  {meta && (
                    <div
                      className="text-[10px] mb-2 px-1.5 py-0.5 rounded inline-block"
                      style={{
                        color: meta.hintColor,
                        backgroundColor: `${meta.hintColor}1a`,
                      }}
                    >
                      {meta.hint}
                    </div>
                  )}

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
        </div>
      </div>

      {/* Uncategorized Section */}
      {uncategorized.length > 0 && (
        <div
          className="rounded-lg border p-3"
          style={{
            borderColor: 'var(--do-border)',
            backgroundColor: 'var(--do-bg-elevated)',
            borderStyle: 'dashed',
          }}
        >
          <div
            className="flex items-center gap-1.5 mb-2 pb-1.5 border-b"
            style={{ borderColor: 'var(--do-border)' }}
          >
            <span className="text-sm">📋</span>
            <span className="text-[12px] font-medium" style={{ color: 'var(--do-text-secondary)' }}>
              未分類
            </span>
            <span className="text-[10px] ml-auto" style={{ color: 'var(--do-text-muted)' }}>
              {uncategorized.length}
            </span>
          </div>
          <div
            className="text-[10px] mb-2"
            style={{ color: 'var(--do-text-muted)' }}
          >
            點擊色塊按鈕將項目分配到對應象限
          </div>
          <div className="space-y-1.5">
            {uncategorized
              .sort((a, b) => a.sort_order - b.sort_order)
              .map((item) => (
                <div key={item.id} className="flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <PlanItemRow item={item} onToggle={onToggle} />
                  </div>
                  {/* Quick assign buttons */}
                  {onAssignCategory && (
                    <div className="flex gap-1 shrink-0">
                      {sortedCategories.slice(0, 4).map((cat) => {
                        const catColor = cat.color || QUADRANT_COLORS[0]
                        const catMeta = QUADRANT_META[cat.id]
                        return (
                          <button
                            key={cat.id}
                            type="button"
                            title={`${cat.name_zh || cat.name}${catMeta ? ` - ${catMeta.hint}` : ''}`}
                            onClick={() => onAssignCategory(item.id, cat.id)}
                            className="w-5 h-5 rounded text-[8px] font-bold transition-opacity hover:opacity-100 opacity-60 shrink-0"
                            style={{
                              backgroundColor: `${catColor}33`,
                              color: catColor,
                              border: `1px solid ${catColor}66`,
                            }}
                          >
                            {cat.icon || cat.id[0].toUpperCase()}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}

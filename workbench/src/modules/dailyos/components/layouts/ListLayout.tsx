import type { MethodConfig, PlanItem } from '../../types'
import PlanItemRow from '../PlanItemRow'

interface ListLayoutProps {
  items: PlanItem[]
  config: MethodConfig
  onToggle?: (item: PlanItem) => void
}

export default function ListLayout({ items, config, onToggle }: ListLayoutProps) {
  const showNumbers = config.ui_hints?.show_numbers !== false
  const sequentialStrict = config.sequential_strict === true

  // Find the first incomplete item index
  const firstIncompleteIdx = items.findIndex((it) => it.status === 'pending')

  const sorted = [...items].sort((a, b) => a.sort_order - b.sort_order)

  return (
    <div className="space-y-1.5">
      {sorted.length === 0 ? (
        <div
          className="rounded-lg border p-6 text-center text-[13px]"
          style={{ borderColor: 'var(--do-border)', color: 'var(--do-text-muted)' }}
        >
          {config.ui_hints?.empty_state_message_zh || '尚未新增任何項目'}
        </div>
      ) : (
        sorted.map((item, idx) => {
          const dimmed =
            sequentialStrict &&
            item.status === 'pending' &&
            firstIncompleteIdx >= 0 &&
            idx > firstIncompleteIdx

          return (
            <PlanItemRow
              key={item.id}
              item={item}
              index={idx}
              showNumber={showNumbers}
              dimmed={dimmed}
              onToggle={onToggle}
            />
          )
        })
      )}
    </div>
  )
}

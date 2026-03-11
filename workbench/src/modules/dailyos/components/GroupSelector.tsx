import { FolderOpen } from 'lucide-react'
import { useRef, useState } from 'react'
import { useMethodStore } from '../stores/methodStore'

interface GroupSelectorProps {
  value?: string
  onChange: (groupId: string | undefined) => void
  compact?: boolean
}

export default function GroupSelector({ value, onChange, compact }: GroupSelectorProps) {
  const { taskGroups } = useMethodStore()
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  if (taskGroups.length === 0) return null

  const selected = taskGroups.find((g) => g.id === value)

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 rounded cursor-pointer"
        style={{
          padding: compact ? '2px 6px' : '3px 8px',
          fontSize: compact ? 10 : 11,
          color: selected ? selected.color : 'var(--do-text-muted)',
          backgroundColor: selected ? `${selected.color}18` : 'transparent',
          border: `1px solid ${selected ? `${selected.color}40` : 'var(--do-border)'}`,
          transition: 'all 150ms ease',
        }}
        title="選擇群組"
      >
        {selected ? (
          <>
            <span
              className="rounded-full block"
              style={{ width: 6, height: 6, backgroundColor: selected.color }}
            />
            {!compact && selected.name}
          </>
        ) : (
          <>
            <FolderOpen size={compact ? 10 : 11} />
            {!compact && '群組'}
          </>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className="absolute z-50 mt-1 rounded-lg border py-1 min-w-[120px]"
            style={{
              backgroundColor: 'var(--do-bg-elevated)',
              borderColor: 'var(--do-border)',
              boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
              right: 0,
            }}
          >
            <button
              type="button"
              onClick={() => {
                onChange(undefined)
                setOpen(false)
              }}
              className="w-full text-left px-3 py-1.5 text-[11px] cursor-pointer"
              style={{
                color: 'var(--do-text-muted)',
                backgroundColor: !value ? 'var(--do-bg-surface)' : 'transparent',
                transition: 'background-color 100ms ease',
              }}
            >
              無群組
            </button>
            {taskGroups.map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => {
                  onChange(g.id)
                  setOpen(false)
                }}
                className="w-full text-left px-3 py-1.5 text-[11px] flex items-center gap-2 cursor-pointer"
                style={{
                  color: 'var(--do-text)',
                  backgroundColor: value === g.id ? 'var(--do-bg-surface)' : 'transparent',
                  transition: 'background-color 100ms ease',
                }}
              >
                <span
                  className="rounded-full block shrink-0"
                  style={{ width: 8, height: 8, backgroundColor: g.color }}
                />
                {g.name}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

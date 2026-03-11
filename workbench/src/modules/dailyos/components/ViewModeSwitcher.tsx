export type ViewMode = 'day' | 'week' | 'month'

const MODES: { key: ViewMode; label: string }[] = [
  { key: 'day', label: '日' },
  { key: 'week', label: '週' },
  { key: 'month', label: '月' },
]

interface ViewModeSwitcherProps {
  value: ViewMode
  onChange: (mode: ViewMode) => void
}

export default function ViewModeSwitcher({ value, onChange }: ViewModeSwitcherProps) {
  return (
    <div
      className="inline-flex rounded-lg overflow-hidden border"
      style={{ borderColor: 'var(--do-border)' }}
    >
      {MODES.map((mode) => {
        const active = value === mode.key
        return (
          <button
            key={mode.key}
            type="button"
            onClick={() => onChange(mode.key)}
            className="px-3.5 py-1.5 text-[12px] font-medium cursor-pointer"
            style={{
              backgroundColor: active ? 'var(--do-accent-alpha)' : 'transparent',
              color: active ? 'var(--do-accent)' : 'var(--do-text-tertiary)',
              borderRight: mode.key !== 'month' ? '1px solid var(--do-border)' : 'none',
              transition: 'background-color 150ms ease, color 150ms ease',
            }}
          >
            {mode.label}
          </button>
        )
      })}
    </div>
  )
}

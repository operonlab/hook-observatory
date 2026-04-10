import { useMemvaultStore } from '../stores'
import type { Lens } from '../types'

const LENSES: { key: Lens; label: string }[] = [
  { key: 'recall', label: 'Recall' },
  { key: 'journey', label: 'Journey' },
  { key: 'understand', label: 'Understand' },
]

export default function LensSelector() {
  const activeLens = useMemvaultStore((s) => s.activeLens)
  const setActiveLens = useMemvaultStore((s) => s.setActiveLens)

  return (
    <div
      className="inline-flex rounded-xl border p-1"
      style={{
        backgroundColor: 'var(--crust)',
        borderColor: 'var(--surface0)',
      }}
    >
      {LENSES.map((lens) => {
        const active = activeLens === lens.key
        return (
          <button
            key={lens.key}
            onClick={() => setActiveLens(lens.key)}
            className="rounded-lg px-5 py-2 text-sm font-medium transition-all"
            style={{
              backgroundColor: active
                ? 'color-mix(in srgb, var(--blue) 18%, var(--surface0))'
                : 'transparent',
              color: active ? 'var(--blue)' : 'var(--subtext1)',
              minHeight: 36,
            }}
          >
            {lens.label}
          </button>
        )
      })}
    </div>
  )
}

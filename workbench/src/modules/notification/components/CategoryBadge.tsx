const CATEGORY_COLORS: Record<string, string> = {
  sentinel: '#f38ba8',
  system: '#cba6f7',
  finance: '#a6e3a1',
  taskflow: '#89b4fa',
  intelflow: '#94e2d5',
  agent: '#fab387',
}

export default function CategoryBadge({ category }: { category: string }) {
  const color = CATEGORY_COLORS[category] ?? 'var(--subtext1)'
  return (
    <span
      className="inline-block rounded px-2 py-0.5 text-[11px] font-medium"
      style={{
        backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)`,
        color,
        border: `1px solid color-mix(in srgb, ${color} 25%, transparent)`,
      }}
    >
      {category}
    </span>
  )
}

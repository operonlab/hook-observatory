import type { LayoutType } from '../types'

interface LayoutPreviewProps {
  layout: LayoutType
  color?: string
}

/**
 * Mini visual preview thumbnail for each layout type.
 * Pure CSS/SVG — no data needed.
 */
export default function LayoutPreview({ layout, color = '#89b4fa' }: LayoutPreviewProps) {
  const dim = color + '44'
  const bg = color + '18'

  return (
    <div
      className="w-full aspect-[4/3] rounded-md overflow-hidden p-2 flex items-center justify-center"
      style={{ backgroundColor: bg }}
    >
      {layout === 'list' && <ListPreview color={color} dim={dim} />}
      {layout === 'columns' && <ColumnsPreview color={color} dim={dim} />}
      {layout === 'grid' && <GridPreview color={color} dim={dim} />}
      {layout === 'kanban' && <KanbanPreview color={color} dim={dim} />}
      {layout === 'timeline' && <TimelinePreview color={color} dim={dim} />}
    </div>
  )
}

function ListPreview({ color, dim }: { color: string; dim: string }) {
  return (
    <div className="w-full space-y-1.5 px-1">
      {[1, 2, 3, 4, 5, 6].map((n) => (
        <div key={n} className="flex items-center gap-1.5">
          <span className="text-[7px] font-bold w-3 text-center shrink-0" style={{ color }}>
            {n}
          </span>
          <div
            className="h-2 rounded-full flex-1"
            style={{
              backgroundColor: n <= 2 ? color : dim,
              opacity: n <= 2 ? 0.7 : 0.4,
              maxWidth: `${90 - n * 8}%`,
            }}
          />
        </div>
      ))}
    </div>
  )
}

function ColumnsPreview({ color, dim }: { color: string; dim: string }) {
  const cols = [
    { label: '1', items: 1, accent: '#f38ba8' },
    { label: '3', items: 3, accent: color },
    { label: '5', items: 2, accent: '#a6e3a1' },
  ]
  return (
    <div className="flex gap-1 w-full h-full">
      {cols.map((col) => (
        <div
          key={col.label}
          className="flex-1 rounded p-1 flex flex-col gap-0.5"
          style={{ backgroundColor: col.accent + '18', border: `1px solid ${col.accent}33` }}
        >
          <span className="text-[6px] font-bold text-center" style={{ color: col.accent }}>
            {col.label}
          </span>
          {Array.from({ length: col.items }).map((_, i) => (
            <div
              key={i}
              className="h-1.5 rounded-sm"
              style={{ backgroundColor: col.accent + '55' }}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

function GridPreview({ color }: { color: string }) {
  const quads = [
    { label: '🔴', bg: '#f38ba818', border: '#f38ba833' },
    { label: '🟠', bg: '#fab38718', border: '#fab38733' },
    { label: '🔵', bg: '#89b4fa18', border: '#89b4fa33' },
    { label: '⚪', bg: '#a6adc818', border: '#a6adc833' },
  ]
  return (
    <div className="w-full h-full flex flex-col gap-0.5">
      {/* Axis labels */}
      <div className="flex justify-center">
        <span className="text-[5px]" style={{ color }}>
          緊急 ← → 不緊急
        </span>
      </div>
      <div className="flex gap-0.5 flex-1">
        <div className="flex flex-col items-center justify-center w-2.5">
          <span className="text-[5px]" style={{ color, writingMode: 'vertical-rl' }}>
            重要↑↓
          </span>
        </div>
        <div className="grid grid-cols-2 gap-0.5 flex-1">
          {quads.map((q, i) => (
            <div
              key={i}
              className="rounded flex items-center justify-center"
              style={{ backgroundColor: q.bg, border: `1px solid ${q.border}` }}
            >
              <span className="text-[7px]">{q.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function KanbanPreview({ color, dim }: { color: string; dim: string }) {
  const cols = [
    { label: '待辦', count: 3, accent: '#a6adc8' },
    { label: '進行', count: 2, accent: color },
    { label: '完成', count: 1, accent: '#a6e3a1' },
  ]
  return (
    <div className="flex gap-0.5 w-full h-full">
      {cols.map((col) => (
        <div
          key={col.label}
          className="flex-1 rounded p-1 flex flex-col"
          style={{ backgroundColor: col.accent + '12', border: `1px solid ${col.accent}33` }}
        >
          <div className="flex items-center gap-0.5 mb-1">
            <div className="w-1 h-1 rounded-full" style={{ backgroundColor: col.accent }} />
            <span className="text-[5px] font-medium" style={{ color: col.accent }}>
              {col.label}
            </span>
          </div>
          <div className="space-y-0.5 flex-1">
            {Array.from({ length: col.count }).map((_, i) => (
              <div
                key={i}
                className="h-2 rounded-sm"
                style={{ backgroundColor: col.accent + '44' }}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function TimelinePreview({ color, dim }: { color: string; dim: string }) {
  const slots = ['09', '10', '11', '12', '13', '14']
  const filled = [true, true, false, true, false, true]
  return (
    <div className="w-full space-y-0.5 px-0.5">
      {slots.map((slot, i) => (
        <div key={slot} className="flex items-center gap-1">
          <span className="text-[5px] font-mono w-3 text-right shrink-0" style={{ color: dim }}>
            {slot}
          </span>
          <div
            className="w-1 h-1 rounded-full shrink-0"
            style={{ backgroundColor: filled[i] ? color : dim }}
          />
          <div
            className="h-1.5 flex-1 rounded-sm"
            style={{ backgroundColor: filled[i] ? color + '55' : 'transparent' }}
          />
        </div>
      ))}
    </div>
  )
}

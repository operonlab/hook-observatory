import { X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

const TAG_PALETTE = [
  '#cba6f7',
  '#f38ba8',
  '#fab387',
  '#f9e2af',
  '#a6e3a1',
  '#94e2d5',
  '#89dceb',
  '#89b4fa',
  '#b4befe',
  '#9399b2',
]

export interface TagItem {
  name: string
  color: string
}

interface TagInputProps {
  value: TagItem[]
  onChange: (tags: TagItem[]) => void
  placeholder?: string
}

export function tagsToItems(names: string[], styles: Record<string, string>): TagItem[] {
  return names.map((name, i) => ({
    name,
    color: styles[name] ?? TAG_PALETTE[i % TAG_PALETTE.length],
  }))
}

export function itemsToNames(items: TagItem[]): string[] {
  return items.map((t) => t.name)
}

export function itemsToStyles(items: TagItem[]): Record<string, string> {
  const m: Record<string, string> = {}
  for (const t of items) m[t.name] = t.color
  return m
}

export default function TagInput({ value, onChange, placeholder = '輸入標籤...' }: TagInputProps) {
  const [input, setInput] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const getNextColor = () => {
    const used = new Set(value.map((t) => t.color))
    return TAG_PALETTE.find((c) => !used.has(c)) ?? TAG_PALETTE[value.length % TAG_PALETTE.length]
  }

  const addTag = (raw: string) => {
    const name = raw.trim()
    if (!name || value.some((t) => t.name === name)) return
    onChange([...value, { name, color: getNextColor() }])
  }

  const removeTag = (idx: number) => {
    onChange(value.filter((_, i) => i !== idx))
  }

  const cycleColor = (idx: number) => {
    const cur = TAG_PALETTE.indexOf(value[idx].color)
    const next = TAG_PALETTE[(cur + 1) % TAG_PALETTE.length]
    onChange(value.map((t, i) => (i === idx ? { ...t, color: next } : t)))
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addTag(input)
      setInput('')
    }
    if (e.key === 'Backspace' && !input && value.length > 0) {
      removeTag(value.length - 1)
    }
  }

  // Handle paste with commas
  const handlePaste = (e: React.ClipboardEvent) => {
    const text = e.clipboardData.getData('text')
    if (text.includes(',')) {
      e.preventDefault()
      const parts = text.split(',')
      for (const p of parts) addTag(p)
    }
  }

  // Workaround: on mobile, detect comma in onChange
  useEffect(() => {
    if (input.includes(',')) {
      const parts = input.split(',')
      for (const p of parts) addTag(p)
      setInput('')
    }
  }, [input])

  return (
    <div
      className="flex flex-wrap gap-1.5 px-2 py-1.5 rounded border min-h-[38px] cursor-text"
      style={{
        borderColor: 'var(--fn-border)',
        backgroundColor: 'var(--fn-bg-surface)',
      }}
      onClick={() => inputRef.current?.focus()}
    >
      {value.map((tag, i) => (
        <span
          key={tag.name}
          className="inline-flex items-center gap-0.5 pl-2 pr-1 py-0.5 rounded text-[11px] font-medium shrink-0"
          style={{
            backgroundColor: `${tag.color}25`,
            color: tag.color,
          }}
        >
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              cycleColor(i)
            }}
            className="hover:opacity-70 transition-opacity"
            title="點擊換色"
          >
            {tag.name}
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              removeTag(i)
            }}
            className="ml-0.5 hover:opacity-70 transition-opacity rounded-full p-0.5"
            style={{ backgroundColor: `${tag.color}20` }}
          >
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        placeholder={value.length === 0 ? placeholder : ''}
        className="flex-1 min-w-[60px] text-[12px] bg-transparent outline-none py-0.5"
        style={{ color: 'var(--fn-text)' }}
      />
    </div>
  )
}

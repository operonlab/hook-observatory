import { Plus } from 'lucide-react'
import { useState } from 'react'

interface AddItemInputProps {
  onAdd: (title: string) => void
  placeholder?: string
}

export default function AddItemInput({ onAdd, placeholder = '新增項目...' }: AddItemInputProps) {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)

  const handleSubmit = () => {
    const trimmed = value.trim()
    if (!trimmed) return
    onAdd(trimmed)
    setValue('')
  }

  return (
    <div
      className="flex items-center gap-2 px-3 py-2.5 rounded-lg border border-dashed"
      style={{
        borderColor: focused ? 'var(--do-accent-dim)' : 'var(--do-border)',
        backgroundColor: 'var(--do-bg-surface)',
        boxShadow: focused ? '0 0 0 2px var(--do-accent-alpha)' : 'none',
        transition: 'border-color 150ms ease, box-shadow 150ms ease',
      }}
    >
      <button
        type="button"
        onClick={handleSubmit}
        className="shrink-0 flex items-center justify-center w-6 h-6 rounded-full cursor-pointer"
        style={{
          color: 'var(--do-text-muted)',
          transition: 'background-color 150ms ease, color 150ms ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = 'var(--do-accent-alpha)'
          e.currentTarget.style.color = 'var(--do-accent)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = 'transparent'
          e.currentTarget.style.color = 'var(--do-text-muted)'
        }}
      >
        <Plus size={14} />
      </button>
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleSubmit()
        }}
        placeholder={placeholder}
        className="flex-1 bg-transparent text-[13px] outline-none"
        style={{ color: 'var(--do-text)' }}
      />
      {value.trim() && (
        <button
          type="button"
          onClick={handleSubmit}
          className="text-[11px] px-2 py-0.5 rounded font-medium cursor-pointer"
          style={{
            color: 'var(--do-accent)',
            backgroundColor: 'var(--do-accent-alpha)',
            transition: 'background-color 150ms ease',
          }}
        >
          新增
        </button>
      )}
    </div>
  )
}

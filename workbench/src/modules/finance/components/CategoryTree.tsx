import { ChevronDown, ChevronRight, Pencil, Plus } from 'lucide-react'
import { useState } from 'react'
import { categoryApi } from '../api'
import type { Category, CategoryCreate } from '../types'

interface CategoryTreeProps {
  categories: Category[]
  selectedId?: string
  onSelect?: (id: string | null) => void
  onRefresh?: () => void
  editable?: boolean
}

export default function CategoryTree({
  categories,
  selectedId,
  onSelect,
  onRefresh,
  editable,
}: CategoryTreeProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [addingParentId, setAddingParentId] = useState<string | null>(null)
  const [newName, setNewName] = useState('')

  const roots = categories.filter((c) => !c.parent_id)

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleRename = async (id: string) => {
    if (!editValue.trim()) return
    await categoryApi.update(id, { name: editValue.trim() })
    setEditingId(null)
    onRefresh?.()
  }

  const handleAdd = async (parentId?: string) => {
    if (!newName.trim()) return
    const data: CategoryCreate = { name: newName.trim(), parent_id: parentId }
    await categoryApi.create(data)
    setAddingParentId(null)
    setNewName('')
    onRefresh?.()
  }

  const renderNodeLabel = (cat: Category) => {
    if (editingId === cat.id) {
      return (
        <input
          type="text"
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={() => handleRename(cat.id)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleRename(cat.id)
            if (e.key === 'Escape') setEditingId(null)
          }}
          className="flex-1 px-1 py-0.5 text-xs rounded border bg-transparent"
          style={{ borderColor: 'var(--fn-border)', color: 'var(--fn-text)' }}
          onClick={(e) => e.stopPropagation()}
        />
      )
    }
    return (
      <>
        <span className="text-xs truncate">
          {cat.icon ? `${cat.icon} ` : ''}
          {cat.name}
        </span>
        {editable && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setEditingId(cat.id)
              setEditValue(cat.name)
            }}
            className="ml-auto shrink-0 opacity-0 group-hover:opacity-100 p-0.5"
            style={{ color: 'var(--fn-text-muted)' }}
          >
            <Pencil size={10} />
          </button>
        )}
      </>
    )
  }

  const renderAddForm = (parentId: string, depth: number) => {
    if (addingParentId !== parentId) return null
    return (
      <div
        className="flex items-center gap-1 py-1"
        style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
      >
        <input
          type="text"
          placeholder="子分類名稱"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleAdd(parentId === '__root__' ? undefined : parentId)
            if (e.key === 'Escape') setAddingParentId(null)
          }}
          className="flex-1 px-2 py-1 text-xs rounded border bg-transparent"
          style={{ borderColor: 'var(--fn-border)', color: 'var(--fn-text)' }}
        />
      </div>
    )
  }

  const renderNode = (cat: Category, depth: number) => {
    const children = categories.filter((c) => c.parent_id === cat.id)
    const hasChildren = children.length > 0
    const isExpanded = expanded.has(cat.id)
    const isSelected = selectedId === cat.id

    return (
      <div key={cat.id}>
        <button
          type="button"
          onClick={() => onSelect?.(isSelected ? null : cat.id)}
          className="w-full flex items-center gap-1.5 py-1.5 px-2 rounded text-left transition-colors"
          style={{
            paddingLeft: `${depth * 16 + 8}px`,
            backgroundColor: isSelected ? 'var(--fn-accent-alpha)' : 'transparent',
            color: isSelected ? 'var(--fn-accent)' : 'var(--fn-text)',
          }}
        >
          {hasChildren ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                toggle(cat.id)
              }}
              className="shrink-0 p-0.5"
              style={{ color: 'var(--fn-text-muted)' }}
            >
              {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </button>
          ) : (
            <span className="w-4 shrink-0" />
          )}
          {renderNodeLabel(cat)}
        </button>

        {hasChildren && isExpanded && children.map((child) => renderNode(child, depth + 1))}
        {renderAddForm(cat.id, depth)}
      </div>
    )
  }

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => onSelect?.(null)}
        className="w-full flex items-center gap-1.5 py-1.5 px-2 rounded text-xs text-left transition-colors"
        style={{
          backgroundColor: !selectedId ? 'var(--fn-accent-alpha)' : 'transparent',
          color: !selectedId ? 'var(--fn-accent)' : 'var(--fn-text-tertiary)',
        }}
      >
        全部分類
      </button>

      {roots.map((cat) => renderNode(cat, 0))}

      {editable &&
        (addingParentId === '__root__' ? (
          renderAddForm('__root__', -1)
        ) : (
          <button
            type="button"
            onClick={() => setAddingParentId('__root__')}
            className="flex items-center gap-1 px-2 py-1.5 text-xs transition-colors"
            style={{ color: 'var(--fn-text-muted)' }}
          >
            <Plus size={12} /> 新增分類
          </button>
        ))}
    </div>
  )
}

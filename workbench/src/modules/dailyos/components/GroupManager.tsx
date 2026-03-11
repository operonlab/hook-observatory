import { Eye, EyeOff, FolderOpen, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useMethodStore } from '../stores/methodStore'
import type { TaskGroup } from '../types'

const DEFAULT_COLORS = [
  '#cba6f7', // mauve
  '#89b4fa', // blue
  '#a6e3a1', // green
  '#f9e2af', // yellow
  '#fab387', // peach
  '#f38ba8', // red
  '#94e2d5', // teal
  '#89dceb', // sky
]

function ColorDot({
  color,
  selected,
  onClick,
}: {
  color: string
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full cursor-pointer"
      style={{
        width: 20,
        height: 20,
        backgroundColor: color,
        outline: selected ? `2px solid ${color}` : 'none',
        outlineOffset: 2,
        transition: 'outline 150ms ease, transform 150ms ease',
        transform: selected ? 'scale(1.15)' : 'scale(1)',
      }}
    />
  )
}

function GroupRow({
  group,
  hidden,
  onToggleVisibility,
  onEdit,
  onRemove,
}: {
  group: TaskGroup
  hidden: boolean
  onToggleVisibility: () => void
  onEdit: () => void
  onRemove: () => void
}) {
  return (
    <div
      className="group flex items-center gap-2 px-2 py-1.5 rounded-md"
      style={{
        opacity: hidden ? 0.5 : 1,
        transition: 'background-color 150ms ease, opacity 150ms ease',
      }}
    >
      <span
        className="shrink-0 rounded-full block"
        style={{ width: 10, height: 10, backgroundColor: group.color }}
      />
      <span className="flex-1 text-[12px] font-medium truncate" style={{ color: 'var(--do-text)' }}>
        {group.name}
      </span>
      <button
        type="button"
        onClick={onToggleVisibility}
        className="shrink-0 p-0.5 rounded cursor-pointer"
        style={{ color: 'var(--do-text-muted)', transition: 'color 150ms ease' }}
        title={hidden ? '顯示' : '隱藏'}
      >
        {hidden ? <EyeOff size={12} /> : <Eye size={12} />}
      </button>
      <button
        type="button"
        onClick={onEdit}
        className="shrink-0 p-0.5 rounded cursor-pointer opacity-0 group-hover:opacity-100"
        style={{ color: 'var(--do-text-muted)', transition: 'opacity 150ms ease' }}
        title="編輯"
      >
        <Pencil size={12} />
      </button>
      <button
        type="button"
        onClick={onRemove}
        className="shrink-0 p-0.5 rounded cursor-pointer opacity-0 group-hover:opacity-100 hover:!text-[#f38ba8]"
        style={{
          color: 'var(--do-text-muted)',
          transition: 'opacity 150ms ease, color 150ms ease',
        }}
        title="刪除"
      >
        <Trash2 size={12} />
      </button>
    </div>
  )
}

function InlineForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: { name: string; color: string }
  onSave: (name: string, color: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initial?.name || '')
  const [color, setColor] = useState(initial?.color || DEFAULT_COLORS[0])
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSubmit = () => {
    if (!name.trim()) return
    onSave(name.trim(), color)
  }

  return (
    <div
      className="rounded-md border p-2.5 space-y-2"
      style={{
        borderColor: 'var(--do-accent-dim)',
        backgroundColor: 'var(--do-bg-surface)',
      }}
    >
      <input
        ref={inputRef}
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleSubmit()
          if (e.key === 'Escape') onCancel()
        }}
        placeholder="群組名稱"
        className="w-full bg-transparent text-[12px] outline-none"
        style={{ color: 'var(--do-text)' }}
      />
      <div className="flex items-center gap-1.5">
        {DEFAULT_COLORS.map((c) => (
          <ColorDot key={c} color={c} selected={color === c} onClick={() => setColor(c)} />
        ))}
      </div>
      <div className="flex justify-end gap-1.5">
        <button
          type="button"
          onClick={onCancel}
          className="text-[11px] px-2 py-1 rounded cursor-pointer"
          style={{ color: 'var(--do-text-muted)' }}
        >
          取消
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!name.trim()}
          className="text-[11px] px-2 py-1 rounded font-medium cursor-pointer disabled:opacity-40"
          style={{
            color: '#1e1e2e',
            backgroundColor: 'var(--do-accent)',
          }}
        >
          {initial ? '更新' : '新增'}
        </button>
      </div>
    </div>
  )
}

export default function GroupManager() {
  const {
    taskGroups,
    taskGroupsLoading,
    hiddenGroupIds,
    fetchTaskGroups,
    addTaskGroup,
    updateTaskGroup,
    removeTaskGroup,
    toggleGroupVisibility,
  } = useMethodStore()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  useEffect(() => {
    fetchTaskGroups()
  }, [fetchTaskGroups])

  const handleAdd = async (name: string, color: string) => {
    await addTaskGroup({ name, color, sort_order: taskGroups.length })
    setShowForm(false)
  }

  const handleUpdate = async (id: string, name: string, color: string) => {
    await updateTaskGroup(id, { name, color })
    setEditingId(null)
  }

  const handleRemove = (id: string) => {
    removeTaskGroup(id)
  }

  if (taskGroupsLoading && taskGroups.length === 0) {
    return null
  }

  return (
    <div className="do-card p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <FolderOpen size={13} style={{ color: 'var(--do-accent)' }} />
          <span className="text-[12px] font-semibold" style={{ color: 'var(--do-text)' }}>
            群組
          </span>
          {taskGroups.length > 0 && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-full"
              style={{ color: 'var(--do-text-muted)', backgroundColor: 'var(--do-bg-surface)' }}
            >
              {taskGroups.length}
            </span>
          )}
        </div>
        {!showForm && !editingId && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--do-text-muted)', transition: 'color 150ms ease' }}
            title="新增群組"
          >
            <Plus size={13} />
          </button>
        )}
      </div>

      {taskGroups.length === 0 && !showForm && (
        <p className="text-[11px] py-1" style={{ color: 'var(--do-text-muted)' }}>
          建立群組來分類與篩選項目
        </p>
      )}

      {taskGroups.map((group) =>
        editingId === group.id ? (
          <InlineForm
            key={group.id}
            initial={{ name: group.name, color: group.color }}
            onSave={(name, color) => handleUpdate(group.id, name, color)}
            onCancel={() => setEditingId(null)}
          />
        ) : (
          <GroupRow
            key={group.id}
            group={group}
            hidden={hiddenGroupIds.has(group.id)}
            onToggleVisibility={() => toggleGroupVisibility(group.id)}
            onEdit={() => setEditingId(group.id)}
            onRemove={() => handleRemove(group.id)}
          />
        ),
      )}

      {showForm && <InlineForm onSave={handleAdd} onCancel={() => setShowForm(false)} />}
    </div>
  )
}

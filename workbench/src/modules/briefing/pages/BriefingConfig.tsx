import {
  ChevronDown,
  ChevronUp,
  Palette,
  Plus,
  Trash2,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { briefingApi } from '../api/client'
import { useAnalysts, useTopics } from '../hooks/useBriefing'
import type {
  Analyst,
  AnalystCreate,
  BriefingSubtopicCreate,
  BriefingTopic,
  BriefingTopicCreate,
} from '../types'

function ToggleSwitch({
  enabled,
  onToggle,
}: {
  enabled: boolean
  onToggle: () => void
}) {
  return (
    <button
      onClick={onToggle}
      className="relative w-9 h-5 transition-colors"
      style={{
        backgroundColor: enabled ? 'var(--bf-accent)' : 'var(--bf-bg-surface)',
        border: `1px solid ${enabled ? 'var(--bf-accent)' : 'var(--bf-border)'}`,
      }}
    >
      <span
        className="absolute top-0.5 w-3.5 h-3.5 transition-transform"
        style={{
          backgroundColor: enabled ? 'var(--bf-text-on-accent)' : 'var(--bf-text-muted)',
          left: enabled ? 'calc(100% - 18px)' : '2px',
        }}
      />
    </button>
  )
}

function TopicCard({
  topic,
  onRefresh,
}: {
  topic: BriefingTopic
  onRefresh: () => void
}) {
  const [open, setOpen] = useState(false)
  const [newSubtopic, setNewSubtopic] = useState('')

  const handleToggle = async () => {
    await briefingApi.toggleTopic(topic.id)
    onRefresh()
  }

  const handleDelete = async () => {
    await briefingApi.deleteTopic(topic.id)
    onRefresh()
  }

  const handleAddSubtopic = async () => {
    if (!newSubtopic.trim()) return
    const data: BriefingSubtopicCreate = { name: newSubtopic.trim() }
    await briefingApi.addSubtopic(topic.id, data)
    setNewSubtopic('')
    onRefresh()
  }

  const handleDeleteSubtopic = async (subtopicId: string) => {
    await briefingApi.deleteSubtopic(topic.id, subtopicId)
    onRefresh()
  }

  return (
    <div
      className="border"
      style={{ backgroundColor: 'var(--bf-bg-elevated)', borderColor: 'var(--bf-border)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 sm:px-5 py-3">
        <button onClick={() => setOpen(!open)} className="flex items-center gap-2 flex-1 text-left">
          <span style={{ color: 'var(--bf-text-muted)' }}>
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
          <span className="text-sm font-medium" style={{ color: 'var(--bf-text)' }}>
            {topic.display_name}
          </span>
          <span className="text-[10px]" style={{ color: 'var(--bf-text-dim)' }}>
            {topic.name}
          </span>
          {topic.subtopics.length > 0 && (
            <span className="text-[10px]" style={{ color: 'var(--bf-text-dim)' }}>
              ({topic.subtopics.length} 子項)
            </span>
          )}
        </button>
        <div className="flex items-center gap-3">
          <ToggleSwitch enabled={topic.enabled} onToggle={handleToggle} />
          <button
            onClick={handleDelete}
            className="p-1 transition-colors"
            style={{ color: 'var(--bf-text-muted)' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = '#f87171' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--bf-text-muted)' }}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Expanded: subtopics + description */}
      {open && (
        <div className="px-4 sm:px-5 pb-4 space-y-3 border-t" style={{ borderColor: 'var(--bf-border)' }}>
          {topic.description && (
            <p className="text-xs pt-3" style={{ color: 'var(--bf-text-muted)' }}>
              {topic.description}
            </p>
          )}

          {/* Subtopics */}
          <div className="space-y-1">
            {topic.subtopics.map((st) => (
              <div key={st.id} className="flex items-center justify-between py-1.5">
                <span className="text-sm" style={{ color: 'var(--bf-text-secondary)' }}>
                  {st.name}
                </span>
                <button
                  onClick={() => handleDeleteSubtopic(st.id)}
                  className="p-1"
                  style={{ color: 'var(--bf-text-dim)' }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>

          {/* Add subtopic */}
          <div className="flex items-center gap-2 pt-2">
            <input
              type="text"
              value={newSubtopic}
              onChange={(e) => setNewSubtopic(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAddSubtopic() }}
              placeholder="新增子項..."
              className="flex-1 bg-transparent text-sm outline-none border-b py-1 placeholder:opacity-40"
              style={{
                color: 'var(--bf-text)',
                borderColor: 'var(--bf-border)',
                caretColor: 'var(--bf-accent)',
              }}
            />
            <button
              onClick={handleAddSubtopic}
              disabled={!newSubtopic.trim()}
              className="p-1 disabled:opacity-30"
              style={{ color: 'var(--bf-accent)' }}
            >
              <Plus size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function AnalystCard({
  analyst,
  onRefresh,
}: {
  analyst: Analyst
  onRefresh: () => void
}) {
  const handleToggle = async () => {
    await briefingApi.toggleAnalyst(analyst.id)
    onRefresh()
  }

  const handleDelete = async () => {
    await briefingApi.deleteAnalyst(analyst.id)
    onRefresh()
  }

  return (
    <div
      className="flex items-center justify-between px-4 sm:px-5 py-3 border"
      style={{
        backgroundColor: 'var(--bf-bg-elevated)',
        borderColor: 'var(--bf-border)',
        borderLeftWidth: 3,
        borderLeftColor: analyst.color,
      }}
    >
      <div className="flex items-center gap-3">
        <div
          className="w-7 h-7 flex items-center justify-center text-[10px] font-bold"
          style={{ backgroundColor: analyst.color, color: 'var(--bf-bg)' }}
        >
          {analyst.display_name.charAt(0)}
        </div>
        <div>
          <span className="text-sm font-medium" style={{ color: 'var(--bf-text)' }}>
            {analyst.display_name}
          </span>
          {analyst.model_id && (
            <span className="text-[10px] ml-2" style={{ color: 'var(--bf-text-dim)' }}>
              {analyst.model_id}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <ToggleSwitch enabled={analyst.enabled} onToggle={handleToggle} />
        <button
          onClick={handleDelete}
          className="p-1 transition-colors"
          style={{ color: 'var(--bf-text-muted)' }}
          onMouseEnter={(e) => { e.currentTarget.style.color = '#f87171' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--bf-text-muted)' }}
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  )
}

export default function BriefingConfig() {
  const { topics, fetchTopics } = useTopics()
  const { analysts, fetchAnalysts } = useAnalysts()
  const [showAddTopic, setShowAddTopic] = useState(false)
  const [showAddAnalyst, setShowAddAnalyst] = useState(false)
  const [newTopic, setNewTopic] = useState({ name: '', display_name: '', description: '' })
  const [newAnalyst, setNewAnalyst] = useState({ name: '', display_name: '', color: '#c9a962' })

  const handleAddTopic = async () => {
    if (!newTopic.name.trim() || !newTopic.display_name.trim()) return
    const data: BriefingTopicCreate = {
      name: newTopic.name.trim(),
      display_name: newTopic.display_name.trim(),
      description: newTopic.description.trim() || undefined,
    }
    await briefingApi.createTopic(data)
    setNewTopic({ name: '', display_name: '', description: '' })
    setShowAddTopic(false)
    fetchTopics()
  }

  const handleAddAnalyst = async () => {
    if (!newAnalyst.name.trim() || !newAnalyst.display_name.trim()) return
    const data: AnalystCreate = {
      name: newAnalyst.name.trim(),
      display_name: newAnalyst.display_name.trim(),
      color: newAnalyst.color,
    }
    await briefingApi.createAnalyst(data)
    setNewAnalyst({ name: '', display_name: '', color: '#c9a962' })
    setShowAddAnalyst(false)
    fetchAnalysts()
  }

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-8">
      <h1
        className="text-xl sm:text-2xl font-light"
        style={{ fontFamily: 'var(--bf-font-display)', color: 'var(--bf-text)' }}
      >
        簡報設定
      </h1>

      {/* ── Topics Section ── */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2
            className="text-xs uppercase tracking-widest flex items-center gap-2"
            style={{ color: 'var(--bf-text-tertiary)' }}
          >
            <Palette size={14} />
            主題管理
          </h2>
          <button
            onClick={() => setShowAddTopic(!showAddTopic)}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 border transition-colors"
            style={{ borderColor: 'var(--bf-accent)', color: 'var(--bf-accent)' }}
          >
            <Plus size={12} />
            新增主題
          </button>
        </div>

        {showAddTopic && (
          <div
            className="border p-4 space-y-3"
            style={{ backgroundColor: 'var(--bf-bg-elevated)', borderColor: 'var(--bf-border)' }}
          >
            <div className="grid grid-cols-2 gap-3">
              <input
                type="text"
                value={newTopic.name}
                onChange={(e) => setNewTopic({ ...newTopic, name: e.target.value })}
                placeholder="英文代碼 (如 weather)"
                className="bg-transparent text-sm outline-none border-b py-1.5 placeholder:opacity-40"
                style={{ color: 'var(--bf-text)', borderColor: 'var(--bf-border)' }}
              />
              <input
                type="text"
                value={newTopic.display_name}
                onChange={(e) => setNewTopic({ ...newTopic, display_name: e.target.value })}
                placeholder="顯示名稱 (如 天氣)"
                className="bg-transparent text-sm outline-none border-b py-1.5 placeholder:opacity-40"
                style={{ color: 'var(--bf-text)', borderColor: 'var(--bf-border)' }}
              />
            </div>
            <input
              type="text"
              value={newTopic.description}
              onChange={(e) => setNewTopic({ ...newTopic, description: e.target.value })}
              placeholder="描述（選填）"
              className="w-full bg-transparent text-sm outline-none border-b py-1.5 placeholder:opacity-40"
              style={{ color: 'var(--bf-text)', borderColor: 'var(--bf-border)' }}
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowAddTopic(false)}
                className="text-xs px-3 py-1.5"
                style={{ color: 'var(--bf-text-muted)' }}
              >
                取消
              </button>
              <button
                onClick={handleAddTopic}
                disabled={!newTopic.name.trim() || !newTopic.display_name.trim()}
                className="text-xs px-3 py-1.5 border disabled:opacity-30"
                style={{ borderColor: 'var(--bf-accent)', color: 'var(--bf-accent)' }}
              >
                新增
              </button>
            </div>
          </div>
        )}

        <div className="space-y-2">
          {topics.map((t) => (
            <TopicCard key={t.id} topic={t} onRefresh={fetchTopics} />
          ))}
          {topics.length === 0 && (
            <div
              className="border p-6 text-center text-sm"
              style={{
                backgroundColor: 'var(--bf-bg-elevated)',
                borderColor: 'var(--bf-border)',
                color: 'var(--bf-text-dim)',
              }}
            >
              尚未設定任何主題
            </div>
          )}
        </div>
      </section>

      {/* ── Analysts Section ── */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2
            className="text-xs uppercase tracking-widest flex items-center gap-2"
            style={{ color: 'var(--bf-text-tertiary)' }}
          >
            <Users size={14} />
            分析師管理
          </h2>
          <button
            onClick={() => setShowAddAnalyst(!showAddAnalyst)}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 border transition-colors"
            style={{ borderColor: 'var(--bf-accent)', color: 'var(--bf-accent)' }}
          >
            <Plus size={12} />
            新增分析師
          </button>
        </div>

        {showAddAnalyst && (
          <div
            className="border p-4 space-y-3"
            style={{ backgroundColor: 'var(--bf-bg-elevated)', borderColor: 'var(--bf-border)' }}
          >
            <div className="grid grid-cols-2 gap-3">
              <input
                type="text"
                value={newAnalyst.name}
                onChange={(e) => setNewAnalyst({ ...newAnalyst, name: e.target.value })}
                placeholder="英文代碼 (如 claude)"
                className="bg-transparent text-sm outline-none border-b py-1.5 placeholder:opacity-40"
                style={{ color: 'var(--bf-text)', borderColor: 'var(--bf-border)' }}
              />
              <input
                type="text"
                value={newAnalyst.display_name}
                onChange={(e) => setNewAnalyst({ ...newAnalyst, display_name: e.target.value })}
                placeholder="顯示名稱 (如 Claude)"
                className="bg-transparent text-sm outline-none border-b py-1.5 placeholder:opacity-40"
                style={{ color: 'var(--bf-text)', borderColor: 'var(--bf-border)' }}
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs" style={{ color: 'var(--bf-text-muted)' }}>代表色</label>
              <input
                type="color"
                value={newAnalyst.color}
                onChange={(e) => setNewAnalyst({ ...newAnalyst, color: e.target.value })}
                className="w-8 h-8 cursor-pointer border-0 bg-transparent"
              />
              <span className="text-xs" style={{ color: 'var(--bf-text-dim)' }}>{newAnalyst.color}</span>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowAddAnalyst(false)}
                className="text-xs px-3 py-1.5"
                style={{ color: 'var(--bf-text-muted)' }}
              >
                取消
              </button>
              <button
                onClick={handleAddAnalyst}
                disabled={!newAnalyst.name.trim() || !newAnalyst.display_name.trim()}
                className="text-xs px-3 py-1.5 border disabled:opacity-30"
                style={{ borderColor: 'var(--bf-accent)', color: 'var(--bf-accent)' }}
              >
                新增
              </button>
            </div>
          </div>
        )}

        <div className="space-y-2">
          {analysts.map((a) => (
            <AnalystCard key={a.id} analyst={a} onRefresh={fetchAnalysts} />
          ))}
          {analysts.length === 0 && (
            <div
              className="border p-6 text-center text-sm"
              style={{
                backgroundColor: 'var(--bf-bg-elevated)',
                borderColor: 'var(--bf-border)',
                color: 'var(--bf-text-dim)',
              }}
            >
              尚未設定任何分析師
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

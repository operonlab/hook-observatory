import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronUp,
  Loader2,
  Palette,
  Play,
  Plus,
  Settings,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { briefingApi } from '../api/client'
import { useAnalysts, useTopics } from '../hooks/useBriefing'
import { useInvalidateBriefing, useRunStatusQuery } from '../hooks/queries'
import type {
  Analyst,
  AnalystCreate,
  BriefingSubtopicCreate,
  BriefingTopic,
  BriefingTopicCreate,
  BriefingTopicUpdate,
  SearchConfig,
} from '../types'

/* ── Shared: ToggleSwitch ── */
function ToggleSwitch({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
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

/* ── Shared: inline text input for config fields ── */
const cfgInputClass =
  'w-full bg-transparent text-sm outline-none border-b py-1.5 placeholder:opacity-40'
const cfgInputStyle = {
  color: 'var(--bf-text)',
  borderColor: 'var(--bf-border)',
  caretColor: 'var(--bf-accent)',
}
const cfgTextareaClass =
  'w-full bg-transparent text-sm outline-none border py-2 px-3 placeholder:opacity-40 resize-y min-h-[60px]'
const cfgTextareaStyle = {
  color: 'var(--bf-text)',
  borderColor: 'var(--bf-border)',
  caretColor: 'var(--bf-accent)',
  backgroundColor: 'var(--bf-bg-surface)',
}
const cfgLabelClass = 'text-[10px] uppercase tracking-widest mb-1 block'
const cfgLabelStyle = { color: 'var(--bf-text-dim)' }

/* ── City Editor (for weather topic_type) ── */
function CityEditor({
  cities,
  onChange,
}: {
  cities: { name_en: string; name_cn: string }[]
  onChange: (cities: { name_en: string; name_cn: string }[]) => void
}) {
  const [draft, setDraft] = useState({ name_en: '', name_cn: '' })

  const addCity = () => {
    if (!draft.name_en.trim() || !draft.name_cn.trim()) return
    onChange([...cities, { name_en: draft.name_en.trim(), name_cn: draft.name_cn.trim() }])
    setDraft({ name_en: '', name_cn: '' })
  }

  const removeCity = (idx: number) => {
    onChange(cities.filter((_, i) => i !== idx))
  }

  return (
    <div className="space-y-2">
      <span className={cfgLabelClass} style={cfgLabelStyle}>
        城市列表
      </span>
      {cities.map((c, i) => (
        <div key={`${c.name_en}-${i}`} className="flex items-center gap-2">
          <span className="text-sm flex-1" style={{ color: 'var(--bf-text-secondary)' }}>
            {c.name_cn} ({c.name_en})
          </span>
          <button
            type="button"
            onClick={() => removeCity(i)}
            className="p-1"
            style={{ color: 'var(--bf-text-dim)' }}
          >
            <X size={12} />
          </button>
        </div>
      ))}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft.name_en}
          onChange={(e) => setDraft({ ...draft, name_en: e.target.value })}
          placeholder="English name"
          className="flex-1 bg-transparent text-xs outline-none border-b py-1 placeholder:opacity-40"
          style={cfgInputStyle}
        />
        <input
          type="text"
          value={draft.name_cn}
          onChange={(e) => setDraft({ ...draft, name_cn: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === 'Enter') addCity()
          }}
          placeholder="中文名"
          className="flex-1 bg-transparent text-xs outline-none border-b py-1 placeholder:opacity-40"
          style={cfgInputStyle}
        />
        <button
          type="button"
          onClick={addCity}
          disabled={!draft.name_en.trim() || !draft.name_cn.trim()}
          className="p-1 disabled:opacity-30"
          style={{ color: 'var(--bf-accent)' }}
        >
          <Plus size={14} />
        </button>
      </div>
    </div>
  )
}

/* ── ContentPrioritiesEditor ── */
function ContentPrioritiesEditor({
  priorities,
  onChange,
}: {
  priorities: string[]
  onChange: (priorities: string[]) => void
}) {
  const [draft, setDraft] = useState('')

  const addPriority = () => {
    if (!draft.trim()) return
    onChange([...priorities, draft.trim()])
    setDraft('')
  }

  const removePriority = (idx: number) => {
    onChange(priorities.filter((_, i) => i !== idx))
  }

  const movePriority = (idx: number, dir: -1 | 1) => {
    const target = idx + dir
    if (target < 0 || target >= priorities.length) return
    const next = [...priorities]
    ;[next[idx], next[target]] = [next[target], next[idx]]
    onChange(next)
  }

  return (
    <div className="space-y-2">
      <span className={cfgLabelClass} style={cfgLabelStyle}>
        內容優先級
      </span>
      {priorities.map((p, i) => (
        <div key={`${p}-${i}`} className="flex items-center gap-2">
          <div className="flex flex-col">
            <button
              type="button"
              onClick={() => movePriority(i, -1)}
              disabled={i === 0}
              className="p-0.5 disabled:opacity-20"
              style={{ color: 'var(--bf-text-muted)' }}
            >
              <ArrowUp size={10} />
            </button>
            <button
              type="button"
              onClick={() => movePriority(i, 1)}
              disabled={i === priorities.length - 1}
              className="p-0.5 disabled:opacity-20"
              style={{ color: 'var(--bf-text-muted)' }}
            >
              <ArrowDown size={10} />
            </button>
          </div>
          <span className="text-sm flex-1" style={{ color: 'var(--bf-text-secondary)' }}>
            {p}
          </span>
          <button
            type="button"
            onClick={() => removePriority(i)}
            className="p-1"
            style={{ color: 'var(--bf-text-dim)' }}
          >
            <X size={12} />
          </button>
        </div>
      ))}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') addPriority()
          }}
          placeholder="新增優先項..."
          className="flex-1 bg-transparent text-xs outline-none border-b py-1 placeholder:opacity-40"
          style={cfgInputStyle}
        />
        <button
          type="button"
          onClick={addPriority}
          disabled={!draft.trim()}
          className="p-1 disabled:opacity-30"
          style={{ color: 'var(--bf-accent)' }}
        >
          <Plus size={14} />
        </button>
      </div>
    </div>
  )
}

/* ── TopicCard (expanded) ── */
function TopicCard({ topic, onRefresh }: { topic: BriefingTopic; onRefresh: () => void }) {
  const [open, setOpen] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [newSubtopic, setNewSubtopic] = useState('')

  const searchConfig: SearchConfig = topic.search_config || {}

  const handleToggle = async () => {
    await briefingApi.toggleTopic(topic.id)
    onRefresh()
  }

  const handleDelete = async () => {
    await briefingApi.deleteTopic(topic.id)
    onRefresh()
  }

  const handleUpdate = async (changes: BriefingTopicUpdate) => {
    await briefingApi.updateTopic(topic.id, changes)
    onRefresh()
  }

  const handleSearchConfigChange = async (patch: Partial<SearchConfig>) => {
    const updated = { ...searchConfig, ...patch }
    await handleUpdate({ search_config: updated })
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

  const topicType = topic.topic_type || 'news'

  return (
    <div
      className="border"
      style={{ backgroundColor: 'var(--bf-bg-elevated)', borderColor: 'var(--bf-border)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 sm:px-5 py-3">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 flex-1 text-left"
        >
          <span style={{ color: 'var(--bf-text-muted)' }}>
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
          <span className="text-sm font-medium" style={{ color: 'var(--bf-text)' }}>
            {topic.display_name}
          </span>
          <span className="text-[10px]" style={{ color: 'var(--bf-text-dim)' }}>
            {topic.name}
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 border"
            style={{ borderColor: 'var(--bf-border)', color: 'var(--bf-text-dim)' }}
          >
            {topicType}
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
            type="button"
            onClick={handleDelete}
            className="p-1 transition-colors"
            style={{ color: 'var(--bf-text-muted)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = '#f87171'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--bf-text-muted)'
            }}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Expanded */}
      {open && (
        <div
          className="px-4 sm:px-5 pb-4 space-y-4 border-t"
          style={{ borderColor: 'var(--bf-border)' }}
        >
          {/* Topic Type Radio */}
          <div className="pt-3">
            <span className={cfgLabelClass} style={cfgLabelStyle}>
              主題類型
            </span>
            <div className="flex items-center gap-4">
              {(['news', 'weather'] as const).map((t) => (
                <label key={t} className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name={`topic-type-${topic.id}`}
                    checked={topicType === t}
                    onChange={() => handleUpdate({ topic_type: t })}
                    className="accent-[var(--bf-accent)]"
                  />
                  <span className="text-sm" style={{ color: 'var(--bf-text-secondary)' }}>
                    {t === 'news' ? '新聞' : '天氣'}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* Search Config: search_query_en */}
          <div>
            <span className={cfgLabelClass} style={cfgLabelStyle}>
              搜尋關鍵字 (英文)
            </span>
            <input
              type="text"
              defaultValue={searchConfig.search_query_en || ''}
              onBlur={(e) => handleSearchConfigChange({ search_query_en: e.target.value })}
              placeholder="e.g. AI chip semiconductor"
              className={cfgInputClass}
              style={cfgInputStyle}
            />
          </div>

          {/* Search Config: focus_areas */}
          <div>
            <span className={cfgLabelClass} style={cfgLabelStyle}>
              關注領域
            </span>
            <textarea
              defaultValue={searchConfig.focus_areas || ''}
              onBlur={(e) => handleSearchConfigChange({ focus_areas: e.target.value })}
              placeholder="描述關注的面向..."
              className={cfgTextareaClass}
              style={cfgTextareaStyle}
              rows={2}
            />
          </div>

          {/* Search Config: subreddits */}
          <div>
            <span className={cfgLabelClass} style={cfgLabelStyle}>
              Subreddits
            </span>
            <input
              type="text"
              defaultValue={searchConfig.subreddits || ''}
              onBlur={(e) => handleSearchConfigChange({ subreddits: e.target.value })}
              placeholder="e.g. technology,programming,machinelearning"
              className={cfgInputClass}
              style={cfgInputStyle}
            />
          </div>

          {/* Weather-specific: cities + content_priorities */}
          {topicType === 'weather' && (
            <>
              <CityEditor
                cities={searchConfig.cities || []}
                onChange={(cities) => handleSearchConfigChange({ cities })}
              />
              <ContentPrioritiesEditor
                priorities={searchConfig.content_priorities || []}
                onChange={(content_priorities) => handleSearchConfigChange({ content_priorities })}
              />
            </>
          )}

          {/* Priority reorder */}
          <div className="flex items-center gap-2">
            <span className={cfgLabelClass} style={cfgLabelStyle}>
              排序
            </span>
            <span className="text-xs tabular-nums" style={{ color: 'var(--bf-text-secondary)' }}>
              #{topic.priority}
            </span>
            <button
              type="button"
              onClick={() => handleUpdate({ priority: Math.max(0, topic.priority - 1) })}
              disabled={topic.priority <= 0}
              className="p-0.5 disabled:opacity-20"
              style={{ color: 'var(--bf-text-muted)' }}
            >
              <ArrowUp size={12} />
            </button>
            <button
              type="button"
              onClick={() => handleUpdate({ priority: topic.priority + 1 })}
              className="p-0.5"
              style={{ color: 'var(--bf-text-muted)' }}
            >
              <ArrowDown size={12} />
            </button>
          </div>

          {/* Description */}
          {topic.description && (
            <p className="text-xs" style={{ color: 'var(--bf-text-muted)' }}>
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
                  type="button"
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
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={newSubtopic}
              onChange={(e) => setNewSubtopic(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddSubtopic()
              }}
              placeholder="新增子項..."
              className="flex-1 bg-transparent text-sm outline-none border-b py-1 placeholder:opacity-40"
              style={cfgInputStyle}
            />
            <button
              type="button"
              onClick={handleAddSubtopic}
              disabled={!newSubtopic.trim()}
              className="p-1 disabled:opacity-30"
              style={{ color: 'var(--bf-accent)' }}
            >
              <Plus size={14} />
            </button>
          </div>

          {/* Advanced: prompt_template (collapsible) */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest"
              style={{ color: 'var(--bf-text-dim)' }}
            >
              <Settings size={10} />
              進階設定
              {showAdvanced ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            </button>
            {showAdvanced && (
              <div className="mt-2">
                <span className={cfgLabelClass} style={cfgLabelStyle}>
                  提示詞模板
                </span>
                <textarea
                  defaultValue={topic.prompt_template || ''}
                  onBlur={(e) => handleUpdate({ prompt_template: e.target.value || undefined })}
                  placeholder="自訂提示詞模板..."
                  className={cfgTextareaClass}
                  style={cfgTextareaStyle}
                  rows={4}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── AnalystCard (expanded) ── */
function AnalystCard({ analyst, onRefresh }: { analyst: Analyst; onRefresh: () => void }) {
  const [open, setOpen] = useState(false)

  const handleToggle = async () => {
    await briefingApi.toggleAnalyst(analyst.id)
    onRefresh()
  }

  const handleDelete = async () => {
    await briefingApi.deleteAnalyst(analyst.id)
    onRefresh()
  }

  const handleUpdate = async (
    changes: Partial<Pick<Analyst, 'model_id' | 'system_prompt' | 'cli_command'>>,
  ) => {
    await briefingApi.updateAnalyst(analyst.id, changes)
    onRefresh()
  }

  return (
    <div
      className="border"
      style={{
        backgroundColor: 'var(--bf-bg-elevated)',
        borderColor: 'var(--bf-border)',
        borderLeftWidth: 3,
        borderLeftColor: analyst.color,
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 sm:px-5 py-3">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-3 flex-1 text-left"
        >
          <div
            className="w-7 h-7 flex items-center justify-center text-[10px] font-bold shrink-0"
            style={{ backgroundColor: analyst.color, color: 'var(--bf-bg)' }}
          >
            {analyst.display_name.charAt(0)}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium" style={{ color: 'var(--bf-text)' }}>
              {analyst.display_name}
            </span>
            {analyst.model_id && (
              <span className="text-[10px]" style={{ color: 'var(--bf-text-dim)' }}>
                {analyst.model_id}
              </span>
            )}
            {analyst.cli_command && (
              <span
                className="text-[10px] px-1.5 py-0.5 border"
                style={{ borderColor: 'var(--bf-border)', color: 'var(--bf-text-dim)' }}
              >
                {analyst.cli_command}
              </span>
            )}
          </div>
        </button>
        <div className="flex items-center gap-3">
          <ToggleSwitch enabled={analyst.enabled} onToggle={handleToggle} />
          <button
            type="button"
            onClick={handleDelete}
            className="p-1 transition-colors"
            style={{ color: 'var(--bf-text-muted)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = '#f87171'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--bf-text-muted)'
            }}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Expanded details */}
      {open && (
        <div
          className="px-4 sm:px-5 pb-4 space-y-3 border-t"
          style={{ borderColor: 'var(--bf-border)' }}
        >
          {/* model_id */}
          <div className="pt-3">
            <span className={cfgLabelClass} style={cfgLabelStyle}>
              模型 ID
            </span>
            <input
              type="text"
              defaultValue={analyst.model_id || ''}
              onBlur={(e) => handleUpdate({ model_id: e.target.value || null })}
              placeholder="e.g. claude-sonnet-4-20250514"
              className={cfgInputClass}
              style={cfgInputStyle}
            />
          </div>

          {/* system_prompt */}
          <div>
            <span className={cfgLabelClass} style={cfgLabelStyle}>
              系統提示詞
            </span>
            <textarea
              defaultValue={analyst.system_prompt || ''}
              onBlur={(e) => handleUpdate({ system_prompt: e.target.value || null })}
              placeholder="設定分析師的角色與行為..."
              className={cfgTextareaClass}
              style={cfgTextareaStyle}
              rows={4}
            />
          </div>

          {/* cli_command */}
          <div>
            <span className={cfgLabelClass} style={cfgLabelStyle}>
              CLI 工具
            </span>
            <select
              value={analyst.cli_command || ''}
              onChange={(e) => handleUpdate({ cli_command: e.target.value || null })}
              className="w-full bg-transparent text-sm outline-none border py-1.5 px-2 cursor-pointer"
              style={{
                color: 'var(--bf-text)',
                borderColor: 'var(--bf-border)',
                backgroundColor: 'var(--bf-bg-surface)',
              }}
            >
              <option value="">無</option>
              <option value="claude">claude</option>
              <option value="codex">codex</option>
              <option value="gemini">gemini</option>
            </select>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Run Status Badge ── */
function RunStatusBadge() {
  const { data: runStatus } = useRunStatusQuery()

  if (!runStatus) return null

  const statusColor =
    runStatus.status === 'completed'
      ? 'var(--bf-confidence-high)'
      : runStatus.status === 'running'
        ? 'var(--bf-accent)'
        : 'var(--bf-text-dim)'

  const isRunning =
    runStatus.status === 'running' || runStatus.topics?.some((t) => t.status === 'processing')

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <span
        className={`text-[10px] px-2 py-0.5 border ${isRunning ? 'bf-status-pulse' : ''}`}
        style={{ borderColor: statusColor, color: statusColor }}
      >
        {runStatus.status}
      </span>
      <span className="text-[10px]" style={{ color: 'var(--bf-text-dim)' }}>
        {runStatus.date}
      </span>
      {runStatus.topics?.map((t) => (
        <span
          key={t.id}
          className={`text-[10px] px-1.5 py-0.5 border ${t.status === 'processing' ? 'bf-status-pulse' : ''}`}
          style={{
            borderColor:
              t.status === 'completed'
                ? 'var(--bf-confidence-high)'
                : t.status === 'failed'
                  ? 'var(--bf-confidence-low)'
                  : 'var(--bf-border)',
            color:
              t.status === 'completed'
                ? 'var(--bf-confidence-high)'
                : t.status === 'failed'
                  ? 'var(--bf-confidence-low)'
                  : 'var(--bf-text-dim)',
          }}
        >
          {t.domain}
        </span>
      ))}
    </div>
  )
}

/* ── Main Page ── */
export default function BriefingConfig() {
  const { topics, fetchTopics } = useTopics()
  const { analysts, fetchAnalysts } = useAnalysts()
  const { invalidateRunStatus } = useInvalidateBriefing()
  const [showAddTopic, setShowAddTopic] = useState(false)
  const [showAddAnalyst, setShowAddAnalyst] = useState(false)
  const [newTopic, setNewTopic] = useState({ name: '', display_name: '', description: '' })
  const [newAnalyst, setNewAnalyst] = useState({ name: '', display_name: '', color: '#c9a962' })
  const [triggering, setTriggering] = useState(false)

  const handleTriggerGeneration = async () => {
    setTriggering(true)
    try {
      await briefingApi.triggerGeneration()
      invalidateRunStatus()
    } catch {
      // handled by store
    } finally {
      setTriggering(false)
    }
  }

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
      {/* Title + Trigger */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <h1
          className="text-xl sm:text-2xl font-light"
          style={{ fontFamily: 'var(--bf-font-display)', color: 'var(--bf-text)' }}
        >
          簡報設定
        </h1>
        <button
          type="button"
          onClick={handleTriggerGeneration}
          disabled={triggering}
          className="flex items-center gap-2 text-xs px-3 py-1.5 border transition-colors disabled:opacity-50"
          style={{
            borderColor: 'var(--bf-accent)',
            color: 'var(--bf-text-on-accent)',
            backgroundColor: 'var(--bf-accent)',
          }}
        >
          {triggering ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          立即生成
        </button>
      </div>

      {/* Run Status */}
      <RunStatusBadge />

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
            type="button"
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
                type="button"
                onClick={() => setShowAddTopic(false)}
                className="text-xs px-3 py-1.5"
                style={{ color: 'var(--bf-text-muted)' }}
              >
                取消
              </button>
              <button
                type="button"
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
            type="button"
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
              <label
                className="text-xs flex items-center gap-2"
                style={{ color: 'var(--bf-text-muted)' }}
              >
                代表色
                <input
                  type="color"
                  value={newAnalyst.color}
                  onChange={(e) => setNewAnalyst({ ...newAnalyst, color: e.target.value })}
                  className="w-8 h-8 cursor-pointer border-0 bg-transparent"
                />
              </label>
              <span className="text-xs" style={{ color: 'var(--bf-text-dim)' }}>
                {newAnalyst.color}
              </span>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowAddAnalyst(false)}
                className="text-xs px-3 py-1.5"
                style={{ color: 'var(--bf-text-muted)' }}
              >
                取消
              </button>
              <button
                type="button"
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

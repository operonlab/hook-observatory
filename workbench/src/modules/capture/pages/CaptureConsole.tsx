import { MessageSquare, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { type Capture, type CaptureStats, captureApi } from '../api'
import CaptureList from '../components/CaptureList'
import EnrichmentChat from '../components/EnrichmentChat'

export default function CaptureConsole() {
  const [allCaptures, setAllCaptures] = useState<Capture[]>([])
  const [stats, setStats] = useState<CaptureStats | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [moduleFilter, setModuleFilter] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('pending')
  const [chatOpen, setChatOpen] = useState(true)
  const [refreshKey, setRefreshKey] = useState(0)

  const reload = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  // Fetch all captures for current status (no module filter — done client-side)
  useEffect(() => {
    captureApi
      .list({ status: statusFilter, limit: 100 })
      .then(setAllCaptures)
      .catch(() => {})
    captureApi
      .stats()
      .then(setStats)
      .catch(() => {})
  }, [refreshKey, statusFilter])

  // Client-side module filtering — instant tab switch
  const captures = moduleFilter ? allCaptures.filter((c) => c.module === moduleFilter) : allCaptures

  const selected = selectedId ? (captures.find((c) => c.id === selectedId) ?? null) : null

  const handlePromote = async (id: string) => {
    const result = await captureApi.promote(id)
    if (result.success) {
      setSelectedId(null)
      reload()
    }
    return result
  }

  const handleDelete = async (id: string) => {
    await captureApi.delete(id)
    if (selectedId === id) setSelectedId(null)
    reload()
  }

  const handleUpdate = async (id: string, payload: Record<string, unknown>) => {
    await captureApi.update(id, { payload })
    reload()
  }

  const handleCaptureCreated = () => {
    reload()
  }

  return (
    <div className="h-[calc(100vh-3.5rem)] flex flex-col">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{ borderColor: 'var(--surface0)' }}
      >
        <div className="flex items-center gap-3">
          <h1 className="text-base font-medium" style={{ color: 'var(--text)' }}>
            快速捕捉
          </h1>
          {stats && (
            <div className="flex items-center gap-2">
              <span
                className="text-xs px-2 py-0.5 rounded-full"
                style={{ backgroundColor: 'var(--surface0)', color: 'var(--yellow)' }}
              >
                {stats.by_status.pending ?? 0} 待處理
              </span>
              <span
                className="text-xs px-2 py-0.5 rounded-full"
                style={{ backgroundColor: 'var(--surface0)', color: 'var(--green)' }}
              >
                {stats.by_status.promoted ?? 0} 已提升
              </span>
            </div>
          )}
        </div>

        {/* Mobile chat toggle */}
        <button
          type="button"
          className="lg:hidden flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs"
          style={{ backgroundColor: 'var(--surface0)', color: 'var(--text)' }}
          onClick={() => setChatOpen(!chatOpen)}
        >
          {chatOpen ? <X size={14} /> : <MessageSquare size={14} />}
          {chatOpen ? '列表' : '對話'}
        </button>
      </div>

      {/* Module filter tabs */}
      <div
        className="flex items-center gap-1 px-4 py-2 border-b shrink-0 overflow-x-auto"
        style={{ borderColor: 'var(--surface0)' }}
      >
        {[
          { key: null, label: '全部' },
          { key: 'finance', label: '記帳', color: '#a6e3a1' },
          { key: 'taskflow', label: '任務', color: '#cba6f7' },
          { key: 'invest', label: '投資', color: '#f38ba8' },
          { key: 'dailyos', label: '日程', color: '#89b4fa' },
          { key: 'ideagraph', label: '靈感', color: '#f9e2af' },
          { key: 'intelflow', label: '情報', color: '#94e2d5' },
        ].map((tab) => (
          <button
            key={tab.key ?? 'all'}
            type="button"
            onClick={() => setModuleFilter(tab.key)}
            className="px-3 py-1 text-xs rounded-md whitespace-nowrap transition-colors"
            style={{
              backgroundColor:
                moduleFilter === tab.key ? (tab.color ?? 'var(--accent)') : 'transparent',
              color: moduleFilter === tab.key ? 'var(--base)' : (tab.color ?? 'var(--subtext0)'),
              fontWeight: moduleFilter === tab.key ? 600 : 400,
              opacity: moduleFilter === tab.key ? 1 : 0.8,
            }}
          >
            {tab.label}
            {stats && tab.key && stats.by_module[tab.key] ? (
              <span className="ml-1 opacity-70">({stats.by_module[tab.key]})</span>
            ) : null}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-1">
          {(['pending', 'promoted', 'expired'] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className="px-2 py-1 text-[11px] rounded transition-colors"
              style={{
                backgroundColor: statusFilter === s ? 'var(--surface1)' : 'transparent',
                color: statusFilter === s ? 'var(--text)' : 'var(--overlay0)',
              }}
            >
              {{ pending: '待處理', promoted: '已提升', expired: '已過期' }[s]}
            </button>
          ))}
        </div>
      </div>

      {/* Two-panel body */}
      <div className="flex-1 flex min-h-0">
        {/* Left: Capture list */}
        <div
          className={`${chatOpen ? 'hidden lg:flex' : 'flex'} flex-col flex-1 lg:flex-none lg:w-[420px] border-r min-h-0`}
          style={{ borderColor: 'var(--surface0)' }}
        >
          <CaptureList
            captures={captures}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onPromote={handlePromote}
            onDelete={handleDelete}
            onUpdate={handleUpdate}
          />
        </div>

        {/* Right: Enrichment chat */}
        <div
          className={`${chatOpen ? 'flex' : 'hidden lg:flex'} flex-col flex-1 min-h-0`}
          style={{ backgroundColor: 'var(--mantle)' }}
        >
          <EnrichmentChat
            selectedCapture={selected}
            moduleFilter={moduleFilter}
            onCaptureCreated={handleCaptureCreated}
            onUpdate={handleUpdate}
            onPromote={handlePromote}
          />
        </div>
      </div>
    </div>
  )
}

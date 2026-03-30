import { type ReactNode, useCallback, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { MemoryBlock } from '@/types'
import { memvaultApi, type SyncScanResult, type SyncStats } from '../api'
import AttitudeTimeline from '../components/AttitudeTimeline'
import BlockTypeFilter from '../components/BlockTypeFilter'
import CascadeSearchBar from '../components/CascadeSearchBar'
import InfoTip from '../components/InfoTip'
import KgExplorerPanel from '../components/KgExplorerPanel'
import MemoryCard from '../components/MemoryCard'
import ProfileWidget from '../components/ProfileWidget'
import SearchBar from '../components/SearchBar'
import SkillDashboard from '../components/SkillDashboard'
import { useDeleteBlock } from '../hooks/mutations'
import { useBlocks, useProfile } from '../hooks/queries'
import { useMemorySearch } from '../hooks/useMemorySearch'
import { useMemvaultStore } from '../stores'
import type { BrowserTab } from '../types'

const TABS: { key: BrowserTab; label: string }[] = [
  { key: 'blocks', label: '記憶區塊' },
  { key: 'kg-explorer', label: '知識圖譜' },
  { key: 'skills', label: '成長追蹤' },
]

function CollapsibleSection({
  title,
  color,
  defaultOpen = true,
  info,
  children,
}: {
  title: string
  color: string
  defaultOpen?: boolean
  info?: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div
      className="rounded-xl border"
      style={{
        borderColor: open ? color : 'var(--surface0)',
      }}
    >
      <div
        className="flex items-center gap-2 w-full px-3 py-3 sm:px-4 transition-colors"
        style={{
          backgroundColor: open ? `color-mix(in srgb, ${color} 6%, transparent)` : 'var(--mantle)',
          borderRadius: open ? '0.75rem 0.75rem 0 0' : '0.75rem',
        }}
      >
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 text-left flex-1 min-h-[44px]"
        >
          <span
            className="text-xs transition-transform duration-200"
            style={{
              color,
              display: 'inline-block',
              transform: open ? 'rotate(0deg)' : 'rotate(-90deg)',
            }}
          >
            ▼
          </span>
          <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
            {title}
          </span>
        </button>
        {info && <InfoTip text={info} />}
        <div className="flex-1" />
      </div>
      {open && <div className="px-3 pb-4 sm:px-4">{children}</div>}
    </div>
  )
}

function ViewToggle({
  mode,
  onChange,
}: {
  mode: 'grid' | 'list'
  onChange: (m: 'grid' | 'list') => void
}) {
  return (
    <div
      className="flex rounded-lg overflow-hidden border"
      style={{ borderColor: 'var(--surface0)' }}
    >
      {(['grid', 'list'] as const).map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className="px-3 py-1.5 text-xs font-medium transition-colors"
          style={{
            backgroundColor: mode === m ? 'var(--surface0)' : 'var(--mantle)',
            color: mode === m ? 'var(--text)' : 'var(--subtext0)',
            minHeight: 44,
          }}
        >
          {m === 'grid' ? '卡片' : '列表'}
        </button>
      ))}
    </div>
  )
}

function Pagination({
  page,
  total,
  pageSize,
  onPageChange,
}: {
  page: number
  total: number
  pageSize: number
  onPageChange: (p: number) => void
}) {
  const totalPages = Math.ceil(total / pageSize)
  if (totalPages <= 1) return null

  return (
    <div className="flex items-center justify-center gap-2 mt-6">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="rounded-lg px-3 py-2 text-sm transition-colors"
        style={{
          backgroundColor: 'var(--surface0)',
          color: page <= 1 ? 'var(--subtext0)' : 'var(--text)',
          cursor: page <= 1 ? 'not-allowed' : 'pointer',
          opacity: page <= 1 ? 0.5 : 1,
          minHeight: 44,
          minWidth: 44,
        }}
      >
        上一頁
      </button>
      <span className="text-sm" style={{ color: 'var(--subtext0)' }}>
        {page} / {totalPages}
      </span>
      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="rounded-lg px-3 py-2 text-sm transition-colors"
        style={{
          backgroundColor: 'var(--surface0)',
          color: page >= totalPages ? 'var(--subtext0)' : 'var(--text)',
          cursor: page >= totalPages ? 'not-allowed' : 'pointer',
          opacity: page >= totalPages ? 0.5 : 1,
          minHeight: 44,
          minWidth: 44,
        }}
      >
        下一頁
      </button>
    </div>
  )
}

function SyncWidget({ onSynced }: { onSynced?: () => void }) {
  const [stats, setStats] = useState<SyncStats | null>(null)
  const [scanning, setScanning] = useState(false)
  const [lastResult, setLastResult] = useState<SyncScanResult | null>(null)

  const fetchStats = useCallback(async () => {
    try {
      setStats(await memvaultApi.syncStats())
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  const runScan = async () => {
    setScanning(true)
    setLastResult(null)
    try {
      const result = await memvaultApi.syncScan()
      setLastResult(result)
      await fetchStats()
      if (result.synced > 0) onSynced?.()
    } catch {
      /* ignore */
    } finally {
      setScanning(false)
    }
  }

  return (
    <div
      className="rounded-xl border p-4"
      style={{ backgroundColor: 'var(--mantle)', borderColor: 'var(--surface0)' }}
    >
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text)' }}>
        Session 掃描
      </h3>

      {stats && (
        <div className="grid grid-cols-2 gap-2 mb-3 text-xs" style={{ color: 'var(--subtext0)' }}>
          <div className="flex justify-between">
            <span>已收錄</span>
            <span style={{ color: 'var(--green)' }}>{stats.synced}</span>
          </div>
          <div className="flex justify-between">
            <span>Session 數</span>
            <span style={{ color: 'var(--text)' }}>{stats.total}</span>
          </div>
          <div className="flex justify-between">
            <span>失敗</span>
            <span style={{ color: stats.failed > 0 ? 'var(--red)' : 'var(--subtext0)' }}>
              {stats.failed}
            </span>
          </div>
          <div className="flex justify-between">
            <span>略過</span>
            <span>{stats.skipped}</span>
          </div>
        </div>
      )}

      <button
        onClick={runScan}
        disabled={scanning}
        className="w-full rounded-lg px-3 py-2.5 text-sm font-medium transition-colors"
        style={{
          backgroundColor: scanning ? 'var(--surface0)' : 'var(--blue)',
          color: scanning ? 'var(--subtext0)' : 'var(--base)',
          cursor: scanning ? 'wait' : 'pointer',
          minHeight: 44,
        }}
      >
        {scanning ? '掃描中...' : '掃描 Session'}
      </button>

      {lastResult && (
        <p className="mt-2 text-xs" style={{ color: 'var(--subtext0)' }}>
          {lastResult.synced > 0
            ? `新收錄 ${lastResult.synced} 筆記憶`
            : `全部已收錄 (${lastResult.already} 筆)`}
          {lastResult.failed > 0 && (
            <span style={{ color: 'var(--red)' }}> / {lastResult.failed} 失敗</span>
          )}
        </p>
      )}
    </div>
  )
}

function BlockDetailDrawer({ block, onClose }: { block: MemoryBlock; onClose: () => void }) {
  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40"
        style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
        onClick={onClose}
      />
      {/* Bottom sheet */}
      <div
        className="fixed bottom-0 left-0 right-0 z-50 rounded-t-2xl border-t p-5 max-h-[70vh] overflow-y-auto"
        style={{
          backgroundColor: 'var(--mantle)',
          borderColor: 'var(--surface0)',
        }}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
            記憶詳情
          </h3>
          <button
            onClick={onClose}
            className="flex items-center justify-center rounded-lg text-sm"
            style={{ color: 'var(--subtext0)', minWidth: 44, minHeight: 44 }}
          >
            關閉
          </button>
        </div>

        <p className="text-sm leading-relaxed mb-3" style={{ color: 'var(--text)' }}>
          {block.content}
        </p>

        <div className="flex flex-col gap-2 text-xs" style={{ color: 'var(--subtext0)' }}>
          <div className="flex justify-between">
            <span>類型</span>
            <span style={{ color: 'var(--text)' }}>{block.block_type}</span>
          </div>
          <div className="flex justify-between">
            <span>信心度</span>
            <span style={{ color: 'var(--text)' }}>{Math.round(block.confidence * 100)}%</span>
          </div>
          {block.source_session && (
            <div className="flex justify-between">
              <span>來源工作階段</span>
              <span className="truncate max-w-[160px]" style={{ color: 'var(--text)' }}>
                {block.source_session}
              </span>
            </div>
          )}
          {block.tags.length > 0 && (
            <div>
              <span className="block mb-1">標籤</span>
              <div className="flex flex-wrap gap-1">
                {block.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded px-2 py-0.5"
                    style={{
                      backgroundColor: 'var(--surface0)',
                      color: 'var(--subtext0)',
                    }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}

export default function MemoryBrowser() {
  const {
    page,
    pageSize,
    selectedBlock,
    viewMode,
    filters,
    selectBlock,
    setPage,
    setFilters,
    setViewMode,
    kg_activeTab,
    setKgActiveTab,
  } = useMemvaultStore()

  const blocksQuery = useBlocks(page, pageSize, filters)
  const profileQuery = useProfile()
  const queryClient = useQueryClient()
  const deleteBlockMutation = useDeleteBlock()

  const blocks = blocksQuery.data?.items ?? []
  const total = blocksQuery.data?.total ?? 0

  const handleDeleteBlock = (id: string) => {
    if (!window.confirm('確定要刪除這筆記憶嗎？')) return
    deleteBlockMutation.mutate(id, {
      onSuccess: () => {
        if (selectedBlock?.id === id) selectBlock(null)
      },
    })
  }

  const { query, results, isSearching, setQuery, searchNow, clear } = useMemorySearch()

  const [showSidebar, setShowSidebar] = useState(false)

  const showSearchResults = query.trim() && results.length > 0
  const displayBlocks = showSearchResults ? results.map((r) => r.block) : blocks

  return (
    <div className="mx-auto max-w-7xl px-3 py-4 sm:px-4 sm:py-5 lg:px-6 lg:py-6">
      {/* View controls */}
      <div className="flex items-center justify-between mb-4 gap-2">
        {kg_activeTab === 'blocks' && <ViewToggle mode={viewMode} onChange={setViewMode} />}
        {/* Mobile: KAS Profile / Sync button */}
        <button
          onClick={() => setShowSidebar(true)}
          className="lg:hidden flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors ml-auto"
          style={{
            backgroundColor: 'var(--surface0)',
            color: 'var(--subtext0)',
            minHeight: 44,
          }}
        >
          KAS 狀態
        </button>
      </div>

      {/* Tab Bar */}
      <div
        className="flex gap-0 mb-4 sm:mb-6 rounded-lg overflow-hidden border"
        style={{ borderColor: 'var(--surface0)' }}
      >
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setKgActiveTab(tab.key)}
            className="flex-1 px-2 py-2.5 sm:px-4 text-xs sm:text-sm font-medium transition-colors"
            style={{
              backgroundColor: kg_activeTab === tab.key ? 'var(--surface0)' : 'var(--mantle)',
              color: kg_activeTab === tab.key ? 'var(--text)' : 'var(--subtext0)',
              minHeight: 44,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex gap-4 lg:gap-6">
        {/* Main content */}
        <div className="flex-1 min-w-0">
          {/* Error */}
          {blocksQuery.error && (
            <div
              className="rounded-lg border px-4 py-3 mb-4 text-sm"
              style={{
                backgroundColor: 'color-mix(in srgb, var(--red) 10%, transparent)',
                borderColor: 'var(--red)',
                color: 'var(--red)',
              }}
            >
              {blocksQuery.error instanceof Error
                ? blocksQuery.error.message
                : 'Failed to fetch blocks'}
            </div>
          )}

          {/* === Blocks Tab === */}
          {kg_activeTab === 'blocks' && (
            <>
              {/* Search */}
              <div className="mb-4">
                <SearchBar
                  value={query}
                  onChange={setQuery}
                  onSearch={searchNow}
                  loading={isSearching}
                  resultCount={showSearchResults ? results.length : undefined}
                  onClear={clear}
                />
              </div>

              {/* Filters */}
              {!showSearchResults && (
                <div className="mb-4">
                  <BlockTypeFilter
                    activeType={filters.blockType}
                    onChange={(type) => setFilters({ blockType: type as typeof filters.blockType })}
                  />
                </div>
              )}

              {/* Loading — only show spinner on initial load */}
              {blocksQuery.isLoading && (
                <div className="flex items-center justify-center py-20">
                  <div
                    className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
                    style={{ borderColor: 'var(--blue)', borderTopColor: 'transparent' }}
                  />
                </div>
              )}

              {/* Empty state */}
              {!blocksQuery.isLoading && displayBlocks.length === 0 && (
                <div className="flex flex-col items-center justify-center py-16 gap-2">
                  <p className="text-base" style={{ color: 'var(--subtext0)' }}>
                    {showSearchResults ? '未找到相關記憶' : '尚無記憶區塊'}
                  </p>
                  <p className="text-sm text-center px-4" style={{ color: 'var(--subtext1)' }}>
                    {showSearchResults
                      ? '試試不同的搜尋關鍵字'
                      : '記憶區塊將在 Session 結束後自動提煉'}
                  </p>
                </div>
              )}

              {/* Block list */}
              {displayBlocks.length > 0 && (
                <div
                  className={
                    viewMode === 'grid'
                      ? 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4'
                      : 'flex flex-col gap-2'
                  }
                >
                  {displayBlocks.map((block) => (
                    <MemoryCard
                      key={block.id}
                      block={block}
                      compact={viewMode === 'list'}
                      onClick={() => selectBlock(block)}
                      onDelete={handleDeleteBlock}
                    />
                  ))}
                </div>
              )}

              {/* Pagination */}
              {!showSearchResults && (
                <Pagination page={page} total={total} pageSize={pageSize} onPageChange={setPage} />
              )}
            </>
          )}

          {/* === KG Explorer Tab === */}
          {kg_activeTab === 'kg-explorer' && (
            <>
              <div className="mb-4">
                <CascadeSearchBar />
              </div>
              <KgExplorerPanel />
            </>
          )}

          {/* === Skills Tab === */}
          {kg_activeTab === 'skills' && (
            <div className="space-y-4">
              <CollapsibleSection
                title="技能熟練度"
                color="var(--green)"
                info={
                  '熟練度 = 調用次數 × 成功率 × 時效因子\n時效因子：最後使用距今 90 天內從 1.0 線性衰減至 0.1，超過 90 天固定 0.1。\n\n長條長度 = 熟練度分數，百分比 = 成功率。\n點擊卡片展開調用歷史，每項技能旁的 ? 查看技能說明。'
                }
              >
                <SkillDashboard />
              </CollapsibleSection>
              <CollapsibleSection
                title="態度演進"
                color="var(--mauve)"
                info={
                  '態度（Attitudes）是從對話中自動提煉的偏好與工作原則。\n\n9 種分類：workflow, tool_behavior, config, architecture, preference, technical, naming, syntax, performance\n\n每條態度有信心度（0~1，隨時間衰減）。相同主題的新態度會取代舊版本，形成版本鏈記錄完整演進歷程。\n來源：session 對話直接萃取 + 知識三元組修正回饋。'
                }
              >
                <AttitudeTimeline />
              </CollapsibleSection>
            </div>
          )}
        </div>

        {/* Desktop Sidebar */}
        <div className="hidden lg:flex lg:w-72 lg:flex-col lg:gap-4 lg:shrink-0">
          <ProfileWidget profile={profileQuery.data ?? null} loading={profileQuery.isLoading} />
          <SyncWidget
            onSynced={() => queryClient.invalidateQueries({ queryKey: ['memvault', 'blocks'] })}
          />

          {/* Block detail panel (desktop) */}
          {selectedBlock && (
            <div
              className="rounded-xl border p-5"
              style={{
                backgroundColor: 'var(--mantle)',
                borderColor: 'var(--surface0)',
              }}
            >
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                  記憶詳情
                </h3>
                <button
                  onClick={() => selectBlock(null)}
                  className="text-xs py-1 px-2"
                  style={{ color: 'var(--subtext0)' }}
                >
                  關閉
                </button>
              </div>

              <p className="text-sm leading-relaxed mb-3" style={{ color: 'var(--text)' }}>
                {selectedBlock.content}
              </p>

              <div className="flex flex-col gap-2 text-xs" style={{ color: 'var(--subtext0)' }}>
                <div className="flex justify-between">
                  <span>類型</span>
                  <span style={{ color: 'var(--text)' }}>{selectedBlock.block_type}</span>
                </div>
                <div className="flex justify-between">
                  <span>信心度</span>
                  <span style={{ color: 'var(--text)' }}>
                    {Math.round(selectedBlock.confidence * 100)}%
                  </span>
                </div>
                {selectedBlock.source_session && (
                  <div className="flex justify-between">
                    <span>來源工作階段</span>
                    <span className="truncate max-w-[120px]" style={{ color: 'var(--text)' }}>
                      {selectedBlock.source_session}
                    </span>
                  </div>
                )}
                {selectedBlock.tags.length > 0 && (
                  <div>
                    <span className="block mb-1">標籤</span>
                    <div className="flex flex-wrap gap-1">
                      {selectedBlock.tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded px-2 py-0.5"
                          style={{
                            backgroundColor: 'var(--surface0)',
                            color: 'var(--subtext0)',
                          }}
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Mobile: Block detail bottom sheet */}
      {selectedBlock && (
        <div className="lg:hidden">
          <BlockDetailDrawer block={selectedBlock} onClose={() => selectBlock(null)} />
        </div>
      )}

      {/* Mobile: KAS sidebar bottom sheet */}
      {showSidebar && (
        <>
          <div
            className="lg:hidden fixed inset-0 z-40"
            style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
            onClick={() => setShowSidebar(false)}
          />
          <div
            className="lg:hidden fixed bottom-0 left-0 right-0 z-50 rounded-t-2xl border-t p-5 max-h-[80vh] overflow-y-auto"
            style={{
              backgroundColor: 'var(--mantle)',
              borderColor: 'var(--surface0)',
            }}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
                KAS 狀態
              </h3>
              <button
                onClick={() => setShowSidebar(false)}
                className="flex items-center justify-center rounded-lg text-sm"
                style={{ color: 'var(--subtext0)', minWidth: 44, minHeight: 44 }}
              >
                關閉
              </button>
            </div>
            <div className="space-y-4">
              <ProfileWidget profile={profileQuery.data ?? null} loading={profileQuery.isLoading} />
              <SyncWidget
                onSynced={() => {
                  queryClient.invalidateQueries({ queryKey: ['memvault', 'blocks'] })
                  setShowSidebar(false)
                }}
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

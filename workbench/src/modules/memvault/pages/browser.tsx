import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMemvaultStore } from "../stores";
import { useMemorySearch } from "../hooks/useMemorySearch";
import { memvaultApi, type SyncScanResult, type SyncStats } from "../api";
import MemoryCard from "../components/MemoryCard";
import SearchBar from "../components/SearchBar";
import ProfileWidget from "../components/ProfileWidget";
import BlockTypeFilter from "../components/BlockTypeFilter";

function ViewToggle({
  mode,
  onChange,
}: {
  mode: "grid" | "list";
  onChange: (m: "grid" | "list") => void;
}) {
  return (
    <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: "var(--surface0)" }}>
      {(["grid", "list"] as const).map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className="px-3 py-1.5 text-xs font-medium transition-colors"
          style={{
            backgroundColor: mode === m ? "var(--surface0)" : "var(--mantle)",
            color: mode === m ? "var(--text)" : "var(--subtext0)",
          }}
        >
          {m === "grid" ? "卡片" : "列表"}
        </button>
      ))}
    </div>
  );
}

function Pagination({
  page,
  total,
  pageSize,
  onPageChange,
}: {
  page: number;
  total: number;
  pageSize: number;
  onPageChange: (p: number) => void;
}) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-2 mt-6">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="rounded-lg px-3 py-1.5 text-sm transition-colors"
        style={{
          backgroundColor: "var(--surface0)",
          color: page <= 1 ? "var(--subtext0)" : "var(--text)",
          cursor: page <= 1 ? "not-allowed" : "pointer",
          opacity: page <= 1 ? 0.5 : 1,
        }}
      >
        上一頁
      </button>
      <span className="text-sm" style={{ color: "var(--subtext0)" }}>
        {page} / {totalPages}
      </span>
      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="rounded-lg px-3 py-1.5 text-sm transition-colors"
        style={{
          backgroundColor: "var(--surface0)",
          color: page >= totalPages ? "var(--subtext0)" : "var(--text)",
          cursor: page >= totalPages ? "not-allowed" : "pointer",
          opacity: page >= totalPages ? 0.5 : 1,
        }}
      >
        下一頁
      </button>
    </div>
  );
}

function SyncWidget({ onSynced }: { onSynced?: () => void }) {
  const [stats, setStats] = useState<SyncStats | null>(null);
  const [scanning, setScanning] = useState(false);
  const [lastResult, setLastResult] = useState<SyncScanResult | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      setStats(await memvaultApi.syncStats());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => { fetchStats(); }, [fetchStats]);

  const runScan = async () => {
    setScanning(true);
    setLastResult(null);
    try {
      const result = await memvaultApi.syncScan();
      setLastResult(result);
      await fetchStats();
      if (result.synced > 0) onSynced?.();
    } catch {
      /* ignore */
    } finally {
      setScanning(false);
    }
  };

  return (
    <div
      className="rounded-xl border p-4"
      style={{ backgroundColor: "var(--mantle)", borderColor: "var(--surface0)" }}
    >
      <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text)" }}>
        Session 掃描
      </h3>

      {stats && (
        <div className="grid grid-cols-2 gap-2 mb-3 text-xs" style={{ color: "var(--subtext0)" }}>
          <div className="flex justify-between">
            <span>已收錄</span>
            <span style={{ color: "var(--green)" }}>{stats.synced}</span>
          </div>
          <div className="flex justify-between">
            <span>Session 數</span>
            <span style={{ color: "var(--text)" }}>{stats.total}</span>
          </div>
          <div className="flex justify-between">
            <span>失敗</span>
            <span style={{ color: stats.failed > 0 ? "var(--red)" : "var(--subtext0)" }}>
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
        className="w-full rounded-lg px-3 py-2 text-xs font-medium transition-colors"
        style={{
          backgroundColor: scanning ? "var(--surface0)" : "var(--blue)",
          color: scanning ? "var(--subtext0)" : "var(--base)",
          cursor: scanning ? "wait" : "pointer",
        }}
      >
        {scanning ? "掃描中..." : "掃描 Session"}
      </button>

      {lastResult && (
        <p className="mt-2 text-xs" style={{ color: "var(--subtext0)" }}>
          {lastResult.synced > 0
            ? `新收錄 ${lastResult.synced} 筆記憶`
            : `全部已收錄 (${lastResult.already} 筆)`}
          {lastResult.failed > 0 && (
            <span style={{ color: "var(--red)" }}> / {lastResult.failed} 失敗</span>
          )}
        </p>
      )}
    </div>
  );
}

export default function MemoryBrowser() {
  const navigate = useNavigate();
  const {
    blocks,
    total,
    page,
    pageSize,
    selectedBlock,
    profile,
    viewMode,
    filters,
    loading,
    error,
    fetchBlocks,
    fetchProfile,
    selectBlock,
    setPage,
    setFilters,
    setViewMode,
  } = useMemvaultStore();

  const { query, results, isSearching, setQuery, searchNow, clear } =
    useMemorySearch();

  useEffect(() => {
    fetchBlocks();
    fetchProfile();
  }, [fetchBlocks, fetchProfile]);

  const showSearchResults = query.trim() && results.length > 0;
  const displayBlocks = showSearchResults ? results.map((r) => r.block) : blocks;

  return (
    <div className="mx-auto max-w-6xl p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
          記憶金庫
        </h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate("/memvault/galaxy")}
            className="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
            style={{ backgroundColor: "var(--surface0)", color: "var(--subtext0)" }}
          >
            星系圖
          </button>
          <ViewToggle mode={viewMode} onChange={setViewMode} />
        </div>
      </div>

      <div className="flex gap-6">
        {/* Main content */}
        <div className="flex-1 min-w-0">
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

          {/* Error */}
          {error && (
            <div
              className="rounded-lg border px-4 py-3 mb-4 text-sm"
              style={{
                backgroundColor: "color-mix(in srgb, var(--red) 10%, transparent)",
                borderColor: "var(--red)",
                color: "var(--red)",
              }}
            >
              {error}
            </div>
          )}

          {/* Loading */}
          {loading && !blocks.length && (
            <div className="flex items-center justify-center py-20">
              <div
                className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
                style={{ borderColor: "var(--blue)", borderTopColor: "transparent" }}
              />
            </div>
          )}

          {/* Empty state */}
          {!loading && displayBlocks.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 gap-2">
              <p className="text-lg" style={{ color: "var(--subtext0)" }}>
                {showSearchResults ? "未找到相關記憶" : "尚無記憶區塊"}
              </p>
              <p className="text-sm" style={{ color: "var(--subtext1)" }}>
                {showSearchResults
                  ? "試試不同的搜尋關鍵字"
                  : "記憶區塊將在 Session 結束後自動提煉"}
              </p>
            </div>
          )}

          {/* Block list */}
          {displayBlocks.length > 0 && (
            <div
              className={
                viewMode === "grid"
                  ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
                  : "flex flex-col gap-2"
              }
            >
              {displayBlocks.map((block) => (
                <MemoryCard
                  key={block.id}
                  block={block}
                  compact={viewMode === "list"}
                  onClick={() => selectBlock(block)}
                />
              ))}
            </div>
          )}

          {/* Pagination */}
          {!showSearchResults && (
            <Pagination
              page={page}
              total={total}
              pageSize={pageSize}
              onPageChange={setPage}
            />
          )}
        </div>

        {/* Sidebar */}
        <div className="hidden lg:flex lg:w-72 lg:flex-col lg:gap-4 lg:shrink-0">
          <ProfileWidget profile={profile} loading={loading && !profile} />
          <SyncWidget onSynced={() => fetchBlocks()} />

          {/* Block detail panel */}
          {selectedBlock && (
            <div
              className="rounded-xl border p-5"
              style={{
                backgroundColor: "var(--mantle)",
                borderColor: "var(--surface0)",
              }}
            >
              <div className="flex items-center justify-between mb-3">
                <h3
                  className="text-sm font-semibold"
                  style={{ color: "var(--text)" }}
                >
                  記憶詳情
                </h3>
                <button
                  onClick={() => selectBlock(null)}
                  className="text-xs"
                  style={{ color: "var(--subtext0)" }}
                >
                  關閉
                </button>
              </div>

              <p
                className="text-sm leading-relaxed mb-3"
                style={{ color: "var(--text)" }}
              >
                {selectedBlock.content}
              </p>

              <div className="flex flex-col gap-2 text-xs" style={{ color: "var(--subtext0)" }}>
                <div className="flex justify-between">
                  <span>類型</span>
                  <span style={{ color: "var(--text)" }}>{selectedBlock.block_type}</span>
                </div>
                <div className="flex justify-between">
                  <span>信心度</span>
                  <span style={{ color: "var(--text)" }}>
                    {Math.round(selectedBlock.confidence * 100)}%
                  </span>
                </div>
                {selectedBlock.source_session && (
                  <div className="flex justify-between">
                    <span>來源工作階段</span>
                    <span
                      className="truncate max-w-[120px]"
                      style={{ color: "var(--text)" }}
                    >
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
                            backgroundColor: "var(--surface0)",
                            color: "var(--subtext0)",
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
    </div>
  );
}

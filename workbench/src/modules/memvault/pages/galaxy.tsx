import { useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useMemvaultStore } from "../stores";
import { useGalaxy } from "../hooks/useGalaxy";
import GalaxyCanvas from "../components/GalaxyCanvas";
import { BLOCK_TYPE_CONFIG } from "../types";
import type { GalaxyNode } from "../types";
import type { MemoryBlock } from "@/types";

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins} 分鐘前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小時前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return `${Math.floor(days / 30)} 個月前`;
}

function hexToRgba(cssVar: string, alpha: number): string {
  return `color-mix(in srgb, ${cssVar} ${Math.round(alpha * 100)}%, transparent)`;
}

function BlockDetailPanel({
  block,
  onClose,
}: {
  block: MemoryBlock;
  onClose: () => void;
}) {
  const config = BLOCK_TYPE_CONFIG[block.block_type] ?? BLOCK_TYPE_CONFIG.general;
  const confidencePct = `${Math.round(block.confidence * 100)}%`;

  return (
    <div
      className="flex flex-col h-full border-l overflow-hidden"
      style={{
        width: 360,
        minWidth: 360,
        backgroundColor: "var(--mantle)",
        borderColor: "var(--surface0)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{ borderColor: "var(--surface0)" }}
      >
        <div className="flex items-center gap-2">
          <span
            className="rounded-full px-2.5 py-0.5 text-xs font-medium"
            style={{
              backgroundColor: hexToRgba(config.color, 0.18),
              color: config.color,
              border: `1px solid ${config.color}`,
            }}
          >
            {config.label}
          </span>
          <span className="text-sm font-semibold" style={{ color: config.color }}>
            {confidencePct}
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded-md px-2 py-1 text-xs transition-colors"
          style={{ color: "var(--subtext0)" }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = "var(--surface0)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = "transparent";
          }}
        >
          關閉
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        <div>
          <p
            className="text-sm leading-relaxed whitespace-pre-wrap"
            style={{ color: "var(--text)" }}
          >
            {block.content}
          </p>
        </div>

        {/* Tags */}
        {block.tags.length > 0 && (
          <div>
            <h4
              className="text-xs font-medium mb-2 uppercase tracking-wider"
              style={{ color: "var(--subtext0)" }}
            >
              標籤
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {block.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded px-2 py-0.5 text-xs"
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

        {/* Meta */}
        <div
          className="space-y-1.5 pt-2 border-t text-xs"
          style={{ borderColor: "var(--surface0)", color: "var(--subtext1)" }}
        >
          {block.source_session && (
            <p>
              <span style={{ color: "var(--subtext0)" }}>來源：</span>
              {block.source_session.slice(0, 8)}...
            </p>
          )}
          <p>
            <span style={{ color: "var(--subtext0)" }}>建立：</span>
            {relativeTime(block.created_at)}
          </p>
          <p>
            <span style={{ color: "var(--subtext0)" }}>更新：</span>
            {relativeTime(block.updated_at)}
          </p>
        </div>
      </div>
    </div>
  );
}

export default function GalaxyPage() {
  const navigate = useNavigate();
  const { blocks, fetchBlocks, loading, selectBlock, selectedBlock } =
    useMemvaultStore();
  const { nodes, links } = useGalaxy(blocks);

  useEffect(() => {
    if (blocks.length === 0) fetchBlocks();
  }, [blocks.length, fetchBlocks]);

  const handleNodeClick = useCallback(
    (node: GalaxyNode) => {
      const block = blocks.find((b) => b.id === node.id);
      if (block) {
        if (selectedBlock?.id === block.id) {
          selectBlock(null);
        } else {
          selectBlock(block);
        }
      }
    },
    [blocks, selectBlock, selectedBlock],
  );

  const handleEmptyClick = useCallback(() => {
    selectBlock(null);
  }, [selectBlock]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate("/memvault")}
            className="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
            style={{
              backgroundColor: "var(--surface0)",
              color: "var(--subtext0)",
            }}
          >
            返回列表
          </button>
          <h1
            className="text-xl font-bold"
            style={{ color: "var(--text)" }}
          >
            KAS 星系圖
          </h1>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3">
          <span className="text-xs" style={{ color: "var(--subtext0)" }}>
            拖曳旋轉 | 滾輪縮放 | 點擊查看 | 拖曳節點固定 | 右鍵解除固定
          </span>
          <span
            className="mx-1 h-3 border-l"
            style={{ borderColor: "var(--surface0)" }}
          />
          {(
            Object.entries(BLOCK_TYPE_CONFIG) as [
              string,
              { label: string; color: string },
            ][]
          ).map(([type, config]) => (
            <div key={type} className="flex items-center gap-1.5">
              <span
                className="inline-block h-3 w-3 rounded-full"
                style={{ backgroundColor: config.color }}
              />
              <span
                className="text-xs"
                style={{ color: "var(--subtext0)" }}
              >
                {config.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Stats bar */}
      <div className="flex items-center gap-4 mb-4 shrink-0">
        <span className="text-xs" style={{ color: "var(--subtext0)" }}>
          {nodes.length} 個節點
        </span>
        <span className="text-xs" style={{ color: "var(--subtext0)" }}>
          {links.length} 個連結
        </span>
        {selectedBlock && (
          <span className="text-xs" style={{ color: "var(--blue)" }}>
            已選：{selectedBlock.content.slice(0, 40)}...
          </span>
        )}
      </div>

      {/* Canvas + Detail panel */}
      <div className="flex flex-1 min-h-0 gap-0">
        <div className="flex-1 min-h-0 relative rounded-xl overflow-hidden border"
          style={{ borderColor: "var(--surface0)" }}
        >
          {loading && nodes.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <div
                className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
                style={{
                  borderColor: "var(--blue)",
                  borderTopColor: "transparent",
                }}
              />
            </div>
          ) : nodes.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <p
                className="text-sm"
                style={{ color: "var(--subtext0)" }}
              >
                尚無記憶區塊可視覺化
              </p>
            </div>
          ) : (
            <GalaxyCanvas
              nodes={nodes}
              links={links}
              onNodeClick={handleNodeClick}
              onEmptyClick={handleEmptyClick}
              selectedNodeId={selectedBlock?.id ?? null}
            />
          )}
        </div>

        {/* Detail panel */}
        {selectedBlock && (
          <BlockDetailPanel
            block={selectedBlock}
            onClose={() => selectBlock(null)}
          />
        )}
      </div>
    </div>
  );
}

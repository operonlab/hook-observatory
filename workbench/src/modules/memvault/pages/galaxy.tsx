import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useMemvaultStore } from "../stores";
import { useGalaxy } from "../hooks/useGalaxy";
import GalaxyCanvas from "../components/GalaxyCanvas";
import { BLOCK_TYPE_CONFIG } from "../types";
import type { GalaxyNode } from "../types";

export default function GalaxyPage() {
  const navigate = useNavigate();
  const { blocks, fetchBlocks, loading, selectBlock } = useMemvaultStore();
  const { nodes, links } = useGalaxy(blocks);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });

  useEffect(() => {
    if (blocks.length === 0) fetchBlocks();
  }, [blocks.length, fetchBlocks]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setSize({
          width: Math.floor(entry.contentRect.width),
          height: Math.floor(entry.contentRect.height),
        });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const handleNodeClick = useCallback(
    (node: GalaxyNode) => {
      const block = blocks.find((b) => b.id === node.id);
      if (block) {
        selectBlock(block);
        navigate("/memvault");
      }
    },
    [blocks, selectBlock, navigate],
  );

  const selectedBlock = useMemvaultStore((s) => s.selectedBlock);

  return (
    <div className="flex flex-col h-full p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate("/memvault")}
            className="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
            style={{ backgroundColor: "var(--surface0)", color: "var(--subtext0)" }}
          >
            返回列表
          </button>
          <h1 className="text-xl font-bold" style={{ color: "var(--text)" }}>
            KAS 星系圖
          </h1>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3">
          {(Object.entries(BLOCK_TYPE_CONFIG) as [string, { label: string; color: string }][]).map(
            ([type, config]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-3 w-3 rounded-full"
                  style={{ backgroundColor: config.color }}
                />
                <span className="text-xs" style={{ color: "var(--subtext0)" }}>
                  {config.label}
                </span>
              </div>
            ),
          )}
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

      {/* Canvas area */}
      <div ref={containerRef} className="flex-1 min-h-0 relative rounded-xl overflow-hidden border" style={{ borderColor: "var(--surface0)" }}>
        {loading && nodes.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div
              className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
              style={{ borderColor: "var(--blue)", borderTopColor: "transparent" }}
            />
          </div>
        ) : nodes.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm" style={{ color: "var(--subtext0)" }}>
              尚無記憶區塊可視覺化
            </p>
          </div>
        ) : (
          <GalaxyCanvas
            nodes={nodes}
            links={links}
            width={size.width}
            height={size.height}
            onNodeClick={handleNodeClick}
          />
        )}
      </div>
    </div>
  );
}

import type { MemoryBlock } from "@/types";
import { BLOCK_TYPE_CONFIG } from "../types";

interface MemoryCardProps {
  block: MemoryBlock;
  onClick?: () => void;
  compact?: boolean;
}

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

export default function MemoryCard({ block, onClick, compact = false }: MemoryCardProps) {
  const config = BLOCK_TYPE_CONFIG[block.block_type] ?? BLOCK_TYPE_CONFIG.general;
  const confidencePct = `${Math.round(block.confidence * 100)}%`;
  const badgeBg = hexToRgba(config.color, 0.18);

  if (compact) {
    return (
      <div
        onClick={onClick}
        className="flex items-center gap-3 rounded-lg border px-3 py-2 cursor-pointer transition-colors"
        style={{
          backgroundColor: "var(--mantle)",
          borderColor: "var(--surface0)",
        }}
      >
        <span
          className="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
          style={{
            backgroundColor: badgeBg,
            color: config.color,
            border: `1px solid ${config.color}`,
          }}
        >
          {config.label}
        </span>

        <span
          className="flex-1 truncate text-sm"
          style={{ color: "var(--text)" }}
        >
          {block.content}
        </span>

        <div className="flex shrink-0 items-center gap-1.5">
          {block.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="rounded px-1.5 py-0.5 text-xs"
              style={{ backgroundColor: "var(--surface0)", color: "var(--subtext0)" }}
            >
              {tag}
            </span>
          ))}
        </div>

        <span className="shrink-0 text-xs font-medium" style={{ color: config.color }}>
          {confidencePct}
        </span>

        <span className="shrink-0 text-xs" style={{ color: "var(--subtext1)" }}>
          {relativeTime(block.updated_at)}
        </span>
      </div>
    );
  }

  return (
    <div
      onClick={onClick}
      className="rounded-xl border p-4 cursor-pointer transition-all duration-200"
      style={{
        backgroundColor: "var(--mantle)",
        borderColor: "var(--surface0)",
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget;
        el.style.transform = "scale(1.02)";
        el.style.borderColor = config.color;
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget;
        el.style.transform = "scale(1)";
        el.style.borderColor = "var(--surface0)";
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <span
          className="rounded-full px-2.5 py-0.5 text-xs font-medium"
          style={{
            backgroundColor: badgeBg,
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

      <p
        className="text-sm leading-relaxed mb-3 line-clamp-3"
        style={{ color: "var(--text)" }}
      >
        {block.content}
      </p>

      {block.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {block.tags.map((tag) => (
            <span
              key={tag}
              className="rounded px-2 py-0.5 text-xs"
              style={{ backgroundColor: "var(--surface0)", color: "var(--subtext0)" }}
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <p className="text-xs" style={{ color: "var(--subtext1)" }}>
        {relativeTime(block.updated_at)}
      </p>
    </div>
  );
}

import { useState } from "react";
import type { HookEvent } from "../api/client.ts";

interface Props {
  events: HookEvent[];
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
  onFilterChange: (filters: { event_type?: string; session_id?: string }) => void;
  eventTypes: string[];
}

const TYPE_COLORS: Record<string, string> = {
  PreToolUse: "#89b4fa",
  PostToolUse: "#74c7ec",
  Stop: "#f38ba8",
  SessionStart: "#a6e3a1",
  SessionEnd: "#f9e2af",
  UserPromptSubmit: "#cba6f7",
  SubagentStart: "#94e2d5",
  SubagentStop: "#eba0ac",
  PreCompact: "#fab387",
};

export default function EventTable({
  events,
  total,
  limit,
  offset,
  onPageChange,
  onFilterChange,
  eventTypes,
}: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ backgroundColor: "#12121a", border: "1px solid rgba(255, 255, 255, 0.04)" }}
    >
      {/* Filters */}
      <div className="flex items-center gap-3 px-5 py-3" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
        <select
          className="rounded bg-surface-3 px-2 py-1 text-xs text-white/60 outline-none"
          onChange={(e) => onFilterChange({ event_type: e.target.value || undefined })}
          defaultValue=""
        >
          <option value="">全部類型</option>
          {eventTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <span className="ml-auto text-[11px] text-white/20">
          共 {total.toLocaleString()} 筆
        </span>
      </div>

      {/* Table */}
      <div className="divide-y divide-white/[0.03]">
        {events.map((evt) => {
          const isExpanded = expandedId === evt.id;
          const typeColor = TYPE_COLORS[evt.event_type] || "#a6adc8";
          return (
            <div key={evt.id}>
              <button
                className="flex w-full items-center gap-4 px-5 py-2.5 text-left transition-colors hover:bg-white/[0.02]"
                onClick={() => setExpandedId(isExpanded ? null : evt.id)}
              >
                <span
                  className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium"
                  style={{ backgroundColor: typeColor + "18", color: typeColor }}
                >
                  {evt.event_type}
                </span>
                {evt.tool_name && (
                  <span className="text-[11px] text-white/40 font-mono">{evt.tool_name}</span>
                )}
                <span className="ml-auto text-[10px] text-white/20 shrink-0">
                  {new Date(evt.created_at).toLocaleString("zh-TW")}
                </span>
                <span className="text-[10px] text-white/15">{isExpanded ? "▼" : "▶"}</span>
              </button>
              {isExpanded && (
                <div className="px-5 pb-3">
                  <pre
                    className="rounded bg-surface-0 p-3 text-[11px] text-white/50 overflow-x-auto max-h-60"
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    {JSON.stringify(evt.payload, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          );
        })}
        {events.length === 0 && (
          <div className="px-5 py-10 text-center text-xs text-white/20">
            尚無事件
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}
        >
          <button
            className="text-xs text-white/30 hover:text-white/60 disabled:opacity-30"
            disabled={currentPage <= 1}
            onClick={() => onPageChange(offset - limit)}
          >
            上一頁
          </button>
          <span className="text-[11px] text-white/20">
            {currentPage} / {totalPages}
          </span>
          <button
            className="text-xs text-white/30 hover:text-white/60 disabled:opacity-30"
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange(offset + limit)}
          >
            下一頁
          </button>
        </div>
      )}
    </div>
  );
}

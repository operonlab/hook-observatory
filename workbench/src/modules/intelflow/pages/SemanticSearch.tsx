import { useState } from "react";
import { Search as SearchIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useSearch } from "../hooks/useIntelflow";

export default function SemanticSearch() {
  const { query, results, loading, setQuery, search, clear } = useSearch();
  const [input, setInput] = useState(query);
  const navigate = useNavigate();

  const handleSearch = () => {
    if (input.trim()) search(input.trim());
  };

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-5 sm:space-y-6">
      {/* Header */}
      <div>
        <h1
          className="text-2xl sm:text-3xl font-light"
          style={{ fontFamily: "var(--if-font-display)", color: "var(--if-text)" }}
        >
          語義搜尋
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--if-text-dim)" }}>
          透過語義相似度搜尋研究報告
        </p>
      </div>

      {/* Search bar */}
      <div
        className="flex items-center gap-2 sm:gap-3 border px-3 sm:px-4 py-3"
        style={{
          backgroundColor: "var(--if-bg-elevated)",
          borderColor: "var(--if-border)",
        }}
      >
        <SearchIcon size={16} style={{ color: "var(--if-text-muted)", flexShrink: 0 }} />
        <input
          type="text"
          placeholder="輸入關鍵字或語句..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--if-text-dim)] min-w-0"
          style={{ color: "var(--if-text)" }}
        />
        <button
          onClick={handleSearch}
          disabled={loading || !input.trim()}
          className="px-3 sm:px-4 py-2 text-xs border transition-colors disabled:opacity-30 shrink-0 min-h-[36px]"
          style={{
            borderColor: "var(--if-accent)",
            color: "var(--if-accent)",
          }}
          onMouseEnter={(e) => {
            if (!loading && input.trim()) {
              e.currentTarget.style.backgroundColor = "var(--if-accent)";
              e.currentTarget.style.color = "var(--if-text-on-accent)";
            }
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = "transparent";
            e.currentTarget.style.color = "var(--if-accent)";
          }}
        >
          {loading ? "搜尋中..." : "搜尋"}
        </button>
      </div>

      {/* Results */}
      {results.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs" style={{ color: "var(--if-text-tertiary)" }}>
              找到 {results.length} 筆相關結果
            </span>
            <button
              onClick={() => {
                clear();
                setInput("");
              }}
              className="text-xs min-h-[36px] px-2 transition-colors"
              style={{ color: "var(--if-text-dim)" }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "var(--if-text-secondary)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "var(--if-text-dim)";
              }}
            >
              清除結果
            </button>
          </div>

          {results.map((r) => {
            const scoreColor =
              r.score >= 0.7
                ? "var(--if-score-high)"
                : r.score >= 0.4
                  ? "var(--if-score-mid)"
                  : "var(--if-score-low)";
            const scoreBg =
              r.score >= 0.7
                ? "var(--if-score-high-bg)"
                : r.score >= 0.4
                  ? "var(--if-score-mid-bg)"
                  : "var(--if-score-low-bg)";

            return (
              <button
                key={r.report.id}
                onClick={() => navigate(`/intelflow/reports/${r.report.id}`)}
                className="flex w-full items-center gap-3 sm:gap-4 border px-4 sm:px-5 py-4 text-left transition-colors min-h-[60px]"
                style={{
                  backgroundColor: "var(--if-bg-elevated)",
                  borderColor: "var(--if-border)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--if-accent)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--if-border)";
                }}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm leading-snug" style={{ color: "var(--if-text)" }}>
                    {r.report.title}
                  </p>
                  <p className="text-xs mt-1" style={{ color: "var(--if-text-dim)" }}>
                    {new Date(r.report.created_at).toLocaleDateString("zh-TW")}
                    {r.report.tags.length > 0 && ` · ${r.report.tags.slice(0, 3).join(", ")}`}
                  </p>
                </div>
                <span
                  className="shrink-0 px-2 sm:px-2.5 py-1 text-xs font-medium"
                  style={{ backgroundColor: scoreBg, color: scoreColor }}
                >
                  {Math.round(r.score * 100)}%
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Empty state */}
      {!loading && results.length === 0 && query && (
        <div className="py-12 text-center text-sm" style={{ color: "var(--if-text-dim)" }}>
          無搜尋結果
        </div>
      )}
    </div>
  );
}

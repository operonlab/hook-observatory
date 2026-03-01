import type { SummaryStats, HealthResponse } from "../api/client.ts";

interface Props {
  summary: SummaryStats | null;
  health: HealthResponse | null;
}

const cards = [
  { key: "total" as const, label: "總事件數", color: "#89b4fa" },
  { key: "today" as const, label: "今日事件", color: "#a6e3a1" },
  { key: "unique_sessions" as const, label: "Sessions", color: "#cba6f7" },
];

export default function StatsOverview({ summary, health }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {cards.map((c) => (
        <div
          key={c.key}
          className="rounded-lg p-5"
          style={{
            backgroundColor: "#12121a",
            border: "1px solid rgba(255, 255, 255, 0.04)",
          }}
        >
          <p className="text-xs text-white/30 mb-1">{c.label}</p>
          <p className="text-2xl font-semibold" style={{ color: c.color }}>
            {summary ? summary[c.key].toLocaleString() : "—"}
          </p>
        </div>
      ))}
      {health && (
        <div
          className="col-span-full text-[11px] text-white/20 mt-1"
        >
          Spool: {health.spool_dir} · 已處理: {health.total_events_processed.toLocaleString()}
        </div>
      )}
    </div>
  );
}

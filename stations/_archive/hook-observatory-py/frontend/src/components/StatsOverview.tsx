import type { SummaryStats, HealthResponse } from "../api/client.ts";
import { useI18n } from "../i18n";

interface Props {
  summary: SummaryStats | null;
  health: HealthResponse | null;
}

export default function StatsOverview({ summary, health }: Props) {
  const { t } = useI18n();

  const cards = [
    { key: "total" as const, label: t("stats.totalEvents"), color: "#89b4fa" },
    { key: "today" as const, label: t("stats.todayEvents"), color: "#a6e3a1" },
    { key: "unique_sessions" as const, label: t("stats.sessions"), color: "#cba6f7" },
  ];

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
          {t("stats.spool")} {health.spool_dir} · {t("stats.processed")} {health.total_events_processed.toLocaleString()}
        </div>
      )}
    </div>
  );
}

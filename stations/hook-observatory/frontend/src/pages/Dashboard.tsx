import { useSWR } from "../hooks/useSWR.ts";
import { api } from "../api/client.ts";
import StatsOverview from "../components/StatsOverview.tsx";
import EventTypeChart from "../components/EventTypeChart.tsx";
import TimelineChart from "../components/TimelineChart.tsx";
import ToolUsageChart from "../components/ToolUsageChart.tsx";
import SessionList from "../components/SessionList.tsx";
import { useI18n } from "../i18n";

const REFRESH = 30_000;

export default function Dashboard() {
  const { t } = useI18n();
  const { data: allStats, error: statsError, refresh: refreshStats } = useSWR(
    "allStats",
    api.allStats,
    { refreshInterval: REFRESH },
  );
  const { data: health, error: healthError, refresh: refreshHealth } = useSWR(
    "health",
    api.health,
    { refreshInterval: REFRESH },
  );

  const error = statsError || healthError;
  const refreshAll = () => { refreshStats(); refreshHealth(); };

  return (
    <div className="space-y-6">
      {/* Title row */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-medium text-white/80">{t("dashboard.title")}</h1>
        <button
          onClick={refreshAll}
          className="text-[11px] text-white/25 hover:text-white/50 transition-colors"
        >
          {t("dashboard.refresh")}
        </button>
      </div>

      {error && (
        <div className="rounded bg-red-500/10 border border-red-500/20 px-4 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Stats overview */}
      <StatsOverview summary={allStats?.summary ?? null} health={health} />

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <EventTypeChart data={allStats?.by_event ?? []} />
        <TimelineChart data={allStats?.timeline ?? []} />
      </div>

      {/* Second row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ToolUsageChart data={allStats?.by_tool ?? []} />
        <SessionList data={allStats?.sessions ?? []} />
      </div>
    </div>
  );
}

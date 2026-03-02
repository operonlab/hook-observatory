import { useSWR } from "../hooks/useSWR.ts";
import { api } from "../api/client.ts";
import StatsOverview from "../components/StatsOverview.tsx";
import EventTypeChart from "../components/EventTypeChart.tsx";
import TimelineChart from "../components/TimelineChart.tsx";
import ToolUsageChart from "../components/ToolUsageChart.tsx";
import SessionList from "../components/SessionList.tsx";

const REFRESH = 10_000;

export default function Dashboard() {
  const { data: summary, error: e1, refresh: r1 } = useSWR("summary", api.summary, { refreshInterval: REFRESH });
  const { data: health, error: e2, refresh: r2 } = useSWR("health", api.health, { refreshInterval: REFRESH });
  const { data: byEvent, error: e3, refresh: r3 } = useSWR("byEvent", api.byEvent, { refreshInterval: REFRESH, fallback: [] });
  const { data: byTool, error: e4, refresh: r4 } = useSWR("byTool", () => api.byTool(), { refreshInterval: REFRESH, fallback: [] });
  const { data: sessions, error: e5, refresh: r5 } = useSWR("sessions", () => api.bySession(), { refreshInterval: REFRESH, fallback: [] });
  const { data: timeline, error: e6, refresh: r6 } = useSWR("timeline", () => api.timeline(), { refreshInterval: REFRESH, fallback: [] });

  const error = e1 || e2 || e3 || e4 || e5 || e6;
  const refreshAll = () => { r1(); r2(); r3(); r4(); r5(); r6(); };

  return (
    <div className="space-y-6">
      {/* Title row */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-medium text-white/80">Dashboard</h1>
        <button
          onClick={refreshAll}
          className="text-[11px] text-white/25 hover:text-white/50 transition-colors"
        >
          重新整理
        </button>
      </div>

      {error && (
        <div className="rounded bg-red-500/10 border border-red-500/20 px-4 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Stats overview */}
      <StatsOverview summary={summary} health={health} />

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <EventTypeChart data={byEvent ?? []} />
        <TimelineChart data={timeline ?? []} />
      </div>

      {/* Second row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ToolUsageChart data={byTool ?? []} />
        <SessionList data={sessions ?? []} />
      </div>
    </div>
  );
}

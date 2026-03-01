import { useEffect, useState } from "react";
import { api } from "../api/client.ts";
import type { SummaryStats, EventTypeStats, ToolStats, SessionStats, TimelineBucket, HealthResponse } from "../api/client.ts";
import StatsOverview from "../components/StatsOverview.tsx";
import EventTypeChart from "../components/EventTypeChart.tsx";
import TimelineChart from "../components/TimelineChart.tsx";
import ToolUsageChart from "../components/ToolUsageChart.tsx";
import SessionList from "../components/SessionList.tsx";

export default function Dashboard() {
  const [summary, setSummary] = useState<SummaryStats | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [byEvent, setByEvent] = useState<EventTypeStats[]>([]);
  const [byTool, setByTool] = useState<ToolStats[]>([]);
  const [sessions, setSessions] = useState<SessionStats[]>([]);
  const [timeline, setTimeline] = useState<TimelineBucket[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = () => {
    Promise.all([
      api.summary().catch(() => null),
      api.health().catch(() => null),
      api.byEvent().catch(() => []),
      api.byTool().catch(() => []),
      api.bySession().catch(() => []),
      api.timeline().catch(() => []),
    ]).then(([sum, hp, evt, tool, sess, tl]) => {
      setSummary(sum);
      setHealth(hp);
      setByEvent(evt as EventTypeStats[]);
      setByTool(tool as ToolStats[]);
      setSessions(sess as SessionStats[]);
      setTimeline(tl as TimelineBucket[]);
      setError(null);
    }).catch((e) => setError(e.message));
  };

  useEffect(() => {
    fetchAll();
    const timer = setInterval(fetchAll, 10_000); // Auto-refresh every 10s
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="space-y-6">
      {/* Title row */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-medium text-white/80">Dashboard</h1>
        <button
          onClick={fetchAll}
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
        <EventTypeChart data={byEvent} />
        <TimelineChart data={timeline} />
      </div>

      {/* Second row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ToolUsageChart data={byTool} />
        <SessionList data={sessions} />
      </div>
    </div>
  );
}

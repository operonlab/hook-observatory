import { useState, useCallback } from "react";
import { api } from "../api";
import type { TimelineInfo } from "../types";

export function useTimeline() {
  const [timeline, setTimeline] = useState<TimelineInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (projectId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getTimeline(projectId);
      setTimeline(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const reload = useCallback(
    async (projectId: string) => {
      try {
        const data = await api.getTimeline(projectId);
        setTimeline(data);
      } catch {
        /* keep stale data on refresh failure */
      }
    },
    [],
  );

  return { timeline, loading, error, load, reload };
}

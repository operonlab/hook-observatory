import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client.ts";
import type { HookEvent, EventTypeStats } from "../api/client.ts";
import EventTable from "../components/EventTable.tsx";

export default function Events() {
  const [events, setEvents] = useState<HookEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [eventTypes, setEventTypes] = useState<string[]>([]);
  const [filters, setFilters] = useState<{ event_type?: string; session_id?: string }>({});
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const fetchEvents = useCallback(() => {
    api
      .events({ ...filters, limit, offset })
      .then((res) => {
        setEvents(res.items);
        setTotal(res.total);
      })
      .catch(() => {});
  }, [filters, offset]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  useEffect(() => {
    api
      .byEvent()
      .then((types: EventTypeStats[]) => setEventTypes(types.map((t) => t.event_type)))
      .catch(() => {});
  }, []);

  const handleFilterChange = (f: { event_type?: string; session_id?: string }) => {
    setFilters(f);
    setOffset(0);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-medium text-white/80">事件明細</h1>
        <button
          onClick={fetchEvents}
          className="text-[11px] text-white/25 hover:text-white/50 transition-colors"
        >
          重新整理
        </button>
      </div>

      <EventTable
        events={events}
        total={total}
        limit={limit}
        offset={offset}
        onPageChange={setOffset}
        onFilterChange={handleFilterChange}
        eventTypes={eventTypes}
      />
    </div>
  );
}

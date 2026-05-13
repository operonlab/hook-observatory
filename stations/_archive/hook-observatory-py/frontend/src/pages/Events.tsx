import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client.ts";
import type { HookEvent, EventTypeStats } from "../api/client.ts";
import EventTable from "../components/EventTable.tsx";
import { useI18n } from "../i18n";

export default function Events() {
  const { t } = useI18n();
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
        <h1 className="text-lg font-medium text-white/80">{t("events.title")}</h1>
        <button
          onClick={fetchEvents}
          className="text-[11px] text-white/25 hover:text-white/50 transition-colors"
        >
          {t("events.refresh")}
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

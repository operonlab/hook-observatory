/**
 * API client — fetch wrapper with error handling.
 * Credentials included for cookie auth (workshop_session).
 */

// Detect base path from current URL at load time.
// Under Nginx proxy (/apps/hook/) → BASE = "/apps/hook"
// Local dev (localhost:4101) → BASE = ""
const BASE = window.location.pathname.match(/^(\/apps\/hook)\/?/)?.[1] ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    if (res.status === 401) {
      throw new AuthError("Not authenticated");
    }
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export class AuthError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = "AuthError";
  }
}

// --- Types (mirror backend schemas) ---

export interface SummaryStats {
  total: number;
  today: number;
  unique_sessions: number;
}

export interface EventTypeStats {
  event_type: string;
  count: number;
  today: number;
}

export interface ToolStats {
  tool_name: string;
  count: number;
}

export interface SessionStats {
  session_id: string;
  event_count: number;
  first_seen: string;
  last_seen: string;
}

export interface TimelineBucket {
  bucket: string;
  count: number;
}

export interface HookEvent {
  id: string;
  event_type: string;
  session_id: string | null;
  cwd: string | null;
  tool_name: string | null;
  hook_name: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface EventListResponse {
  items: HookEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface HealthResponse {
  status: string;
  spool_dir: string;
  total_events_processed: number;
}

export interface AllStats {
  summary: SummaryStats;
  by_event: EventTypeStats[];
  by_tool: ToolStats[];
  sessions: SessionStats[];
  timeline: TimelineBucket[];
}

// --- API functions ---

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  allStats: () => request<AllStats>("/api/stats/all"),
  summary: () => request<SummaryStats>("/api/stats/summary"),
  byEvent: () => request<EventTypeStats[]>("/api/stats/by-event"),
  byTool: (limit = 20) => request<ToolStats[]>(`/api/stats/by-tool?limit=${limit}`),
  bySession: (limit = 20) => request<SessionStats[]>(`/api/stats/by-session?limit=${limit}`),
  timeline: (range = "7d", granularity = "hour") =>
    request<TimelineBucket[]>(`/api/stats/timeline?range=${range}&granularity=${granularity}`),
  events: (params: { event_type?: string; session_id?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.event_type) qs.set("event_type", params.event_type);
    if (params.session_id) qs.set("session_id", params.session_id);
    qs.set("limit", String(params.limit ?? 50));
    qs.set("offset", String(params.offset ?? 0));
    return request<EventListResponse>(`/api/events?${qs}`);
  },
};

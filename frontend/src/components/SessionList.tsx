import type { SessionStats } from "../api/client.ts";

interface Props {
  data: SessionStats[];
}

export default function SessionList({ data }: Props) {
  if (!data.length) {
    return (
      <div
        className="flex h-[200px] items-center justify-center rounded-lg"
        style={{ backgroundColor: "#12121a", border: "1px solid rgba(255, 255, 255, 0.04)" }}
      >
        <p className="text-xs text-white/20">尚無 session 資料</p>
      </div>
    );
  }

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ backgroundColor: "#12121a", border: "1px solid rgba(255, 255, 255, 0.04)" }}
    >
      <h3 className="text-xs text-white/30 px-5 pt-5 pb-3">最近 Sessions</h3>
      <div className="divide-y divide-white/[0.03]">
        {data.slice(0, 10).map((s) => (
          <div key={s.session_id} className="flex items-center justify-between px-5 py-3">
            <div className="min-w-0">
              <p className="text-xs text-white/60 font-mono truncate" title={s.session_id}>
                {s.session_id.slice(0, 12)}...
              </p>
              <p className="text-[10px] text-white/20 mt-0.5">
                {new Date(s.first_seen).toLocaleString("zh-TW")} — {new Date(s.last_seen).toLocaleString("zh-TW")}
              </p>
            </div>
            <span
              className="ml-4 shrink-0 rounded px-2 py-0.5 text-[11px] font-medium"
              style={{ backgroundColor: "#cba6f720", color: "#cba6f7" }}
            >
              {s.event_count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

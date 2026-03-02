import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import ChartTooltip from "./ChartTooltip.tsx";
import type { TimelineBucket } from "../api/client.ts";

interface Props {
  data: TimelineBucket[];
}

export default function TimelineChart({ data }: Props) {
  if (!data.length) {
    return (
      <div
        className="flex h-[280px] items-center justify-center rounded-lg"
        style={{ backgroundColor: "#12121a", border: "1px solid rgba(255, 255, 255, 0.04)" }}
      >
        <p className="text-xs text-white/20">尚無時間軸資料</p>
      </div>
    );
  }

  const formatted = data.map((d) => ({
    ...d,
    label: new Date(d.bucket).toLocaleString("zh-TW", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
  }));

  return (
    <div
      className="rounded-lg p-5"
      style={{ backgroundColor: "#12121a", border: "1px solid rgba(255, 255, 255, 0.04)" }}
    >
      <h3 className="text-xs text-white/30 mb-4">事件時間軸（7 天）</h3>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={formatted}>
          <defs>
            <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#89b4fa" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#89b4fa" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="label"
            tick={{ fill: "rgba(255,255,255,0.25)", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: "rgba(255,255,255,0.25)", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={40}
          />
          <Tooltip content={<ChartTooltip />} />
          <Area
            type="monotone"
            dataKey="count"
            stroke="#89b4fa"
            strokeWidth={1.5}
            fill="url(#colorCount)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

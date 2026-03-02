import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import ChartTooltip from "./ChartTooltip.tsx";
import type { ToolStats } from "../api/client.ts";

interface Props {
  data: ToolStats[];
}

export default function ToolUsageChart({ data }: Props) {
  if (!data.length) {
    return (
      <div
        className="flex h-[280px] items-center justify-center rounded-lg"
        style={{ backgroundColor: "#12121a", border: "1px solid rgba(255, 255, 255, 0.04)" }}
      >
        <p className="text-xs text-white/20">尚無工具使用資料</p>
      </div>
    );
  }

  return (
    <div
      className="rounded-lg p-5"
      style={{ backgroundColor: "#12121a", border: "1px solid rgba(255, 255, 255, 0.04)" }}
    >
      <h3 className="text-xs text-white/30 mb-4">工具使用排行</h3>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data.slice(0, 15)} layout="vertical" margin={{ left: 10 }}>
          <XAxis type="number" tick={{ fill: "rgba(255,255,255,0.3)", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis
            type="category"
            dataKey="tool_name"
            tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={110}
          />
          <Tooltip content={<ChartTooltip />} />
          <Bar dataKey="count" fill="#94e2d5" fillOpacity={0.6} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

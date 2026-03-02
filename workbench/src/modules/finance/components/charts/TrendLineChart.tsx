import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { MonthlyTrend } from '../../types'

interface TrendLineChartProps {
  data: MonthlyTrend[]
}

export default function TrendLineChart({ data }: TrendLineChartProps) {
  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-64 text-sm"
        style={{ color: 'var(--fn-text-muted)' }}
      >
        無趨勢資料
      </div>
    )
  }

  const formatted = data.map((d) => ({
    ...d,
    month: d.year_month.slice(5),
  }))

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={formatted}>
        <CartesianGrid strokeDasharray="3 3" stroke="#383854" vertical={false} />
        <XAxis
          dataKey="month"
          tick={{ fontSize: 11, fill: '#7f849c' }}
          axisLine={{ stroke: '#383854' }}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 11, fill: '#7f849c' }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#242438',
            border: '1px solid #383854',
            borderRadius: 8,
            fontSize: 12,
            color: '#cdd6f4',
          }}
          formatter={(value: number, name: string) => {
            const labels: Record<string, string> = {
              income: '收入',
              expense: '支出',
              net: '淨額',
            }
            return [`$${value.toLocaleString()}`, labels[name] ?? name]
          }}
          labelFormatter={(label) => `${label} 月`}
        />
        <Line
          type="monotone"
          dataKey="income"
          stroke="#a6e3a1"
          strokeWidth={2}
          dot={{ r: 3, fill: '#a6e3a1' }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="expense"
          stroke="#f38ba8"
          strokeWidth={2}
          dot={{ r: 3, fill: '#f38ba8' }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="net"
          stroke="#89b4fa"
          strokeWidth={2}
          strokeDasharray="5 3"
          dot={{ r: 3, fill: '#89b4fa' }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

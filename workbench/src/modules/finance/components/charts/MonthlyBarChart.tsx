import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { MonthlyTrend } from '../../types'
import { fmtAmt } from '../../types'

interface MonthlyBarChartProps {
  data: MonthlyTrend[]
}

export default function MonthlyBarChart({ data }: MonthlyBarChartProps) {
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
      <BarChart data={formatted} barGap={2} barCategoryGap="20%">
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
          formatter={(value: number, name: string) => [
            `$${fmtAmt(value)}`,
            name === 'income' ? '收入' : '支出',
          ]}
          labelFormatter={(label) => `${label} 月`}
        />
        <Legend
          formatter={(value: string) => (value === 'income' ? '收入' : '支出')}
          wrapperStyle={{ fontSize: 11, color: '#a6adc8' }}
        />
        <Bar dataKey="income" fill="#a6e3a1" radius={[3, 3, 0, 0]} />
        <Bar dataKey="expense" fill="#f38ba8" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

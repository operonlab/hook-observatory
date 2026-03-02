import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { NetWorthPoint } from '../../types'
import { fmtAmt } from '../../types'

interface NetWorthChartProps {
  data: NetWorthPoint[]
}

export default function NetWorthChart({ data }: NetWorthChartProps) {
  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-64 text-sm"
        style={{ color: 'var(--fn-text-muted)' }}
      >
        無淨資產資料
      </div>
    )
  }

  const formatted = data.map((d) => ({
    ...d,
    label: d.date.slice(5),
  }))

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={formatted}>
        <defs>
          <linearGradient id="fnNwTotal" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#a6e3a1" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#a6e3a1" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="fnNwBank" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#89b4fa" stopOpacity={0.2} />
            <stop offset="100%" stopColor="#89b4fa" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#383854" vertical={false} />
        <XAxis
          dataKey="label"
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
              total: '總淨資產',
              bank: '銀行',
              cash: '現金',
              e_wallet: '電子錢包',
              investment: '投資',
              credit_card: '信用卡',
            }
            return [`$${fmtAmt(value)}`, labels[name] ?? name]
          }}
        />
        <Area
          type="monotone"
          dataKey="total"
          stroke="#a6e3a1"
          strokeWidth={2}
          fill="url(#fnNwTotal)"
        />
        <Area
          type="monotone"
          dataKey="bank"
          stroke="#89b4fa"
          strokeWidth={1.5}
          fill="url(#fnNwBank)"
        />
        <Area type="monotone" dataKey="investment" stroke="#f9e2af" strokeWidth={1.5} fill="none" />
        <Area
          type="monotone"
          dataKey="credit_card"
          stroke="#f38ba8"
          strokeWidth={1}
          strokeDasharray="4 2"
          fill="none"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

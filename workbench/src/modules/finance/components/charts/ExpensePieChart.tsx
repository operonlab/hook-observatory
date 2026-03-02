import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { CategoryBreakdown } from '../../types'

const COLORS = [
  'var(--fn-chart-1)',
  'var(--fn-chart-2)',
  'var(--fn-chart-3)',
  'var(--fn-chart-4)',
  'var(--fn-chart-5)',
  'var(--fn-chart-6)',
  'var(--fn-chart-7)',
  'var(--fn-chart-8)',
]

interface ExpensePieChartProps {
  data: CategoryBreakdown[]
}

export default function ExpensePieChart({ data }: ExpensePieChartProps) {
  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-64 text-sm"
        style={{ color: 'var(--fn-text-muted)' }}
      >
        無分類資料
      </div>
    )
  }

  const total = data.reduce((sum, d) => sum + d.amount, 0)

  return (
    <div className="space-y-3">
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie
            data={data}
            dataKey="amount"
            nameKey="category_name"
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={90}
            paddingAngle={2}
            stroke="none"
          >
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: '#242438',
              border: '1px solid #383854',
              borderRadius: 8,
              fontSize: 12,
              color: '#cdd6f4',
            }}
            formatter={(value: number) => [`$${value.toLocaleString()}`, '金額']}
          />
        </PieChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 px-2">
        {data.map((item, i) => (
          <div
            key={item.category_id ?? 'uncategorized'}
            className="flex items-center gap-2 text-[11px]"
          >
            <div
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ backgroundColor: COLORS[i % COLORS.length] }}
            />
            <span className="truncate" style={{ color: 'var(--fn-text-secondary)' }}>
              {item.category_icon ?? ''} {item.category_name}
            </span>
            <span
              className="ml-auto shrink-0 tabular-nums"
              style={{ color: 'var(--fn-text-muted)' }}
            >
              {total > 0 ? Math.round((item.amount / total) * 100) : 0}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

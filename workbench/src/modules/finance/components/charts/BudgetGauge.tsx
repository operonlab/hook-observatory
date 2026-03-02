import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import type { Budget } from "../../types";

interface BudgetGaugeProps {
	budget: Budget;
}

export default function BudgetGauge({ budget }: BudgetGaugeProps) {
	const pct = Math.min(budget.used_pct, 100);
	const remaining = 100 - pct;

	const data = [
		{ name: "used", value: pct },
		{ name: "remaining", value: remaining },
	];

	const getColor = (p: number) => {
		if (p >= 100) return "#f38ba8";
		if (p >= 80) return "#f9e2af";
		return "#a6e3a1";
	};

	const color = getColor(budget.used_pct);

	return (
		<div className="flex flex-col items-center">
			<div className="relative" style={{ width: 120, height: 120 }}>
				<ResponsiveContainer width="100%" height="100%">
					<PieChart>
						<Pie
							data={data}
							dataKey="value"
							startAngle={210}
							endAngle={-30}
							innerRadius={40}
							outerRadius={52}
							paddingAngle={0}
							stroke="none"
						>
							<Cell fill={color} />
							<Cell fill="#2a2a3e" />
						</Pie>
					</PieChart>
				</ResponsiveContainer>
				<div className="absolute inset-0 flex flex-col items-center justify-center">
					<span
						className="text-lg font-semibold tabular-nums"
						style={{ color }}
					>
						{Math.round(budget.used_pct)}%
					</span>
				</div>
			</div>
			<div className="text-center mt-1 space-y-0.5">
				<div
					className="text-[11px]"
					style={{ color: "var(--fn-text-tertiary)" }}
				>
					{budget.category_name ?? "總預算"}
				</div>
				<div
					className="text-xs tabular-nums"
					style={{ color: "var(--fn-text-secondary)" }}
				>
					${budget.spent_amount.toLocaleString()} / $
					{budget.budget_amount.toLocaleString()}
				</div>
			</div>
		</div>
	);
}

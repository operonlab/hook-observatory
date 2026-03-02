import {
	ChevronLeft,
	ChevronRight,
	Pause,
	RefreshCw,
	XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { subscriptionApi } from "../api";
import type { BillingCycle, Subscription, SubscriptionStatus } from "../types";

const CYCLE_LABELS: Record<BillingCycle, string> = {
	weekly: "每週",
	monthly: "每月",
	yearly: "每年",
};

const STATUS_CONFIG: Record<
	SubscriptionStatus,
	{ label: string; color: string }
> = {
	active: { label: "啟用", color: "var(--fn-income)" },
	paused: { label: "暫停", color: "var(--fn-warning)" },
	cancelled: { label: "已取消", color: "var(--fn-text-muted)" },
};

interface SubscriptionListProps {
	onEdit?: (sub: Subscription) => void;
}

export default function SubscriptionList({ onEdit }: SubscriptionListProps) {
	const [items, setItems] = useState<Subscription[]>([]);
	const [total, setTotal] = useState(0);
	const [page, setPage] = useState(1);
	const [loading, setLoading] = useState(true);
	const pageSize = 20;

	const fetchData = () => {
		setLoading(true);
		subscriptionApi
			.list(page, pageSize)
			.then((res) => {
				setItems(res.items);
				setTotal(res.total);
			})
			.catch(() => setItems([]))
			.finally(() => setLoading(false));
	};

	useEffect(() => {
		fetchData();
	}, [page]);

	const totalPages = Math.ceil(total / pageSize);

	const monthlyEquivalent = (sub: Subscription) => {
		if (sub.billing_cycle === "monthly") return sub.amount;
		if (sub.billing_cycle === "yearly") return Math.round(sub.amount / 12);
		if (sub.billing_cycle === "weekly") return Math.round(sub.amount * 4.33);
		return sub.amount;
	};

	const totalMonthly = items
		.filter((s) => s.status === "active")
		.reduce((sum, s) => sum + monthlyEquivalent(s), 0);

	return (
		<div className="space-y-4">
			{/* Summary */}
			<div className="flex items-center justify-between px-1">
				<div>
					<span
						className="text-[11px]"
						style={{ color: "var(--fn-text-muted)" }}
					>
						每月訂閱總計
					</span>
					<div
						className="text-lg font-medium"
						style={{ color: "var(--fn-expense)" }}
					>
						${totalMonthly.toLocaleString()}
					</div>
				</div>
				<span className="text-[11px]" style={{ color: "var(--fn-text-muted)" }}>
					{items.filter((s) => s.status === "active").length} 個啟用中
				</span>
			</div>

			{/* List */}
			{loading ? (
				<div className="flex justify-center py-12">
					<div
						className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
						style={{
							borderColor: "var(--fn-accent)",
							borderTopColor: "transparent",
						}}
					/>
				</div>
			) : items.length === 0 ? (
				<div
					className="text-center py-12 text-sm"
					style={{ color: "var(--fn-text-muted)" }}
				>
					尚無訂閱紀錄
				</div>
			) : (
				<div className="space-y-1">
					{items.map((sub) => {
						const sCfg = STATUS_CONFIG[sub.status];
						return (
							<button
								type="button"
								key={sub.id}
								onClick={() => onEdit?.(sub)}
								className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md transition-colors text-left"
								style={{ backgroundColor: "transparent" }}
								onMouseEnter={(e) => {
									e.currentTarget.style.backgroundColor =
										"var(--fn-accent-alpha)";
								}}
								onMouseLeave={(e) => {
									e.currentTarget.style.backgroundColor = "transparent";
								}}
							>
								<div className="flex-1 min-w-0">
									<div className="flex items-center justify-between gap-2">
										<span
											className="text-[13px] truncate"
											style={{ color: "var(--fn-text)" }}
										>
											{sub.name}
										</span>
										<span
											className="text-[13px] font-medium shrink-0"
											style={{ color: "var(--fn-expense)" }}
										>
											${sub.amount.toLocaleString()}/
											{CYCLE_LABELS[sub.billing_cycle]}
										</span>
									</div>
									<div className="flex items-center gap-2 mt-0.5">
										<span
											className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded"
											style={{
												backgroundColor: `${sCfg.color}20`,
												color: sCfg.color,
											}}
										>
											{sub.status === "active" && <RefreshCw size={9} />}
											{sub.status === "paused" && <Pause size={9} />}
											{sub.status === "cancelled" && <XCircle size={9} />}
											{sCfg.label}
										</span>
										{sub.next_billing && (
											<span
												className="text-[11px]"
												style={{ color: "var(--fn-text-muted)" }}
											>
												下次扣款{" "}
												{new Date(sub.next_billing).toLocaleDateString("zh-TW")}
											</span>
										)}
										{sub.category_name && (
											<span
												className="text-[11px] px-1.5 py-0.5 rounded"
												style={{
													backgroundColor: "var(--fn-bg-surface)",
													color: "var(--fn-text-tertiary)",
												}}
											>
												{sub.category_name}
											</span>
										)}
									</div>
								</div>
							</button>
						);
					})}
				</div>
			)}

			{/* Pagination */}
			{totalPages > 1 && (
				<div className="flex items-center justify-center gap-2 pt-2">
					<button
						type="button"
						onClick={() => setPage((p) => Math.max(1, p - 1))}
						disabled={page === 1}
						className="p-1 disabled:opacity-30"
						style={{ color: "var(--fn-text-tertiary)" }}
					>
						<ChevronLeft size={16} />
					</button>
					<span
						className="text-[11px]"
						style={{ color: "var(--fn-text-muted)" }}
					>
						{page} / {totalPages}
					</span>
					<button
						type="button"
						onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
						disabled={page === totalPages}
						className="p-1 disabled:opacity-30"
						style={{ color: "var(--fn-text-tertiary)" }}
					>
						<ChevronRight size={16} />
					</button>
				</div>
			)}
		</div>
	);
}

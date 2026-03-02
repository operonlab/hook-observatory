import { FileText, PieChart, Receipt, Target, Wallet } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import "../styles/finance.css";

const NAV_ITEMS = [
	{ id: "transactions", label: "交易", icon: Receipt, path: "/finance" },
	{ id: "wallets", label: "錢包", icon: Wallet, path: "/finance/wallets" },
	{ id: "budget", label: "預算", icon: Target, path: "/finance/budget" },
	{
		id: "analytics",
		label: "分析",
		icon: PieChart,
		path: "/finance/analytics",
	},
	{ id: "report", label: "報告", icon: FileText, path: "/finance/report" },
] as const;

export default function FinanceLayout() {
	const location = useLocation();

	const isActive = (item: (typeof NAV_ITEMS)[number]) => {
		if (item.id === "transactions") return location.pathname === "/finance";
		return location.pathname.startsWith(item.path);
	};

	return (
		<div className="finance flex flex-col md:flex-row h-full">
			{/* ─── Desktop Sidebar ─── */}
			<aside
				className="hidden md:flex flex-col shrink-0 border-r"
				style={{
					width: 220,
					backgroundColor: "var(--fn-bg)",
					borderColor: "var(--fn-border)",
				}}
			>
				<div
					className="flex items-center gap-2.5 px-5 py-4 border-b"
					style={{ borderColor: "var(--fn-border)" }}
				>
					<span className="text-lg">💰</span>
					<span
						className="text-sm font-medium tracking-wide"
						style={{ color: "var(--fn-accent)" }}
					>
						記帳理財
					</span>
				</div>

				<nav className="flex-1 py-2 px-2 space-y-0.5">
					{NAV_ITEMS.map((item) => {
						const active = isActive(item);
						const Icon = item.icon;
						return (
							<NavLink
								key={item.id}
								to={item.path}
								className="flex items-center gap-3 px-3 py-2.5 text-[13px] rounded-md transition-colors"
								style={{
									backgroundColor: active
										? "var(--fn-accent-alpha)"
										: "transparent",
									color: active
										? "var(--fn-accent)"
										: "var(--fn-text-tertiary)",
									borderLeft: active
										? "2px solid var(--fn-accent)"
										: "2px solid transparent",
								}}
							>
								<Icon size={15} />
								{item.label}
							</NavLink>
						);
					})}
				</nav>
			</aside>

			{/* ─── Main Content ─── */}
			<main className="flex-1 min-w-0 overflow-y-auto pb-16 md:pb-0">
				<Outlet />
			</main>

			{/* ─── Mobile Bottom Tab Bar ─── */}
			<nav
				className="flex md:hidden items-stretch border-t shrink-0 fixed bottom-0 left-0 right-0 z-30"
				style={{
					backgroundColor: "var(--fn-bg)",
					borderColor: "var(--fn-border)",
					paddingBottom: "env(safe-area-inset-bottom, 0px)",
				}}
			>
				{NAV_ITEMS.map((item) => {
					const active = isActive(item);
					const Icon = item.icon;
					return (
						<NavLink
							key={item.id}
							to={item.path}
							className="flex flex-1 flex-col items-center justify-center gap-1 py-2 min-h-[56px] text-[10px] transition-colors"
							style={{
								color: active ? "var(--fn-accent)" : "var(--fn-text-muted)",
								backgroundColor: active
									? "var(--fn-accent-alpha)"
									: "transparent",
							}}
						>
							<Icon size={20} />
							<span className="font-medium">{item.label}</span>
						</NavLink>
					);
				})}
			</nav>
		</div>
	);
}

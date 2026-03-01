import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { PaginatedResponse, User } from "@/types";
import { listUsers } from "../api";
import RoleBadge from "../components/RoleBadge";
import StatusBadge from "../components/StatusBadge";

const STATUS_TABS = [
	{ value: "", label: "全部" },
	{ value: "active", label: "啟用" },
	{ value: "pending", label: "待審" },
	{ value: "suspended", label: "停權" },
	{ value: "banned", label: "封鎖" },
];

const PAGE_SIZE = 20;

export default function UserList() {
	const navigate = useNavigate();
	const [data, setData] = useState<PaginatedResponse<User> | null>(null);
	const [status, setStatus] = useState("");
	const [search, setSearch] = useState("");
	const [page, setPage] = useState(1);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		let cancelled = false;
		setLoading(true);
		setError("");
		listUsers({
			page,
			page_size: PAGE_SIZE,
			status_filter: status || undefined,
			search: search || undefined,
		})
			.then((res) => {
				if (!cancelled) setData(res);
			})
			.catch((err: Error) => {
				if (!cancelled) setError(err.message);
			})
			.finally(() => {
				if (!cancelled) setLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [page, status, search]);

	const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

	return (
		<div className="mx-auto max-w-5xl">
			<h1 className="mb-6 text-2xl font-bold" style={{ color: "var(--text)" }}>
				使用者管理
			</h1>

			{/* Search */}
			<div className="mb-4">
				<input
					type="text"
					value={search}
					onChange={(e) => {
						setSearch(e.target.value);
						setPage(1);
					}}
					placeholder="搜尋 email 或名稱..."
					className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none focus:ring-2"
					style={{
						backgroundColor: "var(--base)",
						borderColor: "var(--surface0)",
						color: "var(--text)",
						minHeight: 44,
					}}
				/>
			</div>

			{/* Status tabs */}
			<div
				className="mb-4 flex gap-1 overflow-x-auto rounded-lg p-1"
				style={{ backgroundColor: "var(--surface0)" }}
			>
				{STATUS_TABS.map((tab) => (
					<button
						type="button"
						key={tab.value}
						onClick={() => {
							setStatus(tab.value);
							setPage(1);
						}}
						className="whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
						style={{
							backgroundColor:
								status === tab.value ? "var(--mantle)" : "transparent",
							color: status === tab.value ? "var(--text)" : "var(--subtext0)",
							minHeight: 36,
						}}
					>
						{tab.label}
					</button>
				))}
			</div>

			{/* Error */}
			{error && (
				<p
					className="mb-4 rounded-lg px-3 py-2 text-sm"
					style={{
						backgroundColor: "var(--red)" + "15",
						color: "var(--red)",
					}}
				>
					{error}
				</p>
			)}

			{/* Table */}
			<div
				className="overflow-hidden rounded-xl border"
				style={{ borderColor: "var(--surface0)" }}
			>
				<table className="w-full text-sm">
					<thead>
						<tr style={{ backgroundColor: "var(--surface0)" }}>
							<th
								className="px-4 py-3 text-left font-medium"
								style={{ color: "var(--subtext0)" }}
							>
								使用者
							</th>
							<th
								className="hidden px-4 py-3 text-left font-medium sm:table-cell"
								style={{ color: "var(--subtext0)" }}
							>
								角色
							</th>
							<th
								className="px-4 py-3 text-left font-medium"
								style={{ color: "var(--subtext0)" }}
							>
								狀態
							</th>
							<th
								className="hidden px-4 py-3 text-left font-medium md:table-cell"
								style={{ color: "var(--subtext0)" }}
							>
								建立時間
							</th>
						</tr>
					</thead>
					<tbody>
						{loading && !data ? (
							<tr>
								<td
									colSpan={4}
									className="px-4 py-8 text-center"
									style={{ color: "var(--subtext0)" }}
								>
									載入中...
								</td>
							</tr>
						) : data?.items.length === 0 ? (
							<tr>
								<td
									colSpan={4}
									className="px-4 py-8 text-center"
									style={{ color: "var(--subtext0)" }}
								>
									沒有找到使用者
								</td>
							</tr>
						) : (
							data?.items.map((user) => (
								<tr
									key={user.id}
									onClick={() => navigate(`/admin/users/${user.id}`)}
									className="cursor-pointer border-t transition-colors hover:opacity-80"
									style={{
										borderColor: "var(--surface0)",
										backgroundColor: "var(--mantle)",
									}}
								>
									<td className="px-4 py-3">
										<div>
											<div
												className="font-medium"
												style={{ color: "var(--text)" }}
											>
												{user.display_name}
											</div>
											<div
												className="text-xs"
												style={{ color: "var(--subtext0)" }}
											>
												{user.email}
											</div>
										</div>
									</td>
									<td className="hidden px-4 py-3 sm:table-cell">
										<RoleBadge role={user.role} />
									</td>
									<td className="px-4 py-3">
										<StatusBadge status={user.status} />
									</td>
									<td
										className="hidden px-4 py-3 md:table-cell"
										style={{ color: "var(--subtext0)" }}
									>
										{new Date(user.created_at).toLocaleDateString("zh-TW")}
									</td>
								</tr>
							))
						)}
					</tbody>
				</table>
			</div>

			{/* Pagination */}
			{totalPages > 1 && (
				<div className="mt-4 flex items-center justify-between">
					<span className="text-sm" style={{ color: "var(--subtext0)" }}>
						共 {data?.total} 位使用者
					</span>
					<div className="flex gap-1">
						<button
							type="button"
							onClick={() => setPage((p) => Math.max(1, p - 1))}
							disabled={page === 1}
							className="rounded-lg px-3 py-1.5 text-sm disabled:opacity-40"
							style={{
								backgroundColor: "var(--surface0)",
								color: "var(--text)",
								minHeight: 36,
							}}
						>
							上一頁
						</button>
						<span
							className="flex items-center px-3 text-sm"
							style={{ color: "var(--subtext0)" }}
						>
							{page} / {totalPages}
						</span>
						<button
							type="button"
							onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
							disabled={page === totalPages}
							className="rounded-lg px-3 py-1.5 text-sm disabled:opacity-40"
							style={{
								backgroundColor: "var(--surface0)",
								color: "var(--text)",
								minHeight: 36,
							}}
						>
							下一頁
						</button>
					</div>
				</div>
			)}
		</div>
	);
}

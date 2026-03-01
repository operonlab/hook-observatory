import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { UserDetail as UserDetailType } from "@/types";
import { getUserDetail, updateUser } from "../api";
import RoleBadge from "../components/RoleBadge";
import StatusBadge from "../components/StatusBadge";

const ROLES = ["admin", "user", "guest"];
const STATUSES = ["active", "pending", "suspended", "banned"];

export default function UserDetail() {
	const { userId } = useParams<{ userId: string }>();
	const navigate = useNavigate();
	const [user, setUser] = useState<UserDetailType | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");
	const [saving, setSaving] = useState(false);
	const [editRole, setEditRole] = useState("");
	const [editStatus, setEditStatus] = useState("");

	useEffect(() => {
		if (!userId) return;
		setLoading(true);
		getUserDetail(userId)
			.then((data) => {
				setUser(data);
				setEditRole(data.role);
				setEditStatus(data.status);
			})
			.catch((err: Error) => setError(err.message))
			.finally(() => setLoading(false));
	}, [userId]);

	const handleSave = async () => {
		if (!userId || !user) return;
		setSaving(true);
		setError("");
		try {
			const patch: Record<string, string> = {};
			if (editRole !== user.role) patch.role = editRole;
			if (editStatus !== user.status) patch.status = editStatus;
			if (Object.keys(patch).length === 0) {
				setSaving(false);
				return;
			}
			const updated = await updateUser(userId, patch);
			setUser((prev) => (prev ? { ...prev, ...updated } : prev));
		} catch (err) {
			setError(err instanceof Error ? err.message : "更新失敗");
		} finally {
			setSaving(false);
		}
	};

	if (loading) {
		return (
			<div
				className="flex min-h-[40vh] items-center justify-center"
				style={{ color: "var(--subtext0)" }}
			>
				載入中...
			</div>
		);
	}

	if (!user) {
		return (
			<div className="mx-auto max-w-3xl">
				<p style={{ color: "var(--red)" }}>{error || "找不到使用者"}</p>
			</div>
		);
	}

	const hasChanges = editRole !== user.role || editStatus !== user.status;

	return (
		<div className="mx-auto max-w-3xl">
			{/* Back button */}
			<button
				type="button"
				onClick={() => navigate("/admin")}
				className="mb-4 text-sm hover:underline"
				style={{ color: "var(--blue)", minHeight: 44 }}
			>
				&larr; 返回使用者列表
			</button>

			{/* Header */}
			<div
				className="mb-6 flex items-center gap-4 rounded-xl border p-5"
				style={{
					backgroundColor: "var(--mantle)",
					borderColor: "var(--surface0)",
				}}
			>
				{user.avatar_url ? (
					<img
						src={user.avatar_url}
						alt={user.display_name}
						className="h-16 w-16 rounded-full object-cover"
					/>
				) : (
					<div
						className="flex h-16 w-16 items-center justify-center rounded-full text-2xl font-bold"
						style={{
							backgroundColor: "var(--surface0)",
							color: "var(--text)",
						}}
					>
						{user.display_name.charAt(0).toUpperCase()}
					</div>
				)}
				<div>
					<h1 className="text-xl font-bold" style={{ color: "var(--text)" }}>
						{user.display_name}
					</h1>
					<p className="text-sm" style={{ color: "var(--subtext0)" }}>
						{user.email}
					</p>
					<div className="mt-1 flex gap-2">
						<RoleBadge role={user.role} />
						<StatusBadge status={user.status} />
					</div>
				</div>
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

			{/* Edit section */}
			<div
				className="mb-6 rounded-xl border p-5"
				style={{
					backgroundColor: "var(--mantle)",
					borderColor: "var(--surface0)",
				}}
			>
				<h2
					className="mb-4 text-base font-semibold"
					style={{ color: "var(--text)" }}
				>
					帳號設定
				</h2>

				<div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
					{/* Role */}
					<div>
						<label
							htmlFor="edit-role"
							className="mb-1 block text-sm"
							style={{ color: "var(--subtext0)" }}
						>
							角色
						</label>
						<select
							id="edit-role"
							value={editRole}
							onChange={(e) => setEditRole(e.target.value)}
							className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none"
							style={{
								backgroundColor: "var(--base)",
								borderColor: "var(--surface0)",
								color: "var(--text)",
								minHeight: 44,
							}}
						>
							{ROLES.map((r) => (
								<option key={r} value={r}>
									{r}
								</option>
							))}
						</select>
					</div>

					{/* Status */}
					<div>
						<label
							htmlFor="edit-status"
							className="mb-1 block text-sm"
							style={{ color: "var(--subtext0)" }}
						>
							狀態
						</label>
						<select
							id="edit-status"
							value={editStatus}
							onChange={(e) => setEditStatus(e.target.value)}
							className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none"
							style={{
								backgroundColor: "var(--base)",
								borderColor: "var(--surface0)",
								color: "var(--text)",
								minHeight: 44,
							}}
						>
							{STATUSES.map((s) => (
								<option key={s} value={s}>
									{s}
								</option>
							))}
						</select>
					</div>
				</div>

				{/* Save button */}
				<div className="mt-4 flex justify-end">
					<button
						type="button"
						onClick={() => void handleSave()}
						disabled={!hasChanges || saving}
						className="rounded-lg px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-40"
						style={{
							backgroundColor: "var(--blue)",
							color: "var(--crust)",
							minHeight: 44,
						}}
					>
						{saving ? "儲存中..." : "儲存變更"}
					</button>
				</div>
			</div>

			{/* OAuth accounts */}
			<div
				className="mb-6 rounded-xl border p-5"
				style={{
					backgroundColor: "var(--mantle)",
					borderColor: "var(--surface0)",
				}}
			>
				<h2
					className="mb-4 text-base font-semibold"
					style={{ color: "var(--text)" }}
				>
					連結帳號
				</h2>

				{user.oauth_accounts.length === 0 ? (
					<p className="text-sm" style={{ color: "var(--subtext0)" }}>
						尚未連結任何 OAuth 帳號
					</p>
				) : (
					<div className="space-y-3">
						{user.oauth_accounts.map((acc) => (
							<div
								key={acc.id}
								className="flex items-center gap-3 rounded-lg border p-3"
								style={{
									borderColor: "var(--surface0)",
									backgroundColor: "var(--base)",
								}}
							>
								<span
									className="flex h-10 w-10 items-center justify-center rounded-lg text-lg"
									style={{ backgroundColor: "var(--surface0)" }}
								>
									{acc.provider === "google"
										? "G"
										: acc.provider === "github"
											? "GH"
											: acc.provider.charAt(0).toUpperCase()}
								</span>
								<div>
									<div
										className="text-sm font-medium capitalize"
										style={{ color: "var(--text)" }}
									>
										{acc.provider}
									</div>
									<div className="text-xs" style={{ color: "var(--subtext0)" }}>
										{acc.email || acc.name || acc.provider_id}
									</div>
								</div>
								<span
									className="ml-auto text-xs"
									style={{ color: "var(--subtext0)" }}
								>
									{new Date(acc.created_at).toLocaleDateString("zh-TW")}
								</span>
							</div>
						))}
					</div>
				)}
			</div>

			{/* Info */}
			<div
				className="rounded-xl border p-5"
				style={{
					backgroundColor: "var(--mantle)",
					borderColor: "var(--surface0)",
				}}
			>
				<h2
					className="mb-4 text-base font-semibold"
					style={{ color: "var(--text)" }}
				>
					帳號資訊
				</h2>
				<dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
					<div>
						<dt style={{ color: "var(--subtext0)" }}>ID</dt>
						<dd
							className="mt-0.5 font-mono text-xs"
							style={{ color: "var(--text)" }}
						>
							{user.id}
						</dd>
					</div>
					<div>
						<dt style={{ color: "var(--subtext0)" }}>建立時間</dt>
						<dd className="mt-0.5" style={{ color: "var(--text)" }}>
							{new Date(user.created_at).toLocaleString("zh-TW")}
						</dd>
					</div>
				</dl>
			</div>
		</div>
	);
}

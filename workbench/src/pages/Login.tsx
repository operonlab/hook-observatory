import type React from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

type Tab = "login" | "register";

export default function Login() {
	const navigate = useNavigate();
	const { login, register, loading } = useAuth();

	const [tab, setTab] = useState<Tab>("login");
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [name, setName] = useState("");
	const [error, setError] = useState("");

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError("");

		if (!email.trim() || !password.trim()) {
			setError("請填寫所有必填欄位");
			return;
		}
		if (tab === "register" && !name.trim()) {
			setError("請填寫名稱");
			return;
		}
		if (password.length < 8) {
			setError("密碼至少需要 8 個字元");
			return;
		}

		try {
			if (tab === "login") {
				await login(email, password);
			} else {
				await register(email, password, name);
			}
			navigate("/");
		} catch (err) {
			setError(err instanceof Error ? err.message : "發生錯誤，請稍後再試");
		}
	};

	return (
		<div
			className="flex min-h-screen items-center justify-center p-4"
			style={{ backgroundColor: "var(--base)" }}
		>
			<div
				className="w-full max-w-sm rounded-2xl border p-6"
				style={{
					backgroundColor: "var(--mantle)",
					borderColor: "var(--surface0)",
				}}
			>
				{/* Logo */}
				<h1
					className="mb-6 text-center text-3xl font-bold"
					style={{ color: "var(--blue)" }}
				>
					Workshop
				</h1>

				{/* Tabs */}
				<div
					className="mb-5 flex rounded-lg p-1"
					style={{ backgroundColor: "var(--surface0)" }}
				>
					{(["login", "register"] as Tab[]).map((t) => (
						<button
							type="button"
							key={t}
							onClick={() => {
								setTab(t);
								setError("");
							}}
							className="flex-1 rounded-md py-2 text-sm font-medium transition-colors"
							style={{
								backgroundColor: tab === t ? "var(--mantle)" : "transparent",
								color: tab === t ? "var(--text)" : "var(--subtext0)",
								minHeight: 44,
							}}
						>
							{t === "login" ? "登入" : "註冊"}
						</button>
					))}
				</div>

				{/* Form */}
				<form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
					{tab === "register" && (
						<div>
							<label
								htmlFor="register-name"
								className="mb-1 block text-sm"
								style={{ color: "var(--subtext0)" }}
							>
								名稱
							</label>
							<input
								id="register-name"
								type="text"
								value={name}
								onChange={(e) => setName(e.target.value)}
								className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none focus:ring-2"
								style={{
									backgroundColor: "var(--base)",
									borderColor: "var(--surface0)",
									color: "var(--text)",
									minHeight: 44,
								}}
								placeholder="你的名稱"
								autoComplete="name"
							/>
						</div>
					)}

					<div>
						<label
							htmlFor="login-email"
							className="mb-1 block text-sm"
							style={{ color: "var(--subtext0)" }}
						>
							電子郵件
						</label>
						<input
							id="login-email"
							type="email"
							value={email}
							onChange={(e) => setEmail(e.target.value)}
							className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none focus:ring-2"
							style={{
								backgroundColor: "var(--base)",
								borderColor: "var(--surface0)",
								color: "var(--text)",
								minHeight: 44,
							}}
							placeholder="name@example.com"
							autoComplete="email"
						/>
					</div>

					<div>
						<label
							htmlFor="login-password"
							className="mb-1 block text-sm"
							style={{ color: "var(--subtext0)" }}
						>
							密碼
						</label>
						<input
							id="login-password"
							type="password"
							value={password}
							onChange={(e) => setPassword(e.target.value)}
							className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none focus:ring-2"
							style={{
								backgroundColor: "var(--base)",
								borderColor: "var(--surface0)",
								color: "var(--text)",
								minHeight: 44,
							}}
							placeholder="至少 8 個字元"
							autoComplete={
								tab === "login" ? "current-password" : "new-password"
							}
						/>
					</div>

					{/* Error */}
					{error && (
						<p
							className="rounded-lg px-3 py-2 text-sm"
							style={{
								backgroundColor: "var(--red)" + "15",
								color: "var(--red)",
							}}
						>
							{error}
						</p>
					)}

					{/* Submit */}
					<button
						type="submit"
						disabled={loading}
						className="w-full rounded-lg py-2.5 text-sm font-medium transition-opacity disabled:opacity-50"
						style={{
							backgroundColor: "var(--blue)",
							color: "var(--crust)",
							minHeight: 44,
						}}
					>
						{loading ? "處理中..." : tab === "login" ? "登入" : "建立帳號"}
					</button>
				</form>

				{/* OAuth divider */}
				<div className="my-5 flex items-center gap-3">
					<div
						className="h-px flex-1"
						style={{ backgroundColor: "var(--surface0)" }}
					/>
					<span className="text-xs" style={{ color: "var(--subtext0)" }}>
						或使用以下方式
					</span>
					<div
						className="h-px flex-1"
						style={{ backgroundColor: "var(--surface0)" }}
					/>
				</div>

				{/* OAuth buttons */}
				<div className="flex flex-col gap-3">
					<a
						href="/auth/oauth/google"
						className="flex h-11 items-center justify-center gap-2 rounded-lg border text-sm font-medium transition-opacity hover:opacity-80"
						style={{
							borderColor: "var(--surface0)",
							backgroundColor: "var(--base)",
							color: "var(--text)",
							minHeight: 44,
						}}
					>
						<svg
							width="18"
							height="18"
							viewBox="0 0 24 24"
							fill="none"
							aria-hidden="true"
						>
							<path
								d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
								fill="#4285F4"
							/>
							<path
								d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
								fill="#34A853"
							/>
							<path
								d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
								fill="#FBBC05"
							/>
							<path
								d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
								fill="#EA4335"
							/>
						</svg>
						使用 Google 登入
					</a>

					<a
						href="/auth/oauth/github"
						className="flex h-11 items-center justify-center gap-2 rounded-lg border text-sm font-medium transition-opacity hover:opacity-80"
						style={{
							borderColor: "var(--surface0)",
							backgroundColor: "var(--base)",
							color: "var(--text)",
							minHeight: 44,
						}}
					>
						<svg
							width="18"
							height="18"
							viewBox="0 0 24 24"
							fill="currentColor"
							aria-hidden="true"
						>
							<path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
						</svg>
						使用 GitHub 登入
					</a>
				</div>
			</div>
		</div>
	);
}

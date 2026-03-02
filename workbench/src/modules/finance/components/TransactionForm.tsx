import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { categoryApi, transactionApi, walletApi } from "../api";
import type {
	Category,
	PaymentMethod,
	Transaction,
	TransactionCreate,
	TransactionType,
	TransactionUpdate,
	Wallet,
} from "../types";
import { PAYMENT_METHOD_LABELS } from "../types";

interface TransactionFormProps {
	transaction?: Transaction | null;
	onClose: () => void;
	onSaved: () => void;
}

export default function TransactionForm({
	transaction,
	onClose,
	onSaved,
}: TransactionFormProps) {
	const isEdit = !!transaction;
	const [categories, setCategories] = useState<Category[]>([]);
	const [wallets, setWallets] = useState<Wallet[]>([]);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const [form, setForm] = useState({
		type: (transaction?.type ?? "expense") as TransactionType,
		amount: transaction?.amount?.toString() ?? "",
		description: transaction?.description ?? "",
		merchant: transaction?.merchant ?? "",
		payment_method: (transaction?.payment_method ??
			"credit_card") as PaymentMethod,
		payment_detail: transaction?.payment_detail ?? "",
		category_id: transaction?.category_id ?? "",
		wallet_id: transaction?.wallet_id ?? "",
		transfer_to_wallet_id: transaction?.transfer_to_wallet_id ?? "",
		tags: transaction?.tags?.join(", ") ?? "",
		transacted_at: transaction?.transacted_at
			? new Date(transaction.transacted_at).toISOString().slice(0, 16)
			: new Date().toISOString().slice(0, 16),
	});

	useEffect(() => {
		categoryApi
			.list()
			.then(setCategories)
			.catch(() => {});
		walletApi
			.list()
			.then((r) => setWallets(r.items))
			.catch(() => {});
	}, []);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setSaving(true);
		setError(null);

		const tags = form.tags
			.split(",")
			.map((t) => t.trim())
			.filter(Boolean);

		try {
			if (isEdit && transaction) {
				const data: TransactionUpdate = {
					type: form.type,
					amount: Number(form.amount),
					description: form.description || undefined,
					merchant: form.merchant || undefined,
					payment_method: form.payment_method,
					payment_detail: form.payment_detail || undefined,
					category_id: form.category_id || undefined,
					wallet_id: form.wallet_id || undefined,
					tags,
					transacted_at: new Date(form.transacted_at).toISOString(),
				};
				await transactionApi.update(transaction.id, data);
			} else {
				const data: TransactionCreate = {
					type: form.type,
					amount: Number(form.amount),
					description: form.description || undefined,
					merchant: form.merchant || undefined,
					payment_method: form.payment_method,
					payment_detail: form.payment_detail || undefined,
					category_id: form.category_id || undefined,
					wallet_id: form.wallet_id,
					transfer_to_wallet_id:
						form.type === "transfer"
							? form.transfer_to_wallet_id || undefined
							: undefined,
					tags,
					transacted_at: new Date(form.transacted_at).toISOString(),
				};
				await transactionApi.create(data);
			}
			onSaved();
			onClose();
		} catch (err) {
			setError(err instanceof Error ? err.message : "儲存失敗");
		} finally {
			setSaving(false);
		}
	};

	const fieldStyle = {
		borderColor: "var(--fn-border)",
		backgroundColor: "var(--fn-bg-surface)",
		color: "var(--fn-text)",
	};

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
			<div
				className="w-full max-w-lg mx-4 rounded-lg border overflow-y-auto max-h-[90vh]"
				style={{
					backgroundColor: "var(--fn-bg-elevated)",
					borderColor: "var(--fn-border)",
				}}
			>
				<div
					className="flex items-center justify-between px-5 py-4 border-b"
					style={{ borderColor: "var(--fn-border)" }}
				>
					<h2
						className="text-sm font-medium"
						style={{ color: "var(--fn-text)" }}
					>
						{isEdit ? "編輯交易" : "新增交易"}
					</h2>
					<button
						type="button"
						onClick={onClose}
						style={{ color: "var(--fn-text-muted)" }}
					>
						<X size={18} />
					</button>
				</div>

				<form onSubmit={handleSubmit} className="p-5 space-y-4">
					{error && (
						<div
							className="px-3 py-2 rounded text-xs"
							style={{
								backgroundColor: "rgba(243, 139, 168, 0.1)",
								color: "var(--fn-expense)",
							}}
						>
							{error}
						</div>
					)}

					{/* Type */}
					<div className="flex gap-2">
						{(["expense", "income", "transfer"] as TransactionType[]).map(
							(t) => (
								<button
									key={t}
									type="button"
									onClick={() => setForm((f) => ({ ...f, type: t }))}
									className="flex-1 py-2 text-xs rounded border transition-colors"
									style={{
										borderColor:
											form.type === t ? "var(--fn-accent)" : "var(--fn-border)",
										backgroundColor:
											form.type === t
												? "var(--fn-accent-alpha)"
												: "transparent",
										color:
											form.type === t
												? "var(--fn-accent)"
												: "var(--fn-text-tertiary)",
									}}
								>
									{t === "expense" ? "支出" : t === "income" ? "收入" : "轉帳"}
								</button>
							),
						)}
					</div>

					{/* Amount + Date row */}
					<div className="grid grid-cols-2 gap-3">
						<label className="space-y-1">
							<span
								className="text-[11px]"
								style={{ color: "var(--fn-text-tertiary)" }}
							>
								金額
							</span>
							<input
								type="number"
								step="0.01"
								required
								value={form.amount}
								onChange={(e) =>
									setForm((f) => ({ ...f, amount: e.target.value }))
								}
								className="w-full px-3 py-2 text-sm rounded border"
								style={fieldStyle}
							/>
						</label>
						<label className="space-y-1">
							<span
								className="text-[11px]"
								style={{ color: "var(--fn-text-tertiary)" }}
							>
								日期
							</span>
							<input
								type="datetime-local"
								required
								value={form.transacted_at}
								onChange={(e) =>
									setForm((f) => ({ ...f, transacted_at: e.target.value }))
								}
								className="w-full px-3 py-2 text-sm rounded border"
								style={fieldStyle}
							/>
						</label>
					</div>

					{/* Description + Merchant */}
					<div className="grid grid-cols-2 gap-3">
						<label className="space-y-1">
							<span
								className="text-[11px]"
								style={{ color: "var(--fn-text-tertiary)" }}
							>
								描述
							</span>
							<input
								type="text"
								value={form.description}
								onChange={(e) =>
									setForm((f) => ({ ...f, description: e.target.value }))
								}
								className="w-full px-3 py-2 text-sm rounded border"
								style={fieldStyle}
							/>
						</label>
						<label className="space-y-1">
							<span
								className="text-[11px]"
								style={{ color: "var(--fn-text-tertiary)" }}
							>
								商家
							</span>
							<input
								type="text"
								value={form.merchant}
								onChange={(e) =>
									setForm((f) => ({ ...f, merchant: e.target.value }))
								}
								className="w-full px-3 py-2 text-sm rounded border"
								style={fieldStyle}
							/>
						</label>
					</div>

					{/* Payment + Wallet */}
					<div className="grid grid-cols-2 gap-3">
						<label className="space-y-1">
							<span
								className="text-[11px]"
								style={{ color: "var(--fn-text-tertiary)" }}
							>
								付款方式
							</span>
							<select
								value={form.payment_method}
								onChange={(e) =>
									setForm((f) => ({
										...f,
										payment_method: e.target.value as PaymentMethod,
									}))
								}
								className="w-full px-3 py-2 text-sm rounded border"
								style={fieldStyle}
							>
								{Object.entries(PAYMENT_METHOD_LABELS).map(([k, v]) => (
									<option key={k} value={k}>
										{v}
									</option>
								))}
							</select>
						</label>
						<label className="space-y-1">
							<span
								className="text-[11px]"
								style={{ color: "var(--fn-text-tertiary)" }}
							>
								錢包
							</span>
							<select
								value={form.wallet_id}
								onChange={(e) =>
									setForm((f) => ({ ...f, wallet_id: e.target.value }))
								}
								required
								className="w-full px-3 py-2 text-sm rounded border"
								style={fieldStyle}
							>
								<option value="">選擇錢包</option>
								{wallets.map((w) => (
									<option key={w.id} value={w.id}>
										{w.name}
									</option>
								))}
							</select>
						</label>
					</div>

					{/* Transfer target wallet */}
					{form.type === "transfer" && (
						<label className="space-y-1">
							<span
								className="text-[11px]"
								style={{ color: "var(--fn-text-tertiary)" }}
							>
								轉入錢包
							</span>
							<select
								value={form.transfer_to_wallet_id}
								onChange={(e) =>
									setForm((f) => ({
										...f,
										transfer_to_wallet_id: e.target.value,
									}))
								}
								required
								className="w-full px-3 py-2 text-sm rounded border"
								style={fieldStyle}
							>
								<option value="">選擇目標錢包</option>
								{wallets
									.filter((w) => w.id !== form.wallet_id)
									.map((w) => (
										<option key={w.id} value={w.id}>
											{w.name}
										</option>
									))}
							</select>
						</label>
					)}

					{/* Category */}
					<label className="space-y-1">
						<span
							className="text-[11px]"
							style={{ color: "var(--fn-text-tertiary)" }}
						>
							分類
						</span>
						<select
							value={form.category_id}
							onChange={(e) =>
								setForm((f) => ({ ...f, category_id: e.target.value }))
							}
							className="w-full px-3 py-2 text-sm rounded border"
							style={fieldStyle}
						>
							<option value="">未分類</option>
							{categories.map((c) => (
								<option key={c.id} value={c.id}>
									{c.icon ? `${c.icon} ` : ""}
									{c.name}
								</option>
							))}
						</select>
					</label>

					{/* Tags */}
					<label className="space-y-1">
						<span
							className="text-[11px]"
							style={{ color: "var(--fn-text-tertiary)" }}
						>
							標籤（逗號分隔）
						</span>
						<input
							type="text"
							value={form.tags}
							onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
							className="w-full px-3 py-2 text-sm rounded border"
							placeholder="午餐, 同事"
							style={fieldStyle}
						/>
					</label>

					{/* Submit */}
					<div className="flex justify-end gap-2 pt-2">
						<button
							type="button"
							onClick={onClose}
							className="px-4 py-2 text-xs rounded"
							style={{ color: "var(--fn-text-tertiary)" }}
						>
							取消
						</button>
						<button
							type="submit"
							disabled={saving}
							className="px-4 py-2 text-xs rounded font-medium disabled:opacity-50"
							style={{
								backgroundColor: "var(--fn-accent)",
								color: "var(--fn-bg)",
							}}
						>
							{saving ? "儲存中..." : isEdit ? "更新" : "新增"}
						</button>
					</div>
				</form>
			</div>
		</div>
	);
}

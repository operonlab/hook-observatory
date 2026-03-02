import { Eye, EyeOff } from "lucide-react";

interface PrivacyToggleProps {
	isPrivate: boolean;
	onToggle: () => void;
	size?: "sm" | "md";
}

export default function PrivacyToggle({
	isPrivate,
	onToggle,
	size = "sm",
}: PrivacyToggleProps) {
	const iconSize = size === "sm" ? 14 : 18;

	return (
		<button
			type="button"
			onClick={(e) => {
				e.stopPropagation();
				onToggle();
			}}
			className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-colors"
			style={{
				backgroundColor: isPrivate
					? "rgba(243, 139, 168, 0.15)"
					: "rgba(166, 227, 161, 0.1)",
				color: isPrivate ? "var(--fn-expense)" : "var(--fn-text-muted)",
			}}
			title={isPrivate ? "隱密項目（僅自己可見）" : "公開項目"}
		>
			{isPrivate ? <EyeOff size={iconSize} /> : <Eye size={iconSize} />}
			{size === "md" && (isPrivate ? "隱密" : "公開")}
		</button>
	);
}

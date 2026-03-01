const ROLE_STYLES: Record<string, { bg: string; text: string; label: string }> =
	{
		admin: { bg: "var(--mauve)", text: "var(--base)", label: "Admin" },
		user: { bg: "var(--blue)", text: "var(--base)", label: "User" },
		guest: { bg: "var(--overlay0)", text: "var(--base)", label: "Guest" },
	};

export default function RoleBadge({ role }: { role: string }) {
	const style = ROLE_STYLES[role] ?? {
		bg: "var(--surface0)",
		text: "var(--text)",
		label: role,
	};
	return (
		<span
			className="inline-block rounded-full px-2 py-0.5 text-xs font-medium"
			style={{ backgroundColor: style.bg, color: style.text }}
		>
			{style.label}
		</span>
	);
}

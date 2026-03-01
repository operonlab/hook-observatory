import { useAuth } from "@/hooks/useAuth";

interface NavBarProps {
	onToggleSidebar: () => void;
}

export default function NavBar({ onToggleSidebar }: NavBarProps) {
	const { user, logout } = useAuth();

	return (
		<nav
			className="fixed top-0 left-0 right-0 z-50 flex h-14 items-center justify-between border-b px-4"
			style={{
				backgroundColor: "var(--mantle)",
				borderColor: "var(--surface0)",
			}}
		>
			{/* Left side */}
			<div className="flex items-center gap-3">
				{/* Mobile hamburger */}
				<button
					type="button"
					onClick={onToggleSidebar}
					className="flex h-10 w-10 items-center justify-center rounded-lg md:hidden"
					style={{ minHeight: 44, minWidth: 44 }}
					aria-label="Toggle sidebar"
				>
					<svg
						width="20"
						height="20"
						viewBox="0 0 20 20"
						fill="none"
						aria-hidden="true"
					>
						<path
							d="M3 5h14M3 10h14M3 15h14"
							stroke="currentColor"
							strokeWidth="2"
							strokeLinecap="round"
						/>
					</svg>
				</button>

				{/* Logo */}
				<span className="text-xl font-bold" style={{ color: "var(--blue)" }}>
					Workshop
				</span>
			</div>

			{/* Right side */}
			<div className="flex items-center gap-2">
				{/* User info */}
				{user && (
					<span
						className="hidden text-sm sm:block"
						style={{ color: "var(--subtext0)" }}
					>
						{user.display_name}
					</span>
				)}

				{/* Logout */}
				{user && (
					<button
						type="button"
						onClick={() => void logout()}
						className="flex h-10 items-center rounded-lg px-3 text-sm hover:opacity-80"
						style={{
							minHeight: 44,
							color: "var(--subtext0)",
							backgroundColor: "transparent",
						}}
					>
						登出
					</button>
				)}
			</div>
		</nav>
	);
}

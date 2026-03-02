import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: number | string;
  accent?: boolean;
}

export default function StatCard({ icon: Icon, label, value, accent }: StatCardProps) {
  return (
    <div
      className="flex flex-col gap-2 border p-4 sm:p-5"
      style={{
        backgroundColor: "var(--if-bg-elevated)",
        borderColor: accent ? "var(--if-accent)" : "var(--if-border)",
      }}
    >
      <div className="flex items-center gap-2">
        <Icon
          size={15}
          style={{ color: accent ? "var(--if-accent)" : "var(--if-text-muted)" }}
        />
        <span
          className="text-[10px] sm:text-xs uppercase tracking-widest"
          style={{ color: "var(--if-text-tertiary)" }}
        >
          {label}
        </span>
      </div>
      <span
        className="text-2xl sm:text-3xl font-light"
        style={{
          fontFamily: "var(--if-font-display)",
          color: accent ? "var(--if-accent)" : "var(--if-text)",
        }}
      >
        {value}
      </span>
    </div>
  );
}

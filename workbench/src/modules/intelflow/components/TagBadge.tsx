interface TagBadgeProps {
  tag: string;
  active?: boolean;
  onClick?: () => void;
}

export default function TagBadge({ tag, active, onClick }: TagBadgeProps) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center px-3 py-2 sm:py-1 text-xs border transition-colors min-h-[36px] sm:min-h-0"
      style={{
        backgroundColor: active ? "var(--if-accent)" : "transparent",
        borderColor: active ? "var(--if-accent)" : "var(--if-border)",
        color: active ? "var(--if-text-on-accent)" : "var(--if-text-secondary)",
      }}
      onMouseEnter={(e) => {
        if (!active) {
          e.currentTarget.style.borderColor = "var(--if-accent)";
          e.currentTarget.style.color = "var(--if-accent)";
        }
      }}
      onMouseLeave={(e) => {
        if (!active) {
          e.currentTarget.style.borderColor = "var(--if-border)";
          e.currentTarget.style.color = "var(--if-text-secondary)";
        }
      }}
    >
      {tag}
    </button>
  );
}

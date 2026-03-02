import type { TooltipProps } from "recharts";

/** Null-safe recharts Tooltip — guards against undefined payload entries. */
export default function ChartTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;

  return (
    <div
      style={{
        background: "#1a1b2e",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: 6,
        padding: "8px 12px",
        fontSize: 12,
      }}
    >
      {label && (
        <p style={{ color: "rgba(255,255,255,0.7)", marginBottom: 4 }}>{label}</p>
      )}
      {payload.map((entry, i) =>
        entry?.value != null ? (
          <p key={i} style={{ color: entry.color ?? "#89b4fa" }}>
            {entry.name}: {entry.value.toLocaleString()}
          </p>
        ) : null,
      )}
    </div>
  );
}

interface RelevanceBadgeProps {
  relevance?: string | null
}

const RELEVANCE_MAP: Record<string, { color: string; bg: string; border: string; label: string }> =
  {
    high: {
      color: '#a6e3a1',
      bg: 'rgba(166,227,161,0.12)',
      border: 'rgba(166,227,161,0.5)',
      label: '高價值',
    },
    medium: {
      color: '#f9e2af',
      bg: 'rgba(249,226,175,0.10)',
      border: 'rgba(249,226,175,0.45)',
      label: '中價值',
    },
    low: {
      color: '#9399b2',
      bg: 'rgba(147,153,178,0.08)',
      border: 'rgba(147,153,178,0.35)',
      label: '低價值',
    },
  }

export default function RelevanceBadge({ relevance }: RelevanceBadgeProps) {
  const tier = RELEVANCE_MAP[relevance ?? 'low'] ?? RELEVANCE_MAP.low

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '2px 8px',
        fontSize: '10px',
        letterSpacing: '0.06em',
        border: `1px solid ${tier.border}`,
        backgroundColor: tier.bg,
        color: tier.color,
        fontFamily: 'var(--pp-font-ui)',
        flexShrink: 0,
      }}
    >
      <span
        style={{
          display: 'inline-block',
          width: 5,
          height: 5,
          backgroundColor: tier.color,
          flexShrink: 0,
        }}
      />
      {tier.label}
    </span>
  )
}

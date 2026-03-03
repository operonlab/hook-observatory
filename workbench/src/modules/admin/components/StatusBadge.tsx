const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  active: { bg: 'var(--green)', text: 'var(--base)', label: 'Active' },
  pending: { bg: 'var(--yellow)', text: 'var(--base)', label: 'Pending' },
  suspended: { bg: 'var(--peach)', text: 'var(--base)', label: 'Suspended' },
  banned: { bg: 'var(--red)', text: 'var(--base)', label: 'Banned' },
}

export default function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? {
    bg: 'var(--surface0)',
    text: 'var(--text)',
    label: status,
  }
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ backgroundColor: style.bg, color: style.text }}
    >
      {style.label}
    </span>
  )
}

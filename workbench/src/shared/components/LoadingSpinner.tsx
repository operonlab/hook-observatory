export function LoadingSpinner({ text = 'Loading...' }: { text?: string }) {
  return (
    <div className="flex items-center justify-center p-8 text-[var(--text-secondary)]">
      <div className="animate-spin rounded-full h-5 w-5 border-2 border-current border-t-transparent mr-2" />
      <span className="text-sm">{text}</span>
    </div>
  )
}

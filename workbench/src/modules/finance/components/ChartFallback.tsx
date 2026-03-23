export default function ChartFallback({ height = 'h-64' }: { height?: string }) {
  return <div className={`animate-pulse ${height} bg-white/5 rounded`} />
}

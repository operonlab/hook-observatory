import { Archive } from 'lucide-react'
import { useEffect, useState } from 'react'
import { type CaptureStats, captureApi } from './api'

export default function CaptureBadge() {
  const [stats, setStats] = useState<CaptureStats | null>(null)

  useEffect(() => {
    captureApi
      .stats()
      .then(setStats)
      .catch(() => {})
    // Poll every 30s
    const interval = setInterval(() => {
      captureApi
        .stats()
        .then(setStats)
        .catch(() => {})
    }, 30000)
    return () => clearInterval(interval)
  }, [])

  const pending = stats?.by_status?.pending ?? 0
  if (pending === 0) return null

  return (
    <button
      type="button"
      className="relative p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
      title={`${pending} pending captures`}
    >
      <Archive size={18} className="text-gray-500 dark:text-gray-400" />
      <span className="absolute -top-1 -right-1 min-w-[16px] h-4 flex items-center justify-center text-[10px] font-bold text-white bg-amber-500 rounded-full px-1">
        {pending > 99 ? '99+' : pending}
      </span>
    </button>
  )
}

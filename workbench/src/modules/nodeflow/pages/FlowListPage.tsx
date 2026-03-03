import { useCallback, useEffect, useState } from 'react'
import type { PaginatedResponse } from '@/types'
import { flowApi } from '../api'
import FlowCard from '../components/FlowCard'
import type { Flow } from '../types'

export default function FlowListPage() {
  const [flows, setFlows] = useState<Flow[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = (await flowApi.list(1, 50)) as PaginatedResponse<Flow>
      setFlows(res.items)
    } catch {
      // empty state
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) {
    return (
      <div className="animate-pulse rounded-xl p-6" style={{ backgroundColor: 'var(--surface0)' }}>
        <div className="h-6 w-32 rounded" style={{ backgroundColor: 'var(--surface1)' }} />
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold" style={{ color: 'var(--text)' }}>
          事件流程
        </h2>
      </div>

      {flows.length === 0 ? (
        <div
          className="rounded-xl p-8 text-center"
          style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext0)' }}
        >
          尚無流程。建立第一個事件流程來自動化跨模組工作。
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {flows.map((flow) => (
            <FlowCard key={flow.id} flow={flow} />
          ))}
        </div>
      )}
    </div>
  )
}
